#!/usr/bin/env python3
"""Reverse an anonymization job: restore the original terms in a model's output.

The round-trip key (emitted by `apply.py --emit-key`) is the only thing that can
re-identify the text. It stays local. This script never sends anything anywhere.

Reversing is not symmetric, and the script refuses to guess:
  * many-to-one targets (two originals became one replacement) are left untouched
    until a decision is supplied via --decisions;
  * target forms the model produced that the forward pass never created (new case,
    plural, derivation) are reported so they can be added to `reverse_extra`;
  * `protect_reverse` keeps legitimate mentions of the target locale intact.

Usage:
  python scripts/restore.py <paths...> --key key.json --dry-run
  python scripts/restore.py <paths...> --key key.json --backup-dir ./backup-restore
  python scripts/restore.py <paths...> --key key.json --decisions decisions.json \
      --verify-against ./backup-anon
"""
import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

SENTINEL = "\x00"


def mask_spans(text, fragments):
    """Mask protected spans (legitimate target-locale mentions) before reversing."""
    if not fragments:
        return text, []
    if SENTINEL in text:
        raise ValueError("file contains NUL bytes; protected replacement is unsafe here")
    spans = []
    low = text.lower()
    for frag in fragments:
        if not frag:
            continue
        start = 0
        needle = frag.lower()
        while True:
            idx = low.find(needle, start)
            if idx < 0:
                break
            spans.append((idx, idx + len(frag)))
            start = idx + len(frag)
    if not spans:
        return text, []
    spans.sort()
    merged = []
    for begin, end in spans:
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((begin, end))
    pieces, cursor = [], 0
    for i, (begin, end) in enumerate(merged):
        pieces.append(text[cursor:begin])
        pieces.append("%sPROTECT%d%s" % (SENTINEL, i, SENTINEL))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), [text[b:e] for b, e in merged]


def unmask(text, originals):
    for i, original in enumerate(originals):
        text = text.replace("%sPROTECT%d%s" % (SENTINEL, i, SENTINEL), original)
    return text


def replace_ambiguous(text, target, sources, decisions):
    """Resolve an ambiguous target occurrence by occurrence, using context rules.

    Case-sensitive, mirroring the forward pass. Unresolved occurrences are kept
    verbatim and reported - guessing here would silently corrupt the text.
    """
    out, cursor, pending, resolved = [], 0, [], 0
    for m in re.finditer(re.escape(target), text):
        out.append(text[cursor:m.start()])
        lineno, ctx = common.snippet_at(text, m.start(), m.end(), 120)
        choice = common.resolve_choice(target, ctx, decisions)
        if choice and choice in sources:
            out.append(choice)
            resolved += 1
        else:
            out.append(m.group(0))
            pending.append({"target": target, "line": lineno, "context": ctx,
                            "options": sources})
        cursor = m.end()
    out.append(text[cursor:])
    return "".join(out), resolved, pending


def find_counterpart(verify_root, path):
    """Locate the pre-anonymization original for a restored file."""
    if os.path.isfile(verify_root):
        return verify_root
    base = os.path.basename(path)
    for root, _dirs, files in os.walk(verify_root):
        if base in files:
            return os.path.join(root, base)
    return None


def main():
    ap = argparse.ArgumentParser(description="Restore original terms from a round-trip key.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--key", required=True, help="round-trip key from apply.py --emit-key")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument("--backup-dir", help="copy the anonymized input here before writing")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--decisions", help="JSON resolving ambiguous targets")
    ap.add_argument("--decisions-template", help="write a decisions skeleton for ambiguous targets here")
    ap.add_argument("--verify-against", help="file or directory with the pre-anonymization originals")
    ap.add_argument("--ext", help="comma-separated extensions to include")
    ap.add_argument("--exclude", help="comma-separated directory names to skip")
    ap.add_argument("--include-hidden", action="store_true")
    ap.add_argument("--report", help="write a JSON report here")
    args = ap.parse_args()

    try:
        key = common.load_key(args.key)
    except (ValueError, OSError) as exc:
        common.eprint("key error: %s" % exc)
        return 2

    decisions = {}
    if args.decisions:
        with open(args.decisions, "r", encoding="utf-8-sig") as fh:
            decisions = json.load(fh)

    ambiguous = key.get("ambiguous") or {}
    if args.decisions_template:
        skeleton = {t: [{"contains": "<context fragment>", "choose": srcs[0]}
                        for _ in srcs] + [{"default": srcs[0]}]
                    for t, srcs in ambiguous.items()}
        common.dump_json(args.decisions_template, skeleton)
        print("decisions template: %s" % args.decisions_template)
        for t, srcs in ambiguous.items():
            print("   %s  <-  %s" % (t, " | ".join(srcs)))
        return 0

    pairs = common.reverse_pairs(key)
    protect = key.get("protect_reverse") or []
    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    exclude = [e.strip() for e in args.exclude.split(",")] if args.exclude else None

    if not args.dry_run and not args.backup_dir and not args.no_backup:
        common.eprint("refusing to write without --backup-dir or --no-backup")
        return 2

    files = list(common.iter_files(args.paths, exts, exclude, args.include_hidden))
    changed, errors, skipped = [], [], []
    all_pending, all_unknown, verifications = [], [], []
    pair_totals = Counter()
    backups = 0

    for path in files:
        text, enc = common.read_text(path)
        if text is None:
            skipped.append({"path": path, "reason": "not decodable as text"})
            continue

        try:
            masked, originals = mask_spans(text, protect)
        except ValueError as exc:
            skipped.append({"path": path, "reason": str(exc)})
            continue

        # Detect uncovered forms after masking, so protected legitimate mentions
        # of the target locale are not reported as something to reverse.
        unknown = common.unknown_target_forms(masked, key)
        if unknown:
            all_unknown.append({"path": path, "forms": unknown})

        counts = Counter()
        pending = []
        for pair in pairs:
            src, dst = pair["from"], pair["to"]
            if src in ambiguous:
                masked, n, pend = replace_ambiguous(masked, src, ambiguous[src], decisions)
                pending += pend
            else:
                n = masked.count(src)
                if n:
                    masked = masked.replace(src, dst)
            if n:
                counts[src] += n

        new_text = unmask(masked, originals)
        if pending:
            all_pending.append({"path": path, "occurrences": pending})
        if new_text == text:
            continue

        err = common.validate_structured(path, new_text)
        if err:
            errors.append({"path": path, "error": err, "action": "rolled back, file untouched"})
            continue

        if not args.dry_run:
            if args.backup_dir:
                dest = os.path.join(args.backup_dir, os.path.basename(path))
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                shutil.copy2(path, dest)
                backups += 1
            common.write_text(path, new_text, enc)

        changed.append({"path": path, "restored": dict(counts), "total": sum(counts.values())})
        pair_totals.update(counts)

        if args.verify_against:
            counterpart = find_counterpart(args.verify_against, path)
            if counterpart is None:
                verifications.append({"path": path, "status": "no counterpart found"})
            else:
                orig, _ = common.read_text(counterpart)
                if orig is None:
                    verifications.append({"path": path, "status": "counterpart unreadable"})
                elif orig == new_text:
                    verifications.append({"path": path, "status": "identical",
                                          "counterpart": counterpart})
                else:
                    verifications.append({"path": path, "status": "differs",
                                          "counterpart": counterpart,
                                          "note": "expected when the model edited the text"})

    problems = len(all_pending) + len(all_unknown) + len(errors)
    report = {
        "key": os.path.abspath(args.key), "dry_run": bool(args.dry_run),
        "scanned_files": len(files), "changed_files": len(changed),
        "backups_written": backups, "pair_totals": dict(pair_totals),
        "changed": changed, "pending_ambiguities": all_pending,
        "unknown_target_forms": all_unknown, "roundtrip": verifications,
        "errors": errors, "skipped": skipped, "problems": problems,
    }
    common.dump_json(args.report, report)

    print("%s: %d/%d files restored, %d terms put back"
          % ("DRY RUN" if args.dry_run else "RESTORED", len(changed), len(files),
             sum(pair_totals.values())))
    for src, n in pair_totals.most_common():
        dst = next(p["to"] for p in pairs if p["from"] == src)
        print("   %4d  %s  ->  %s" % (n, src, dst))
    if all_pending:
        print("\n-- AMBIGUOUS: left untouched, needs a decision --")
        for entry in all_pending:
            for occ in entry["occurrences"][:20]:
                print("   %s:%s  %s  <-  %s" % (entry["path"], occ["line"], occ["target"],
                                                " | ".join(occ["options"])))
                print("        %s" % occ["context"][:110])
        print("   resolve with --decisions (skeleton: --decisions-template out.json)")
    if all_unknown:
        print("\n-- UNKNOWN TARGET FORMS: add to key.reverse_extra --")
        for entry in all_unknown:
            for f in entry["forms"]:
                print("   %-28s x%d  (%s)" % (f["form"], f["count"], entry["path"]))
    if verifications:
        print("\n-- round-trip check --")
        for v in verifications:
            print("   [%s] %s" % (v["status"], v["path"]))
    if errors:
        print("\n-- ERRORS (files left untouched) --")
        for e in errors:
            print("   %s: %s" % (e["path"], e["error"]))
    if not args.dry_run and args.backup_dir:
        print("\nbackups: %d files in %s" % (backups, args.backup_dir))
    print("\nRESULT: %s" % ("CLEAN" if problems == 0 else "%d item(s) need attention" % problems))
    if args.report:
        print("report: %s" % args.report)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

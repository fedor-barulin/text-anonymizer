#!/usr/bin/env python3
"""Apply an approved mapping: ordered, protected replacement with backup and rollback.

Why the pieces exist:
  * longest-first ordering - a short pair applied early eats the context a longer
    pair needed, which produces duplicated tokens;
  * protect list - brand roots live inside ordinary words (motivation, leitmotif,
    surnames, unrelated companies); masking them first is what keeps prose intact;
  * backup - bulk edits without version control are unrecoverable;
  * structured-file validation - a replacement inside JSON must not break parsing.

Usage:
  python scripts/apply.py --mapping mapping.json <paths...> --dry-run
  python scripts/apply.py --mapping mapping.json <paths...> --backup-dir work/backup-anon
"""
import argparse
import os
import shutil
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

SENTINEL = "\x00"


def mask_protected(text, protect):
    """Replace protected spans with sentinels; return (masked_text, spans)."""
    if not protect:
        return text, []
    if SENTINEL in text:
        raise ValueError("file contains NUL bytes; protected replacement is unsafe here")
    spans = []
    for frag in protect:
        if not frag:
            continue
        start = 0
        low = text.lower()
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
    pieces = []
    cursor = 0
    for i, (begin, end) in enumerate(merged):
        pieces.append(text[cursor:begin])
        pieces.append("%sPROTECT%d%s" % (SENTINEL, i, SENTINEL))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), [text[b:e] for b, e in merged]


def restore_protected(text, originals):
    for i, original in enumerate(originals):
        text = text.replace("%sPROTECT%d%s" % (SENTINEL, i, SENTINEL), original)
    return text


def replace_all(text, pairs):
    counts = Counter()
    for pair in pairs:
        src, dst = pair["from"], pair["to"]
        n = text.count(src)
        if n:
            text = text.replace(src, dst)
            counts[src] += n
    return text, counts


def anchor_for(paths):
    resolved = [os.path.abspath(p) for p in paths]
    if len(resolved) == 1 and os.path.isfile(resolved[0]):
        return os.path.dirname(resolved[0])
    existing = [p if os.path.isdir(p) else os.path.dirname(p) for p in resolved]
    return os.path.commonpath(existing) if existing else os.getcwd()


def main():
    ap = argparse.ArgumentParser(description="Apply an anonymization mapping.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--mapping", required=True, help="mapping JSON (see assets/mapping.example.json)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument("--backup-dir", help="copy originals here before writing (strongly recommended)")
    ap.add_argument("--no-backup", action="store_true", help="skip backup even without version control")
    ap.add_argument("--ext", help="comma-separated extensions to include")
    ap.add_argument("--exclude", help="comma-separated directory names to skip")
    ap.add_argument("--include-hidden", action="store_true")
    ap.add_argument("--report", help="write a JSON report here")
    ap.add_argument("--emit-key", help="write a round-trip key here so restore.py can reverse the job "
                                       "(the key re-identifies the text: keep it local, never in a prompt)")
    args = ap.parse_args()

    try:
        mapping = common.load_mapping(args.mapping)
    except (ValueError, OSError) as exc:
        common.eprint("mapping error: %s" % exc)
        return 2

    pairs = common.sorted_pairs(mapping)
    protect = mapping.get("protect") or []
    targets = [p["to"] for p in pairs]
    allowed = common.expected_forms(mapping)
    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    exclude = [e.strip() for e in args.exclude.split(",")] if args.exclude else None

    if not args.dry_run and not args.backup_dir and not args.no_backup:
        common.eprint("refusing to write without --backup-dir or --no-backup: "
                      "bulk replacement is unrecoverable otherwise")
        return 2

    anchor = anchor_for(args.paths)
    files = list(common.iter_files(args.paths, exts, exclude, args.include_hidden))
    changed, artifacts, errors, skipped = [], [], [], []
    pair_totals = Counter()
    backups = 0

    for path in files:
        text, enc = common.read_text(path)
        if text is None:
            skipped.append({"path": path, "reason": "not decodable as text"})
            continue
        try:
            masked, originals = mask_protected(text, protect)
        except ValueError as exc:
            skipped.append({"path": path, "reason": str(exc)})
            continue
        new_masked, counts = replace_all(masked, pairs)
        if not counts:
            continue
        new_text = restore_protected(new_masked, originals)
        if new_text == text:
            continue

        rel = os.path.relpath(path, anchor)
        entry = {"path": path, "replacements": dict(counts),
                 "total": sum(counts.values())}

        err = common.validate_structured(path, new_text)
        if err:
            errors.append({"path": path, "error": err, "action": "rolled back, file untouched"})
            continue

        found = common.find_artifacts(new_text, targets, allowed)
        if found:
            artifacts.append({"path": path, "items": found})

        if not args.dry_run:
            if args.backup_dir:
                dest = os.path.join(args.backup_dir, rel)
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                shutil.copy2(path, dest)
                backups += 1
            if args.emit_key:
                entry["sha256_before"] = common.sha256_file(path)
            common.write_text(path, new_text, enc)
            if args.emit_key:
                entry["sha256_after"] = common.sha256_file(path)

        entry["artifacts"] = found
        changed.append(entry)
        pair_totals.update(counts)

    report = {
        "mapping": os.path.abspath(args.mapping),
        "target_locale": mapping.get("target_locale"),
        "mode": mapping.get("mode", "substitute"),
        "dry_run": bool(args.dry_run),
        "scanned_files": len(files),
        "changed_files": len(changed),
        "backups_written": backups,
        "pair_totals": dict(pair_totals),
        "changed": changed,
        "artifacts": artifacts,
        "errors": errors,
        "skipped": skipped,
    }
    common.dump_json(args.report, report)

    if args.emit_key and not args.dry_run:
        documents = [{"path": e["path"],
                      "sha256_before": e.get("sha256_before"),
                      "sha256_after": e.get("sha256_after")} for e in changed]
        key = common.build_key(mapping, documents)
        common.dump_json(args.emit_key, key)
        print("\nround-trip key: %s" % args.emit_key)
        print("It maps every replacement back to the original. Keep it local and out of git,")
        print("and never paste it into a prompt - it fully re-identifies the text.")
        if key["ambiguous"]:
            print("Ambiguous targets (restore.py will leave these untouched until you decide):")
            for t, srcs in key["ambiguous"].items():
                print("   %s  <-  %s" % (t, " | ".join(srcs)))
    elif args.emit_key and args.dry_run:
        print("\n--emit-key skipped in dry run: nothing was written, so there is nothing to key")

    print("%s: %d/%d files changed, %d replacements"
          % ("DRY RUN" if args.dry_run else "APPLIED", len(changed), len(files), sum(pair_totals.values())))
    for src, n in pair_totals.most_common():
        dst = next(p["to"] for p in pairs if p["from"] == src)
        print("   %4d  %s  ->  %s" % (n, src, dst))
    if changed:
        print("\n-- changed files --")
        for entry in sorted(changed, key=lambda e: -e["total"]):
            print("%5d  %s" % (entry["total"], entry["path"]))
    if artifacts:
        print("\n-- artifacts to review in the language pass --")
        for a in artifacts:
            for item in a["items"]:
                print("   [%s] %s  (%s)" % (item["kind"], item["token"], a["path"]))
    if errors:
        print("\n-- ERRORS (files left untouched) --")
        for e in errors:
            print("   %s: %s" % (e["path"], e["error"]))
    if skipped:
        print("\n-- skipped --")
        for s in skipped:
            print("   %s: %s" % (s["path"], s["reason"]))
    if not args.dry_run and args.backup_dir:
        print("\nbackups: %d files in %s" % (backups, args.backup_dir))
    print("\nREMINDER: the mapping and the backups both contain every original name.")
    print("They are a deanonymization key - remove them at cleanup if the tree must be clean.")
    if args.report:
        print("report: %s" % args.report)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Inventory locale-bound references before any replacement.

Reports every inflected form with counts and sample contexts, plus filenames and
@handles carrying the term. Read this output before writing a mapping: the form list
is what tells you which declensions and wordplay you have to handle.

Usage:
  python scripts/scan.py <paths...> --terms "Employer,City" [--json inventory.json]
  python scripts/scan.py ./docs --terms-file terms.txt --ext .md,.txt --samples 5
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Inventory locale references in text files.")
    ap.add_argument("paths", nargs="+", help="files or directories to scan")
    ap.add_argument("--terms", help="comma-separated search terms")
    ap.add_argument("--terms-file", help="file with one term per line (# comments allowed)")
    ap.add_argument("--ext", help="comma-separated extensions to include (default: common text types)")
    ap.add_argument("--exclude", help="comma-separated directory names to skip")
    ap.add_argument("--samples", type=int, default=3, help="context samples per term per file")
    ap.add_argument("--width", type=int, default=70, help="context snippet width")
    ap.add_argument("--handles", action="store_true", help="also list @handles containing a term")
    ap.add_argument("--include-hidden", action="store_true", help="do not skip dotfiles/dotdirs")
    ap.add_argument("--json", help="write the inventory as JSON to this path")
    args = ap.parse_args()

    terms = common.load_terms(args.terms, args.terms_file)
    if not terms:
        ap.error("provide --terms or --terms-file")

    exts = [e.strip() for e in args.ext.split(",")] if args.ext else None
    exclude = [e.strip() for e in args.exclude.split(",")] if args.exclude else None

    files = list(common.iter_files(args.paths, exts, exclude, args.include_hidden))
    report = {"terms": terms, "files": [], "totals": {}, "filename_hits": [], "handle_hits": []}
    totals = Counter()
    unreadable = []

    for path in files:
        text, _enc = common.read_text(path)
        if text is None:
            unreadable.append(path)
            continue
        forms = common.find_forms(text, terms)
        if not forms:
            continue
        samples = common.find_contexts(text, terms, args.samples, args.width)
        entry = {
            "path": path,
            "forms": {t: dict(c) for t, c in forms.items()},
            "count": sum(sum(c.values()) for c in forms.values()),
            "samples": [{"line": ln, "form": f, "context": s} for ln, f, s in samples],
        }
        report["files"].append(entry)
        for term, counts in forms.items():
            totals[term] += sum(counts.values())

        base = os.path.basename(path).lower()
        if any(t.lower() in base for t in terms):
            report["filename_hits"].append(path)
        if args.handles:
            for handle in common.handle_tokens(text):
                if any(t.lower() in handle.lower() for t in terms):
                    report["handle_hits"].append({"path": path, "handle": handle})

    report["totals"] = dict(totals)
    report["scanned_files"] = len(files)
    report["unreadable"] = unreadable
    common.dump_json(args.json, report)

    print("scanned %d files, %d with matches" % (len(files), len(report["files"])))
    for term in terms:
        print("\n== %s : %d occurrences" % (term, totals.get(term, 0)))
        allforms = Counter()
        for entry in report["files"]:
            allforms.update(entry["forms"].get(term, {}))
        for form, n in allforms.most_common():
            print("   %-28s %d" % (form, n))
    print("\n-- per file --")
    for entry in sorted(report["files"], key=lambda e: -e["count"]):
        print("%5d  %s" % (entry["count"], entry["path"]))
        for s in entry["samples"][:args.samples]:
            print("        L%-5d %s" % (s["line"], s["context"][:120]))
    if report["filename_hits"]:
        print("\n-- filenames carrying a term (renaming breaks references; ask first) --")
        for p in report["filename_hits"]:
            print("   " + p)
    if report["handle_hits"]:
        print("\n-- handles carrying a term --")
        for h in report["handle_hits"]:
            print("   %s  %s" % (h["handle"], h["path"]))
    if unreadable:
        print("\n-- not decodable as text (skipped) --")
        for p in unreadable:
            print("   " + p)
    if args.json:
        print("\ninventory written to %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())

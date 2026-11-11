#!/usr/bin/env python3
"""Verify that no originals survive, and surface the carriers text replacement misses.

Exit code is non-zero while real problems remain, so this can drive a fix -> re-verify
loop. Benign homonyms are separated from genuine leaks via an allowlist of word
fragments, otherwise the signal drowns in ordinary words.

Usage:
  python scripts/verify.py <paths...> --terms "Employer,City" --targets "NewCo,NewCity"
  python scripts/verify.py . --terms-file terms.txt --allowlist allow.txt --json verify.json
"""
import argparse
import os
import re
import sys
import zlib
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

GIT_TEXT_FILES = ("config", "packed-refs", "COMMIT_EDITMSG", "HEAD", "description")


def scan_git_dir(gitdir, terms, max_objects):
    """Look for terms in reflog, config and loose commit objects (author name/email)."""
    hits = []
    patterns = [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in terms]

    def check(label, data):
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            return
        for term, pat in patterns:
            if pat.search(text):
                hits.append({"where": label, "term": term})
                break

    for name in GIT_TEXT_FILES:
        p = os.path.join(gitdir, name)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                check(os.path.relpath(p, gitdir), fh.read())
    logs = os.path.join(gitdir, "logs")
    for root, _dirs, files in os.walk(logs):
        for name in files:
            p = os.path.join(root, name)
            with open(p, "rb") as fh:
                check(os.path.relpath(p, gitdir), fh.read())
    objects = os.path.join(gitdir, "objects")
    seen = 0
    for root, _dirs, files in os.walk(objects):
        if os.path.basename(root) in ("pack", "info"):
            continue
        for name in files:
            if seen >= max_objects:
                hits.append({"where": "objects (truncated at %d)" % max_objects, "term": "-"})
                return hits
            p = os.path.join(root, name)
            try:
                with open(p, "rb") as fh:
                    raw = zlib.decompress(fh.read())
            except Exception:
                continue
            seen += 1
            check(os.path.relpath(p, gitdir), raw)
    return hits


def main():
    ap = argparse.ArgumentParser(description="Verify anonymization and find remaining leak vectors.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--terms", help="comma-separated original terms to look for")
    ap.add_argument("--terms-file", help="file with one original term per line")
    ap.add_argument("--targets", help="comma-separated replacements, for artifact detection")
    ap.add_argument("--allowlist", help="file of word fragments that make a match benign")
    ap.add_argument("--expected-forms", help="comma-separated legitimate inflections of the targets")
    ap.add_argument("--exclude", help="comma-separated directory names to skip")
    ap.add_argument("--ext", help="comma-separated text extensions to check")
    ap.add_argument("--max-objects", type=int, default=2000, help="cap on git loose objects inspected")
    ap.add_argument("--json", help="write the verification result here")
    args = ap.parse_args()

    terms = common.load_terms(args.terms, args.terms_file)
    if not terms:
        ap.error("provide --terms or --terms-file")
    targets = [t.strip() for t in (args.targets or "").split(",") if t.strip()]
    allowed = [f.strip() for f in (args.expected_forms or "").split(",") if f.strip()]
    allowed += targets
    allowlist = common.load_allowlist(args.allowlist)
    exts = {e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
            for e in args.ext.split(",")} if args.ext else common.DEFAULT_EXTS
    exclude = set(e.strip() for e in args.exclude.split(",")) if args.exclude else set(common.DEFAULT_EXCLUDE_DIRS)

    leftovers, benign, artifacts = [], [], []
    filename_hits, pyc_hits, git_hits, mapping_hits, backup_dirs = [], [], [], [], []
    images = Counter()
    text_files = 0

    for raw in args.paths:
        root_path = os.path.abspath(raw)
        if os.path.isfile(root_path):
            walk_root, single = os.path.dirname(root_path), [root_path]
        else:
            walk_root, single = root_path, None
        for dirpath, dirnames, filenames in os.walk(walk_root):
            if ".git" in dirnames:
                git_hits += [{"path": os.path.join(dirpath, ".git"), **h}
                             for h in scan_git_dir(os.path.join(dirpath, ".git"), terms, args.max_objects)]
            dirnames[:] = [d for d in dirnames if d not in exclude and d != ".git"]
            for d in list(dirnames):
                if "backup" in d.lower():
                    backup_dirs.append(os.path.join(dirpath, d))
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                if single and path not in single:
                    continue
                ext = os.path.splitext(name)[1].lower()
                low = name.lower()

                if any(t.lower() in low for t in terms):
                    filename_hits.append(path)
                if ext in common.IMAGE_EXTS:
                    images[ext] += 1
                    continue
                if ext in common.BINARY_TEXT_EXTS:
                    with open(path, "rb") as fh:
                        blob = fh.read()
                    for t in terms:
                        if t.encode("utf-8") in blob or t.lower().encode("utf-8") in blob:
                            pyc_hits.append({"path": path, "term": t})
                    continue
                if ext not in exts:
                    continue

                text, _enc = common.read_text(path)
                if text is None:
                    continue
                text_files += 1
                if ext == ".json" and '"pairs"' in text and '"from"' in text:
                    mapping_hits.append(path)
                spans = common.benign_spans(text, allowlist)
                leak_counts, benign_counts, leak_ctx = Counter(), Counter(), {}
                for term in terms:
                    for m in common.form_pattern(term).finditer(text):
                        form = m.group(0)
                        if common.is_benign(form, allowlist) or common.in_spans(m.start(), m.end(), spans):
                            benign_counts[form] += 1
                        else:
                            leak_counts[form] += 1
                            if form not in leak_ctx:
                                ln, snip = common.snippet_at(text, m.start(), m.end())
                                leak_ctx[form] = (term, ln, snip)
                for form, n in leak_counts.items():
                    term, ln, snip = leak_ctx[form]
                    leftovers.append({"path": path, "term": term, "form": form,
                                      "count": n, "line": ln, "context": snip})
                for form, n in benign_counts.items():
                    benign.append({"path": path, "form": form, "count": n})
                if targets:
                    found = common.find_artifacts(text, targets, allowed)
                    if found:
                        artifacts.append({"path": path, "items": found})

    problems = len(leftovers) + len(artifacts) + len(filename_hits) + len(pyc_hits) + len(git_hits)
    result = {
        "terms": terms, "targets": targets, "text_files_checked": text_files,
        "leftovers": leftovers, "benign": benign, "artifacts": artifacts,
        "filename_hits": filename_hits, "pyc_hits": pyc_hits, "git_hits": git_hits,
        "mapping_files": mapping_hits, "backup_dirs": backup_dirs,
        "images_in_scope": dict(images), "problems": problems, "clean": problems == 0,
    }
    common.dump_json(args.json, result)

    print("checked %d text files; %d problem(s)" % (text_files, problems))
    if leftovers:
        print("\n-- LEFTOVERS (original terms still present) --")
        for r in leftovers[:60]:
            print("   %s:%s  [%s x%d]  %s" % (r["path"], r.get("line", "?"), r["form"], r["count"], r.get("context", "")[:90]))
        if len(leftovers) > 60:
            print("   ... %d more" % (len(leftovers) - 60))
    if benign:
        agg = Counter(r["form"] for r in benign)
        print("\n-- benign homonyms (allowlisted, %d occurrences) --" % sum(agg.values()))
        for form, n in agg.most_common(20):
            print("   %-28s %d" % (form, n))
    if artifacts:
        print("\n-- ARTIFACTS (review grammar and sense) --")
        for a in artifacts:
            for item in a["items"]:
                print("   [%s] %s  (%s)" % (item["kind"], item["token"], a["path"]))
    if filename_hits:
        print("\n-- FILENAMES carrying a term --")
        for p in filename_hits:
            print("   " + p)
    if pyc_hits:
        print("\n-- BYTECODE caches embedding originals (delete them) --")
        for h in pyc_hits:
            print("   %s  [%s]" % (h["path"], h["term"]))
    if git_hits:
        print("\n-- GIT history/config (needs history rewriting, ask first) --")
        for h in git_hits:
            print("   %s :: %s [%s]" % (h["path"], h["where"], h["term"]))
    if mapping_hits or backup_dirs:
        print("\n-- deanonymization keys still in the tree --")
        for p in mapping_hits:
            print("   mapping: " + p)
        for p in backup_dirs:
            print("   backups: " + p)
    if images:
        print("\n-- images in scope: %d (text inside pixels is not fixable by replacement) --"
              % sum(images.values()))
    print("\nRESULT: %s" % ("CLEAN within the checked scope" if problems == 0 else "NOT CLEAN"))
    if args.json:
        print("report: %s" % args.json)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

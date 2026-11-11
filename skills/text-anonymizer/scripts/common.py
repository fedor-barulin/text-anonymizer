"""Shared helpers for the text-anonymizer scripts.

Standard library only, Python 3.8+. Imported by scan.py, apply.py and verify.py
from the same directory, so the scripts work when invoked by absolute path.
"""
import json
import os
import re
import sys
from collections import Counter

DEFAULT_EXTS = {
    ".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".jsonl",
    ".html", ".htm", ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".ps1",
    ".sh", ".bat", ".csv", ".xml", ".ipynb", ".sql", ".env", ".example",
}

DEFAULT_EXCLUDE_DIRS = {
    ".git", "node_modules", ".venv", "venv", ".idea", ".vscode", "dist", "build",
    ".next", ".cache", "target", "__MACOSX",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff"}
BINARY_TEXT_EXTS = {".pyc", ".pyo"}


def eprint(*args):
    print(*args, file=sys.stderr)


def iter_files(paths, exts=None, exclude_dirs=None, include_hidden=False):
    """Yield files under the given paths, filtered by extension and directory name."""
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in (exts or DEFAULT_EXTS)}
    exclude = set(exclude_dirs or DEFAULT_EXCLUDE_DIRS)
    for raw in paths:
        p = os.path.abspath(raw)
        if os.path.isfile(p):
            yield p
            continue
        if not os.path.isdir(p):
            eprint("skip (not found): %s" % raw)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [
                d for d in dirs
                if d not in exclude and (include_hidden or not d.startswith("."))
            ]
            for name in sorted(files):
                if not include_hidden and name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() in exts:
                    yield os.path.join(root, name)


def read_text(path):
    """Return (text, encoding) or (None, None) when the file is not decodable text.

    The encoding name must reflect what is actually on disk: reporting "utf-8-sig"
    for a plain UTF-8 file would make write_text add a BOM that was never there,
    which breaks strict JSON parsers and diffs.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16"
        except (UnicodeDecodeError, UnicodeError):
            pass
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None, None


def write_text(path, text, encoding="utf-8"):
    """Write text preserving the original encoding and line endings (no newline translation)."""
    with open(path, "wb") as fh:
        fh.write(text.encode(encoding))


def form_pattern(term):
    """Match a term together with any attached prefix/suffix, so inflections are captured."""
    return re.compile(r"[\w-]*" + re.escape(term) + r"[\w-]*", re.IGNORECASE | re.UNICODE)


def find_forms(text, terms):
    """Return {term: Counter(form -> count)} for every inflected form found."""
    out = {}
    for term in terms:
        counts = Counter(m.group(0) for m in form_pattern(term).finditer(text))
        if counts:
            out[term] = counts
    return out


def find_contexts(text, terms, limit=3, width=70):
    """Return [(line_no, form, snippet)] samples, at most `limit` per term."""
    samples = []
    seen = Counter()
    patterns = [(t, form_pattern(t)) for t in terms]
    for lineno, line in enumerate(text.splitlines(), 1):
        for term, pat in patterns:
            for m in pat.finditer(line):
                if seen[term] >= limit:
                    continue
                seen[term] += 1
                start = max(0, m.start() - width // 2)
                snippet = line[start:m.end() + width // 2].strip()
                samples.append((lineno, m.group(0), snippet))
    return samples


def handle_tokens(text):
    """Return @handles and URLs that may carry a locale identifier."""
    return sorted(set(re.findall(r"@[\w-]{3,}", text)))


def load_terms(args_terms, args_terms_file):
    terms = []
    if args_terms:
        terms += [t.strip() for t in args_terms.split(",") if t.strip()]
    if args_terms_file:
        with open(args_terms_file, "r", encoding="utf-8-sig") as fh:
            terms += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    seen, uniq = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            uniq.append(t)
    return uniq


def load_allowlist(path):
    if not path:
        return []
    with open(path, "r", encoding="utf-8-sig") as fh:
        return [ln.strip().lower() for ln in fh if ln.strip() and not ln.startswith("#")]


def is_benign(form, allowlist):
    """Single-word fragments: the matched form itself contains a benign fragment."""
    low = form.lower()
    return any(frag in low for frag in allowlist if " " not in frag)


def benign_spans(text, allowlist):
    """Spans covered by allowlisted phrases, so multi-word entries can be matched exactly.

    Checking the whole line would hide a real leak sitting next to a benign phrase;
    span containment keeps the classification tied to the actual occurrence.
    """
    spans = []
    low = text.lower()
    for frag in allowlist:
        if not frag or " " not in frag:
            continue
        start = 0
        while True:
            idx = low.find(frag, start)
            if idx < 0:
                break
            spans.append((idx, idx + len(frag)))
            start = idx + len(frag)
    return spans


def in_spans(begin, end, spans):
    return any(b <= begin and end <= e for b, e in spans)


def snippet_at(text, begin, end, width=70):
    """Return (line_number, trimmed snippet) for a match at the given offsets."""
    lineno = text.count("\n", 0, begin) + 1
    line_start = text.rfind("\n", 0, begin) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    offset = begin - line_start
    start = max(0, offset - width // 2)
    return lineno, line[start:offset + (end - begin) + width // 2].strip()


def load_mapping(path):
    with open(path, "r", encoding="utf-8") as fh:
        mapping = json.load(fh)
    pairs = mapping.get("pairs") or []
    if not pairs:
        raise ValueError("mapping has no pairs")
    problems = []
    seen = {}
    for i, pair in enumerate(pairs):
        src, dst = pair.get("from"), pair.get("to")
        if not src or dst is None:
            problems.append("pair %d: 'from' and 'to' are required" % i)
            continue
        if src == dst:
            problems.append("pair %d: 'from' equals 'to' (%r)" % (i, src))
        if src in seen:
            problems.append("pair %d: duplicate 'from' %r (also pair %d)" % (i, src, seen[src]))
        seen[src] = i
    if problems:
        raise ValueError("invalid mapping:\n  " + "\n  ".join(problems))
    return mapping


def sorted_pairs(mapping):
    """Longest source first: a short pair applied early eats the context a longer pair needs."""
    pairs = list(mapping.get("pairs") or [])
    return sorted(pairs, key=lambda p: (-len(p["from"]), p["from"]))


def expected_forms(mapping):
    forms = {p["to"] for p in mapping.get("pairs") or []}
    forms.update(mapping.get("expected_forms") or [])
    return forms


def find_artifacts(text, targets, allowed_forms=()):
    """Flag doubled tokens and replacements glued to an unexpected suffix.

    Correct inflections of a target look like glued suffixes, so `allowed_forms`
    (the mapping's `expected_forms`) suppresses the legitimate ones.
    """
    hits = []
    allowed = {f.lower() for f in allowed_forms}
    for target in sorted(set(targets), key=len, reverse=True):
        if not target or " " in target.strip():
            continue
        esc = re.escape(target)
        for m in re.finditer(r"[\w-]*" + esc + r"[\w-]*", text, re.IGNORECASE | re.UNICODE):
            token = m.group(0)
            if token.lower() in allowed or token.lower() == target.lower():
                continue
            hits.append(("glued-suffix", token))
        doubled = re.compile(r"(?<![\w])" + esc + r"[ \t]+" + esc + r"(?![\w])", re.IGNORECASE)
        for m in doubled.finditer(text):
            hits.append(("doubled-token", m.group(0)))
    uniq = []
    seen = set()
    for kind, token in hits:
        key = (kind, token.lower())
        if key not in seen:
            seen.add(key)
            uniq.append({"kind": kind, "token": token})
    return uniq


def validate_structured(path, text):
    """Return an error string when a structured file no longer parses, else None."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".json":
            json.loads(text)
        elif ext == ".jsonl":
            for i, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    json.loads(line)
    except (ValueError, TypeError) as exc:
        return "%s no longer parses: %s" % (ext, exc)
    return None


def dump_json(path, obj):
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)

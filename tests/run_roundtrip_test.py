#!/usr/bin/env python3
"""Round-trip self-test: anonymize -> model edits -> restore.

Covers the three ways a naive reverse fails: many-to-one ambiguity, target forms the
forward pass never created, and legitimate mentions of the target locale.

Usage:
    python tests/run_roundtrip_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "skills" / "text-anonymizer" / "scripts"
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
RESULTS = []

ORIGINAL = """Работаю в ООО «Ромашка», город Зареченск.
Выручка девелоперов Зареченска растёт.
Живу в Зареченске.
Ромашка открыла салон.
"""

# Two different originals collapse into one target: reversing needs a decision.
MAPPING = {
    "target_locale": "Singapore",
    "mode": "substitute",
    "protect": [],
    "pairs": [
        {"from": "ООО «Ромашка»", "to": "Globex"},
        {"from": "Зареченска", "to": "Сингапура"},
        {"from": "Зареченске", "to": "Сингапуре"},
        {"from": "Зареченск", "to": "Сингапур"},
        {"from": "Ромашка", "to": "Globex"},
    ],
}

# What the model might add: a new plural form and a genuine mention of the locale.
MODEL_ADDITION = """Сингапуры растут в оранжереях.
Сингапурские авиалинии летают ежедневно.
"""


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  -- " + detail) if detail and not ok else ""))


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          env=ENV, cwd=str(REPO))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="text-anonymizer-roundtrip-"))
    try:
        src = tmp / "src"
        src.mkdir()
        (src / "doc.md").write_text(ORIGINAL, encoding="utf-8")
        (src / "untouched.md").write_text(ORIGINAL, encoding="utf-8")
        mapping = tmp / "mapping.json"
        mapping.write_text(json.dumps(MAPPING, ensure_ascii=False), encoding="utf-8")
        key = tmp / "key.json"
        backup = tmp / "backup-anon"

        # 1. forward pass emits a key
        p = run("apply.py", str(src), "--mapping", str(mapping),
                "--backup-dir", str(backup), "--emit-key", str(key))
        check("forward pass succeeds", p.returncode == 0, p.stderr[-300:])
        check("key emitted", key.exists())
        k = json.loads(key.read_text(encoding="utf-8"))
        check("key marks the ambiguous target", "Globex" in k["ambiguous"],
              str(k.get("ambiguous")))
        check("key records document hashes",
              all(d.get("sha256_before") and d.get("sha256_after") for d in k["documents"]))
        anon = (src / "doc.md").read_text(encoding="utf-8")
        check("forward replaced the city", "город Сингапур" in anon)
        check("forward collapsed both originals", anon.count("Globex") == 2)

        # 2. simulate the model's answer: edited doc + verbatim doc
        (src / "doc.md").write_text(anon + MODEL_ADDITION, encoding="utf-8")

        # 3. dry run must not guess
        p = run("restore.py", str(src), "--key", str(key), "--dry-run", "--report", str(tmp / "r1.json"))
        r1 = json.loads((tmp / "r1.json").read_text(encoding="utf-8"))
        check("dry run writes nothing", (src / "doc.md").read_text(encoding="utf-8") == anon + MODEL_ADDITION)
        check("ambiguous occurrences left pending", len(r1["pending_ambiguities"]) >= 1)
        check("unknown plural form reported",
              any(f["form"] == "Сингапуры" for e in r1["unknown_target_forms"] for f in e["forms"]))
        check("restore exits non-zero while unresolved", p.returncode == 1)

        # 4. decisions template is offered
        tpl = tmp / "decisions-template.json"
        p = run("restore.py", str(src), "--key", str(key), "--decisions-template", str(tpl))
        check("decisions template written", tpl.exists() and "Globex" in json.loads(tpl.read_text(encoding="utf-8")))

        # 5. supply decisions, extra forms and protection, then restore
        decisions = tmp / "decisions.json"
        decisions.write_text(json.dumps({
            "Globex": [{"contains": "Работаю в", "choose": "ООО «Ромашка»"},
                       {"default": "Ромашка"}]
        }, ensure_ascii=False), encoding="utf-8")
        k["reverse_extra"] = [{"from": "Сингапуры", "to": "Зареченски"}]
        k["protect_reverse"] = ["Сингапурские авиалинии"]
        key.write_text(json.dumps(k, ensure_ascii=False), encoding="utf-8")

        p = run("restore.py", str(src), "--key", str(key), "--decisions", str(decisions),
                "--backup-dir", str(tmp / "backup-restore"),
                "--verify-against", str(backup), "--report", str(tmp / "r2.json"))
        r2 = json.loads((tmp / "r2.json").read_text(encoding="utf-8"))
        restored = (src / "doc.md").read_text(encoding="utf-8")
        check("restore succeeds once resolved", p.returncode == 0, p.stdout[-400:])
        check("context rule picked the legal entity", "Работаю в ООО «Ромашка»" in restored)
        check("default rule picked the brand", "Ромашка открыла салон" in restored)
        check("city restored in all cases",
              "город Зареченск" in restored and "девелоперов Зареченска" in restored
              and "Живу в Зареченске" in restored)
        check("extra plural form restored", "Зареченски растут в оранжереях" in restored)
        check("legitimate locale mention protected", "Сингапурские авиалинии летают ежедневно" in restored)
        check("no pending ambiguities remain", not r2["pending_ambiguities"])
        check("no unknown forms remain", not r2["unknown_target_forms"])

        # 6. round-trip integrity
        statuses = {v["path"].split(os.sep)[-1]: v["status"] for v in r2["roundtrip"]}
        check("verbatim file round-trips identically", statuses.get("untouched.md") == "identical",
              str(statuses))
        check("edited file reported as differing", statuses.get("doc.md") == "differs", str(statuses))
        check("untouched file equals the original byte-for-byte",
              (src / "untouched.md").read_text(encoding="utf-8") == ORIGINAL)

        # 7. a wrong key is rejected
        bad = tmp / "bad-key.json"
        bad.write_text(json.dumps({"kind": "something-else"}), encoding="utf-8")
        p = run("restore.py", str(src), "--key", str(bad), "--dry-run")
        check("invalid key rejected", p.returncode == 2)

        # 8. no bytecode left behind
        check("no __pycache__ in the skill", not list(SCRIPTS.rglob("__pycache__")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok in RESULTS if not ok]
    print("\n%d checks, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    print("ALL ROUND-TRIP CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

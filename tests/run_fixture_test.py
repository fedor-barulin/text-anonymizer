#!/usr/bin/env python3
"""Self-test for the text-anonymizer skill on a fictional fixture.

Builds a temp corpus that reproduces the real failure modes (inflection, homonyms,
planted artifacts, structured data), runs the three scripts against it and asserts
the expected behaviour. Exits non-zero on any failure.

Usage:
    python tests/run_fixture_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "text-anonymizer"
SCRIPTS = SKILL / "scripts"

PROFILE = """Работаю в ООО «Ромашка» (Romashka Telecom), город Зареченск.
Почта: ivan@romashka-telecom.example
Продукты: Ромашка.Pay, партнёр - банк «Заречье».
Выручка девелоперов Зареченска растёт, а прибыль хуже.
Живу в Зареченске, езжу по Зареченску, горжусь Зареченском.
Коренной зареченчанин, зареченский акцент.
Каналы: @zarechensk_news | Новости Зареченска
Мотивация команды и лейтмотив поста, рисунок по мотивам игры, мотиватор на стене.
Заварил ромашковый чай, ромашка аптечная в аптеке.
Ромашка Ромашка - двойной бренд.
Ромашкаград - такой район.
Зареченская область, Зареченск.
"""

DATA_JSON = """{
  "source": "@zarechensk_news",
  "messages": [
    {"id": 1, "text": "Новости Зареченска: Ромашка открыла салон"},
    {"id": 2, "text": "Мотивация и лейтмотив - обычные слова"},
    {"id": 3, "text": "Живу в Зареченске"}
  ]
}
"""

MAPPING = {
    "target_locale": "Singapore",
    "mode": "substitute",
    "protect": ["мотиваци", "лейтмотив", "по мотивам", "мотиватор", "motive",
                "ромашковый чай", "ромашка аптечная"],
    "expected_forms": ["Сингапур", "Сингапура", "Сингапуре", "Сингапуром", "Сингапуру",
                       "сингапурец", "сингапурский", "Globex", "Globex Telecom",
                       "Globex Pay", "Merlion Bank"],
    "pairs": [
        {"from": "ООО «Ромашка» (Romashka Telecom)", "to": "Globex Telecom"},
        {"from": "Ромашка.Pay", "to": "Globex Pay"},
        {"from": "romashka-telecom.example", "to": "globex.example"},
        {"from": "банк «Заречье»", "to": "Merlion Bank"},
        {"from": "Зареченская область", "to": "Сингапур"},
        {"from": "Зареченском", "to": "Сингапуром"},
        {"from": "Зареченска", "to": "Сингапура"},
        {"from": "Зареченску", "to": "Сингапуру"},
        {"from": "Зареченске", "to": "Сингапуре"},
        {"from": "Зареченск", "to": "Сингапур"},
        {"from": "зареченчанин", "to": "сингапурец"},
        {"from": "зареченский", "to": "сингапурский"},
        {"from": "@zarechensk_news", "to": "@sg_news"},
        {"from": "Ромашка", "to": "Globex"},
    ],
}

ALLOWLIST = "мотиваци\nлейтмотив\nмотивам\nмотиватор\nромашков\nромашка аптечная\n"
TERMS = "Ромашка,Зареченск,мотив,romashka,zarechensk"
TARGETS = "Globex,Сингапур"

# Never write bytecode into the skill directory: a public repo must not ship caches.
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  -- " + detail) if detail and not ok else ""))


def run(script, *args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True, encoding="utf-8", env=ENV, cwd=str(REPO),
    )
    return proc


def main():
    tmp = Path(tempfile.mkdtemp(prefix="text-anonymizer-test-"))
    try:
        fixture = tmp / "fixture"
        fixture.mkdir()
        (fixture / "profile.md").write_text(PROFILE, encoding="utf-8")
        (fixture / "data.json").write_text(DATA_JSON, encoding="utf-8")
        mapping_path = tmp / "mapping.json"
        mapping_path.write_text(json.dumps(MAPPING, ensure_ascii=False, indent=2), encoding="utf-8")
        allow_path = tmp / "allow.txt"
        allow_path.write_text(ALLOWLIST, encoding="utf-8")

        # 1. scan finds every inflected form
        inv = tmp / "inventory.json"
        p = run("scan.py", str(fixture), "--terms", TERMS, "--handles", "--json", str(inv))
        check("scan exits 0", p.returncode == 0, p.stderr[-300:])
        data = json.loads(inv.read_text(encoding="utf-8")) if inv.exists() else {}
        forms = set()
        for entry in data.get("files", []):
            for counts in entry.get("forms", {}).values():
                forms.update(counts)
        check("scan reports oblique cases", {"Зареченска", "Зареченске", "Зареченском"} <= forms,
              "got: %s" % sorted(forms))
        check("scan reports homonym forms", "Мотивация" in forms and "лейтмотив" in forms)

        # 2. dry run writes nothing
        before = {f.name: f.read_bytes() for f in fixture.iterdir()}
        p = run("apply.py", str(fixture), "--mapping", str(mapping_path), "--dry-run")
        after = {f.name: f.read_bytes() for f in fixture.iterdir()}
        check("dry run exits 0", p.returncode == 0, p.stderr[-300:])
        check("dry run changes nothing", before == after)

        # 3. apply with backup
        backup = tmp / "backup-anon"
        report = tmp / "apply-report.json"
        p = run("apply.py", str(fixture), "--mapping", str(mapping_path),
                "--backup-dir", str(backup), "--report", str(report))
        check("apply exits 0", p.returncode == 0, p.stderr[-300:])
        check("backups written", backup.exists() and len(list(backup.rglob("*.*"))) == 2)

        text = (fixture / "profile.md").read_text(encoding="utf-8")
        check("genitive agrees", "девелоперов Сингапура растёт" in text)
        check("prepositional agrees", "Живу в Сингапуре" in text)
        check("instrumental agrees", "горжусь Сингапуром" in text)
        check("demonym replaced", "Коренной сингапурец" in text)
        check("legal entity replaced", "Работаю в Globex Telecom" in text)
        check("domain replaced", "ivan@globex.example" in text)
        check("handle replaced", "@sg_news" in text and "@zarechensk_news" not in text)
        for word in ("Мотивация", "лейтмотив", "по мотивам", "мотиватор",
                     "ромашковый чай", "ромашка аптечная"):
            check("homonym survives: %s" % word, word in text)

        json_ok = True
        try:
            json.loads((fixture / "data.json").read_text(encoding="utf-8"))
        except ValueError:
            json_ok = False
        check("JSON still parses after replacement", json_ok)

        rep = json.loads(report.read_text(encoding="utf-8"))
        kinds = {item["kind"] for a in rep.get("artifacts", []) for item in a["items"]}
        check("doubled token detected", "doubled-token" in kinds)
        check("glued suffix detected", "glued-suffix" in kinds)

        # 4. verify on the edited scope: no leftovers, benign homonyms separated
        vjson = tmp / "verify.json"
        p = run("verify.py", str(fixture), "--terms", TERMS, "--targets", TARGETS,
                "--allowlist", str(allow_path),
                "--expected-forms", ",".join(MAPPING["expected_forms"]),
                "--json", str(vjson))
        v = json.loads(vjson.read_text(encoding="utf-8"))
        check("verify finds no leftovers", not v["leftovers"],
              "%d leftovers" % len(v["leftovers"]))
        check("verify classifies homonyms as benign", sum(b["count"] for b in v["benign"]) >= 5)
        check("verify reports planted artifacts", len(v["artifacts"]) >= 1)
        check("verify exits non-zero while artifacts remain", p.returncode == 1)

        # 5. verify on the whole tree flags the deanonymization keys
        p = run("verify.py", str(tmp), "--terms", "Ромашка,Зареченск",
                "--allowlist", str(allow_path), "--json", str(tmp / "verify-all.json"))
        va = json.loads((tmp / "verify-all.json").read_text(encoding="utf-8"))
        check("mapping flagged as a key", any("mapping.json" in m for m in va["mapping_files"]))
        check("backup dir flagged as a key", bool(va["backup_dirs"]))

        # 6. a mapping that breaks JSON is rolled back
        fixture2 = tmp / "fixture2"
        fixture2.mkdir()
        shutil.copy2(backup / "data.json", fixture2 / "data.json")
        shutil.copy2(backup / "profile.md", fixture2 / "profile.md")
        bad = tmp / "bad-mapping.json"
        bad.write_text(json.dumps({"pairs": [{"from": "Ромашка", "to": 'Globex"'}]},
                                  ensure_ascii=False), encoding="utf-8")
        original = (fixture2 / "data.json").read_bytes()
        p = run("apply.py", str(fixture2), "--mapping", str(bad), "--no-backup")
        check("broken JSON rolls back", (fixture2 / "data.json").read_bytes() == original)
        check("broken JSON exits non-zero", p.returncode == 1)
        check("rollback is reported", "no longer parses" in p.stdout)

        # 7. encoding, BOM and line endings are preserved exactly
        enc_dir = tmp / "encoding"
        enc_dir.mkdir()
        (enc_dir / "plain.md").write_bytes("Город Зареченск.".encode("utf-8"))
        (enc_dir / "bom.md").write_bytes(b"\xef\xbb\xbf" + "Город Зареченск.".encode("utf-8"))
        (enc_dir / "crlf.md").write_bytes("Город Зареченск.\r\n".encode("utf-8"))
        run("apply.py", str(enc_dir), "--mapping", str(mapping_path), "--no-backup")
        check("no BOM added to plain UTF-8",
              not (enc_dir / "plain.md").read_bytes().startswith(b"\xef\xbb\xbf"))
        check("existing BOM preserved",
              (enc_dir / "bom.md").read_bytes().startswith(b"\xef\xbb\xbf"))
        check("CRLF preserved", b"\r\n" in (enc_dir / "crlf.md").read_bytes())
        check("replacement happened in encoding fixture",
              "Сингапур" in (enc_dir / "plain.md").read_text(encoding="utf-8"))

        # 8. no bytecode caches were created inside the skill
        caches = list(SKILL.rglob("__pycache__"))
        check("no __pycache__ left in the skill", not caches, str(caches))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n%d checks, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    if failed:
        print("FAILED: " + "; ".join(failed))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

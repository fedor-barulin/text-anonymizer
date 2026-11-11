# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-11

Initial public release.

### Added

- `text-anonymizer` skill: intake → inventory → mapping → approval → apply →
  language pass → verify → cleanup pipeline for depersonalizing text.
- Two modes: `substitute` (move references to a target country) and `neutralize`
  (replace with generic wording). The target locale is always asked, never assumed.
- `scripts/scan.py` - inventory of inflected forms, counts, contexts, filenames, handles.
- `scripts/apply.py` - longest-first replacement with homonym protection, backups,
  structured-file validation and rollback, artifact detection. Original encoding,
  BOM presence and line endings are preserved byte-for-byte.
- `scripts/verify.py` - leftovers vs benign homonyms, artifacts, leak vectors
  (filenames, bytecode caches, git history, mapping and backup files), exit code
  suitable for a fix → re-verify loop.
- `references/ru-inflection.md` - Russian declension, demonyms, homonym protection,
  invisible local ties, handles and puns.
- `references/leak-checklist.md` - scope tiers, carriers text replacement cannot fix,
  cleanup of deanonymization keys, report template.
- `assets/mapping.example.json` - mapping template with fictional example data.
- Fixture self-test (`tests/run_fixture_test.py`, 37 checks) covering declension,
  homonym protection, artifact detection, JSON rollback, encoding/BOM/CRLF
  preservation and key detection.
- GitHub Actions workflow running the self-test on Linux and Windows, plus a guard
  against committed bytecode caches.
- Qoder plugin manifest (`.qoder-plugin/plugin.json`); the same `skills/` directory
  installs directly into Claude Code.

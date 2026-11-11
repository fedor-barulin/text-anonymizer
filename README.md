# Text Anonymizer

Depersonalize text by moving its locale: replace employer, legal entity, city, region,
districts, domains, email, partner banks, local brands, channel names and handles with
equivalents from another country — or neutralize them into generic wording.

A skill for AI coding agents (Qoder, Claude Code) with three Python utilities that do
the deterministic part.

**The target country is always your choice.** The skill asks what you are anonymizing
and where to move it before touching a file. There is no default destination.

```
intake → inventory → mapping → approval → apply → language pass → verify → cleanup
```

## Why this exists

Find-and-replace on a city name looks like it works and fails in four predictable ways:

1. **Grammar breaks.** Russian (and any inflected language) needs the right case:
   «выручка девелоперов *Зареченска*» → «…Сингапур**а**», not «…Сингапур».
2. **Unrelated words get mangled.** A brand root lives inside ordinary words —
   `мотивация`, `лейтмотив`, `по мотивам`, English `motive`, surnames, other companies.
   Replacing by root turns prose into nonsense.
3. **The strongest identifiers survive.** District names, regional banks and railways,
   local bloggers, `@city_handles`, phone area codes, filenames, git author emails,
   `.pyc` caches. None of them contain the city name you searched for.
4. **The cleanup leaks.** The mapping file and the backups list every original name in
   one place. They are a deanonymization key, and they are usually left in the tree.

This skill encodes the pipeline that avoids all four, and reports honestly what it
could not fix.

## Install

### Qoder (plugin)

Copy or clone this repository into your Qoder plugins directory, or install it from
your local path:

```
<plugins-dir>/text-anonymizer/
  .qoder-plugin/plugin.json
  skills/text-anonymizer/SKILL.md
```

For project-local use, put the skill where Qoder discovers project skills:

```
<your-project>/.qoder/skills/text-anonymizer/
```

A junction or symlink to `skills/text-anonymizer` works and avoids a second copy.

### Claude Code (skill)

The `SKILL.md` format is the same, so no conversion is needed. Copy the skill directory:

```bash
# personal, available in all projects
cp -r skills/text-anonymizer ~/.claude/skills/

# or project-local
cp -r skills/text-anonymizer <your-project>/.claude/skills/
```

### Manual / any agent

The scripts are standalone and need only Python 3.8+:

```bash
python skills/text-anonymizer/scripts/scan.py --help
```

Point any agent at `skills/text-anonymizer/SKILL.md` and it can follow the workflow.

## Usage

Ask in natural language:

- «Обезличь мои посты: убери работодателя и город»
- "Depersonalize this resume and move the locale to Singapore"
- «Отсингапурь черновик, но работодателя просто обезличь, без замены»
- "Find every mention of my employer and city in this project"

The agent will ask for:

| Question | Why it matters |
|---|---|
| What are we anonymizing? | Authored text, working data and raw dumps differ by orders of magnitude |
| Which target country? | Never assumed; you pick |
| `substitute` or `neutralize`? | Substitution creates new factual claims; neutralization does not |
| Entity counterparts | Legal entity, brand, domains, email, partner bank need real decisions |
| Raw data and non-text carriers | Chat exports, images, git history — include or leave alone |

Then it shows the mapping for approval before applying anything.

### Two modes

| Mode | Result | Fits |
|---|---|---|
| `substitute` | «Ромашка» → «Globex», «Зареченск» → «Сингапур» | Text should read as if the author lives there |
| `neutralize` | «Ромашка» → «приложение оператора связи» | Remove the old identity without claiming a new one |

Mixing is normal: substitute the geography, neutralize the employer.

## CLI reference

```bash
# 1. Inventory: every inflected form, counts, contexts, filenames, handles
python skills/text-anonymizer/scripts/scan.py ./docs \
  --terms "Employer,City" --handles --json inventory.json

# 2. Dry run: what would change, nothing written
python skills/text-anonymizer/scripts/apply.py ./docs \
  --mapping mapping.json --dry-run

# 3. Apply: backup required unless you explicitly opt out
python skills/text-anonymizer/scripts/apply.py ./docs \
  --mapping mapping.json --backup-dir ./backup-anon --report apply-report.json

# 4. Verify: non-zero exit while real problems remain
python skills/text-anonymizer/scripts/verify.py ./docs \
  --terms "Employer,City" --targets "NewCo,NewCity" \
  --allowlist allow.txt --expected-forms "NewCities,NewCity's"
```

`verify.py` separates genuine leftovers from benign homonyms, flags artifacts
(doubled tokens, glued suffixes), and reports the carriers text replacement cannot
fix: filenames, `.pyc` caches, git history, mapping and backup files, images.

### Mapping format

See [`skills/text-anonymizer/assets/mapping.example.json`](skills/text-anonymizer/assets/mapping.example.json).

```json
{
  "target_locale": "Singapore",
  "mode": "substitute",
  "protect": ["мотиваци", "лейтмотив", "по мотивам", "motive"],
  "expected_forms": ["Сингапур", "Сингапура", "Сингапуре"],
  "pairs": [
    {"from": "ООО «Ромашка» (Romashka Telecom)", "to": "Globex Telecom", "note": "legal entity"},
    {"from": "Зареченска", "to": "Сингапура", "note": "genitive"},
    {"from": "Зареченск", "to": "Сингапур", "note": "nominative"}
  ]
}
```

- `pairs` are applied **longest-first** automatically, so a short pair cannot eat the
  context a longer one needed.
- `protect` fragments are masked before replacement and restored afterwards — this is
  what keeps ordinary words intact.
- `expected_forms` lists legitimate inflections of the targets so the artifact checker
  does not flag correct grammar.

## What it will not do

- Invent biographical details. If a counterpart is unknown, it asks or neutralizes.
- Silently ignore images, filenames, git history or document metadata — they are
  reported as remaining vectors.
- Rewrite git history without explicit approval (irreversible, affects pushed commits).
- Help fabricate credentials, alter identity or financial documents, or impersonate a
  real person or company. This is privacy and publication hygiene for text you own.

## Repository layout

```
.github/workflows/test.yml       CI: self-test on Linux + Windows
.qoder-plugin/plugin.json        Qoder plugin manifest
assets/avatar.svg                plugin icon
skills/text-anonymizer/
  SKILL.md                       workflow, intake questions, boundaries
  references/ru-inflection.md    Russian declension, homonyms, invisible ties, puns
  references/leak-checklist.md   scope tiers, leak carriers, cleanup, report template
  scripts/common.py              shared helpers
  scripts/scan.py                inventory
  scripts/apply.py               protected replacement with backup and rollback
  scripts/verify.py              leftovers, artifacts, leak vectors
  assets/mapping.example.json    mapping template (fictional data)
tests/run_fixture_test.py        self-test on a fictional fixture
LICENSE                          MIT
CHANGELOG.md                     release notes
```

One skill directory serves both Qoder and Claude Code — there is no second copy to
keep in sync.

## Development

Requirements: Python 3.8+, no third-party packages.

```bash
python tests/run_fixture_test.py
```

The self-test builds a fictional fixture in a temp directory and runs 37 checks:
declension correctness, homonym protection, artifact detection, JSON rollback,
encoding/BOM/CRLF preservation, and detection of mapping/backup files as
deanonymization keys. It exits non-zero on any failure and leaves no bytecode behind.

CI runs the same test on Linux and Windows (Python 3.11 and 3.12) and fails if any
`__pycache__` or `.pyc` appears in the working tree.

Validate the plugin manifest with the validator bundled in Qoder's `create-plugin`
skill:

```bash
python <create-plugin>/scripts/validate_qoder_plugin.py .
```

After creating the GitHub repository, add `repository` and `homepage` to
`.qoder-plugin/plugin.json`.

## Language support

The workflow is language-agnostic. Inflection handling is documented for Russian in
`references/ru-inflection.md`; the same approach (inventory forms → map each form →
grammar pass) applies to any inflected language. Contributions adding reference files
for other languages are welcome.

## License

[MIT](LICENSE) © Fedor Barulin

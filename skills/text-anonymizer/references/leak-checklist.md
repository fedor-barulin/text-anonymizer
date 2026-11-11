# Leak checklist and cleanup

A text replacement job is only as good as its coverage. This file lists where
identifiers survive a "successful" find-and-replace, and how to close the job without
leaving a deanonymization key behind.

## Contents

- [Scope negotiation](#scope)
- [Carriers text replacement cannot fix](#carriers)
- [The mapping and backups are themselves a leak](#key)
- [Verification that actually verifies](#verification)
- [Report template](#report)

<a id="scope"></a>
## Scope negotiation

Separate the corpus into three tiers before starting, and get the user's decision on
each. Effort and risk differ by orders of magnitude.

| Tier | Examples | Typical volume | Note |
|---|---|---|---|
| Authored text | posts, articles, resumes, profiles, notes, scripts | tens of occurrences | Hand-editable, needs judgement |
| Working data | digests, source lists, channel logs, inventories | hundreds | Mixed: some identifiers are external references |
| Raw dumps | chat exports, crawled feeds, logs, memory dumps | thousands | Strongest deanonymization source; needs scripted replacement + JSON validation |

Users often mean only the first tier and are surprised the third exists. Say the
numbers out loud: "the authored files have ~20 occurrences, the chat exports have
~5000". Let them choose, and record the choice - "clean" later means clean within it.

<a id="carriers"></a>
## Carriers text replacement cannot fix

Report these explicitly; do not let the user assume they were handled.

- **Images and screenshots**: memes, photos, UI captures, covers. Text inside pixels
  is untouched. Recognizable visuals (local brands, landmarks, storefronts) identify
  the location even without words.
- **Filenames and directory names**: `city-event-2026.jpg`, `employer-case.md`.
  Renaming breaks references, so list them and ask.
- **Git history**: author name and email in commits, reflog (`logs/HEAD`,
  `logs/refs/**`), remote URLs, commit messages, tags. A corporate email in the
  author field survives every working-tree edit. Scrubbing requires history rewriting
  (`git filter-repo`) and affects pushed commits - irreversible, needs explicit approval.
- **Bytecode and caches**: `__pycache__/*.pyc` embed string literals from the source.
  A sanitized `.py` next to a stale `.pyc` still leaks. Delete the generated caches.
- **Binary documents**: `.docx`, `.pdf`, `.xlsx` hold text in containers; plain
  replacement on the raw bytes corrupts them. Use a format-aware tool or export,
  edit, re-import.
- **Metadata**: EXIF GPS in photos, document properties (author, company), PDF
  metadata, IDE workspace files.
- **External identifiers**: `@handles`, URLs, phone numbers, email addresses,
  account IDs. Changing them breaks links; leaving them leaks. Decide per item.
- **Structured data**: JSON keys, database identifiers, API field names. Replacing
  values is safe; replacing keys can break consumers. Validate after editing.

<a id="key"></a>
## The mapping and backups are themselves a leak

The mapping file lists every original name next to its replacement. Backups contain
the untouched originals. Both are more identifying than any single edited file.

If the user wants a tree with no trace of the originals:

1. Delete the backup directory, including the empty folder left behind.
2. Delete the mapping file and any inventory/report JSON that quotes originals.
3. Delete generated `.pyc` files for the scripts that contained the mapping.
4. Re-run verification over the **whole tree**, not just the edited scope.

If there is no version control, make backups before bulk edits anyway - then remove
them at the end. An unrecoverable bulk edit is a worse outcome than a temporary file.

Warn the user before deleting: once backups and mapping are gone, the substitution
cannot be reversed or audited.

<a id="verification"></a>
## Verification that actually verifies

- Re-scan with the **original terms**, including lowercase and transliterated forms.
- Classify leftovers: genuine leak vs benign homonym. An allowlist of word fragments
  (`мотиваци`, `лейтмотив`, `по мотивам`) keeps the signal clean.
- Check **artifacts**: doubled tokens, glued suffixes, replacements inside URLs,
  hex colors, or code identifiers that were never meant to change.
- Check **consistency**: domain, email, product names and brand should agree with
  each other across files.
- Validate **structured files** parse after editing (JSON, YAML, XML).
- Scan **filenames**, not just contents.
- Report **out-of-scope carriers** from the list above.

A verification that only greps the edited files will report success while the raw
exports, images and git history still identify the author. Say what was checked.

<a id="report"></a>
## Report template

```markdown
## Anonymization report

**Scope**: <files/dirs included> · **Mode**: substitute | neutralize | mixed
**Target locale**: <country> · **Source locale**: <country/region>

### Changed
| File | Replacements | Notes |
|---|---|---|
| <path> | <n> | <grammar fixes, handles, puns> |

### Mapping used
<original → replacement, grouped by entity type>

### Deliberately untouched
- <homonyms protected, with reason>
- <external identifiers left intact, with reason>

### Still identifying (needs a decision)
- <raw dumps: counts>
- <images / filenames / git history / metadata>

### Cleanup
- backups: removed | kept at <path>
- mapping: removed | kept at <path>
- caches: removed | n/a

**Verification**: <command run> → <result>, <n> benign leftovers explained
```

Keep the report honest about what remains. A partial job described as complete is
the worst outcome of this workflow.

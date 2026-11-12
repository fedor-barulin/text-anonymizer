# Round trip: restoring the originals

Read this before running `restore.py`. Reversing an anonymization is not the forward
pass with the pairs swapped, and treating it that way silently corrupts text.

## Contents

- [Why reverse is not symmetric](#why)
- [The key: format and lifecycle](#key)
- [Ambiguity: many-to-one targets](#ambiguity)
- [Target-language inflection](#inflection)
- [Protecting legitimate mentions](#protect)
- [Verifying the round trip](#verify)
- [What cannot be restored](#limits)
- [Key hygiene](#hygiene)

<a id="why"></a>
## Why reverse is not symmetric

The forward pass is a function from many possible originals to one replacement. It
loses information in three ways:

1. **Collapse.** Several originals can map to the same replacement. The replacement
   alone cannot tell you which one was there.
2. **New forms.** The model writes the replacement in cases, numbers and derivations
   the forward pass never produced. There is no pair for them.
3. **Coincidence.** The replacement may be a real word in the target locale. The model
   can mention the target country genuinely, and reversing that is wrong.

A fourth problem is not linguistic: the model may paraphrase, reorder, translate or
drop the sentence entirely. No key can recover what is no longer in the text.

`restore.py` therefore reports rather than guesses. Anything unresolved is left
verbatim and surfaced for a decision.

<a id="key"></a>
## The key: format and lifecycle

Emitted by `apply.py --emit-key`, consumed by `restore.py --key`:

```json
{
  "kind": "text-anonymizer.roundtrip-key",
  "version": 1,
  "target_locale": "Singapore",
  "mode": "substitute",
  "forward": [{"from": "Зареченск", "to": "Сингапур"}],
  "reverse": [{"from": "Сингапур", "to": "Зареченск"}],
  "reverse_extra": [{"from": "Сингапуры", "to": "Зареченски"}],
  "protect_reverse": ["Сингапурские авиалинии"],
  "ambiguous": {"Globex": ["ООО «Ромашка»", "Ромашка"]},
  "documents": [{"path": "...", "sha256_before": "...", "sha256_after": "..."}]
}
```

| Field | Purpose |
|---|---|
| `forward` / `reverse` | The approved pairs and their swap, longest-first at apply time |
| `reverse_extra` | Target forms the model produced that the forward pass never created |
| `protect_reverse` | Phrases that must survive the reverse pass untouched |
| `ambiguous` | Targets with more than one possible source; computed, not hand-written |
| `documents` | Hashes before/after, so you can tell which version a file is |

Lifecycle: create at apply time → keep local while the model works → extend
`reverse_extra` / `protect_reverse` as the output reveals new forms → restore →
verify → delete.

<a id="ambiguity"></a>
## Ambiguity: many-to-one targets

**Prefer an injective mapping when a restore is planned.** One original → one distinct
replacement. Collapsing the brand `Ромашка` and the legal entity `ООО «Ромашка»` into a
single `Globex` is convenient for reading and expensive for reversing. Giving them
distinct replacements (`Globex`, `Globex Legal`) removes the problem entirely.

When collapse is unavoidable, supply decisions:

```bash
python scripts/restore.py out/ --key key.json --decisions-template decisions.json
# fill it in, then
python scripts/restore.py out/ --key key.json --decisions decisions.json
```

A decision is either a global choice or context rules:

```json
{
  "Globex": [
    {"contains": "Работаю в", "choose": "ООО «Ромашка»"},
    {"contains": "приложение", "choose": "Ромашка"},
    {"default": "Ромашка"}
  ]
}
```

Rules are matched against the line containing the occurrence, first match wins,
`default` applies when nothing matched. Without a decision the occurrence is left
untouched and reported with its context - never guessed.

<a id="inflection"></a>
## Target-language inflection

The forward pass needed a source-language case table. The reverse pass needs a
**target-language** one, because the model declines the replacement freely.

Build it from what the output actually contains. `restore.py` lists every token built
on a target stem that no reverse pair covers:

```
-- UNKNOWN TARGET FORMS: add to key.reverse_extra --
   Сингапуры                    x2
   сингапурцам                  x1
   по-сингапурски               x1
```

Add a pair for each, with the correct source form:

```json
"reverse_extra": [
  {"from": "Сингапуры", "to": "Зареченски"},
  {"from": "сингапурцам", "to": "зареченчанам"},
  {"from": "по-сингапурски", "to": "по-зареченски"}
]
```

Notes:

- Replacement is case-sensitive, mirroring the forward pass. A model that lowercases a
  proper noun produces a form you must add explicitly.
- Indeclinable targets (Косово, Монако) do not take endings, but derivations still
  appear; handle them the same way.
- Adjectives and demonyms decline too; do not stop at the noun.

<a id="protect"></a>
## Protecting legitimate mentions

If the target locale is a real place, the model may write about it genuinely.
`protect_reverse` masks those phrases before reversing and restores them afterwards:

```json
"protect_reverse": ["Сингапурские авиалинии", "Сингапурский зоопарк", "Singapore Airlines"]
```

Protection is phrase-based and case-insensitive. Prefer specific phrases over the bare
country name - protecting the whole name would block the restore entirely.

<a id="verify"></a>
## Verifying the round trip

```bash
python scripts/restore.py out/ --key key.json --verify-against backup-anon/
```

Each file is compared with its pre-anonymization original:

- `identical` - lossless round trip. On a file the model returned verbatim, this is the
  proof that the key and the pairs are complete.
- `differs` - expected when the model edited the text. Read the diff; the difference
  should be the model's edit, not a missed or wrong restoration.
- `no counterpart found` - the original is not in the backup directory; check the path.

Keep at least one file the model does not change as a control. Without a control you
cannot distinguish "the key is incomplete" from "the model rewrote it".

<a id="limits"></a>
## What cannot be restored

- Terms the model dropped, paraphrased beyond recognition, or translated.
- Identifiers that were **neutralized** rather than substituted: «приложение оператора
  связи» carries no information about which operator, so there is nothing to reverse.
  Neutralization is one-way by design.
- Content the model invented. Restoring must not turn invented text into a claim about
  the real employer or city.

Report these honestly instead of forcing a substitution.

<a id="hygiene"></a>
## Key hygiene

The key is a complete deanonymization table. Treat it like a credential:

- **Never put it in a prompt.** Not the file, not a fragment, not "just the pairs".
  The whole point of the forward pass is that the model never sees this mapping.
- Keep it outside the published tree and out of git (`.gitignore` it).
- Do not delete it before the restore is done and verified - that makes the originals
  unrecoverable.
- Delete it, the decisions file and the restore backups once the restored text is
  accepted, unless the user wants an audit trail.
- The anonymized text plus the key equals the original. Anyone holding both has
  everything; sharing the "anonymous" version while leaking the key is a full leak.

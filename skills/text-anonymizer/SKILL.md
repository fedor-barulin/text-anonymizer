---
name: text-anonymizer
description: Depersonalizes prose and documents by replacing locale-bound references (employer, legal entity, city, region, districts, domains, email, partner banks, local brands, channel names and handles) with equivalents from another country, or by neutralizing them into generic wording. Use whenever the user wants to anonymize, depersonalize, de-identify, relocalize or "singapurize" text, remove ties to a city, region or employer, publish a case study without naming their company, swap the locale in a resume, post, article, chat export or agent memory file, or asks "find every mention of X in my project". Always ask what is being anonymized and which target country to use; never assume a default locale. Handles Russian inflection and homonym collisions, hunts invisible local ties, and verifies that no originals survive.
---

# Text Anonymizer

Swap the locale out of a text without breaking the text. Someone wants to publish a
case study, a resume, a blog post or an agent memory dump without revealing where
they live and who they work for. The naive approach - find-and-replace the city name -
produces broken grammar, mangled unrelated words, and a false sense of safety, because
the strongest identifiers are usually the ones nobody thought to search for.

This skill runs the job as a pipeline: **intake → inventory → mapping → approval →
apply → language pass → verify → cleanup**. Each stage exists because skipping it
has a specific, predictable failure mode.

## Two modes

Ask which one the user wants; they are not interchangeable.

| Mode | What happens | When it fits |
|---|---|---|
| `substitute` | Every local reference becomes a specific counterpart in the target country | The text should read as if the author lives there |
| `neutralize` | References become generic wording: "a telecom operator", "a large city", "a partner bank" | The author does not want to claim a new identity, just remove the old one |

`neutralize` is safer and often what a publication rule actually requires. `substitute`
creates new factual claims (a new employer, a new city, a new bank), so it needs the
user's explicit sign-off on each entity. Many jobs mix both: substitute the geography,
neutralize the employer.

## Step 0 - Intake (never skip, never assume)

The target country is the user's choice, not a default. Ask before touching anything.
Use `AskUserQuestion` when available, otherwise ask in plain text.

Required questions:

1. **What are we anonymizing?** Exact files, directories, or a scope description.
   Offer the inventory you can already see, and separate authored text from raw data
   dumps - they differ by orders of magnitude in effort and risk.
2. **Which target country / locale?** Do not propose one as the default. If the user
   has no preference, offer 2-3 concrete options and let them pick.
3. **Which mode?** `substitute`, `neutralize`, or mixed.
4. **Entity-level decisions** for anything that needs a real-world counterpart:
   legal entity, brand, product names, domains, email, partner bank, local chains.
   A wrong bank or a real company name used as a fictional employer creates a new problem.

Also confirm two boundaries that people rarely think about until it is too late:

- **Raw data** (chat exports, logs, crawled feeds): include or leave alone? These can
  hold thousands of occurrences and are often the strongest deanonymization source.
- **Non-text carriers**: images, screenshots, filenames, git history. Text replacement
  cannot fix these; the user needs to know they remain.

Record the answers. Everything downstream depends on them, and re-asking mid-job
wastes the user's time.

## Step 1 - Inventory

Run the scanner over the agreed scope:

```bash
python scripts/scan.py <paths> --terms "<employer>,<city>,<region>" --json work/inventory.json
```

It reports every inflected form with counts and sample contexts, plus filenames and
`@handles` that carry the term. Read the output before writing any mapping - the form
list tells you which declensions you have to handle.

Then do a **second pass for invisible ties**, which the scanner cannot find because
they do not contain the search terms. This is where most leaks survive. Look for:

- districts, suburbs, streets, parks, rivers, local landmarks
- regional companies, banks, railways, utilities, sports clubs, local media and bloggers
- phone area codes, postal code prefixes, regional internet domains
- local slang, demonyms, and puns built on the city name
- universities, employers' subsidiaries, conference names

`references/leak-checklist.md` has the full checklist and the cleanup rules.
For Russian text, `references/ru-inflection.md` covers declension and homonyms - read
it before building the mapping, not after the grammar breaks.

## Step 2 - Build the mapping

Write a mapping file (template: `assets/mapping.example.json`):

```json
{
  "target_locale": "<country>",
  "mode": "substitute",
  "protect": ["<homonym fragments that must never change>"],
  "pairs": [
    {"from": "<longest, most specific form>", "to": "<replacement>", "note": "legal entity"}
  ]
}
```

Rules that come from real failures:

- **Longest first.** `apply.py` sorts by length automatically, but write specific
  multi-word phrases anyway (`ООО «X» (Y)` before `Y`). A short pair applied first
  eats the context a longer pair needed, and you get duplicated tokens.
- **Protect the homonyms.** A brand root often lives inside ordinary words
  (`мотивация`, `лейтмотив`, `по мотивам`, English `motive`), surnames, and unrelated
  companies. List those fragments in `protect`; they are masked during replacement
  and restored afterwards. Replacing by bare root is the single most destructive
  mistake in this job.
- **Cover every declension** you saw in the inventory, not just the nominative.
- **Decide handles explicitly.** Changing a channel's display name while leaving
  `@city_channel` intact leaks exactly what you were hiding. Either change both or
  leave both, and tell the user which you did.
- **Keep the mapping out of the final tree.** It contains every original name in one
  place - it is a deanonymization key. Same for backups. Plan their removal in Step 7.

## Step 3 - Get approval

Show the user the mapping as a table (original → replacement → why) and the list of
things you deliberately left alone. Substitutions are editorial decisions about their
identity, not mechanical edits; a wrong counterpart is worse than no edit. Wait for
confirmation before applying.

If the scope is large, apply to one representative file first and show the diff.

## Step 4 - Apply

Dry run, then real run:

```bash
python scripts/apply.py --mapping mapping.json <paths> --dry-run
python scripts/apply.py --mapping mapping.json <paths> --backup-dir work/backup-anon
```

The script preserves bytes and line endings, backs up originals, validates JSON files
after replacement (and rolls back a file if it stopped parsing), and reports
per-pair counts. It also flags suspicious artifacts for the next step.

Backups are mandatory when there is no version control. Check for a git repo first;
without one, an unrecoverable bulk edit is a real risk.

## Step 5 - Language and sense pass

Mechanical replacement is not the end. Read every changed line and fix:

- **Grammar.** Substituting a nominative form into an oblique case produces nonsense
  ("каналы Сингапур и Москвы"). The replacement has to agree with the sentence.
- **Sense.** A district name, a pun, or a sports club may need a different counterpart
  than the city does, or may need to stay untouched.
- **Artifacts.** Doubled tokens (`Globex Globex`), a replacement glued to a suffix
  (`Globexация`), a replacement inside a URL or a hex color that was never a match.
- **Factual claims.** If the text now asserts something the user never said (a real
  relocation, a real employer, a real bank relationship), flag it rather than smoothing
  it over. Anonymizing is not inventing a biography.

`apply.py` and `verify.py` list candidate artifacts; the judgement is yours.

## Step 6 - Verify

```bash
python scripts/verify.py <paths> --terms "<original terms>" --targets "<replacements>" --allowlist work/allowlist.txt
```

Exit code is non-zero while real leftovers remain, so this can drive a loop:
fix → re-verify → repeat until clean. The script separates genuine leftovers from
benign homonyms (via the allowlist of word fragments), and checks the leak vectors
that text replacement misses: filenames, `.pyc` bytecode, git logs and config,
backup directories, and the mapping file itself.

Report honestly what is still there. "Clean" means clean within the agreed scope,
not clean everywhere.

## Step 7 - Cleanup and report

Ask whether the user wants a tree with no trace of the originals. If yes, remove:

- the backup directory (and the empty folder left behind)
- the mapping file and any inventory/report JSON that quotes originals
- generated `.pyc` files - they embed the old strings and are easy to miss

Then re-run `verify.py` over the whole tree, not just the edited scope.

Finish with a report: what changed per file, the mapping used, what was deliberately
left alone (raw data, images, git history), and what still needs a human decision.
Name the remaining deanonymization vectors explicitly - a partial job described as
complete is the worst outcome.

## Boundaries

This is privacy and publication hygiene: removing identifiers from text the user owns.
Keep it that way. Do not use it to fabricate credentials, alter identity or financial
documents, impersonate a real person or company, or misrepresent facts to a service
that is verifying them. If a request crosses that line, say so and stop.

Also: never invent biographical details to fill a gap. If a counterpart is unknown,
ask or neutralize - do not guess.

## Resources

- `references/ru-inflection.md` - Russian declension, homonym protection, invisible
  ties specific to Russian-language text. Read before building a mapping for Russian.
- `references/leak-checklist.md` - where identifiers hide beyond the obvious terms,
  and how to clean up without leaving a deanonymization key behind.
- `assets/mapping.example.json` - mapping template with a fictional example.
- `scripts/scan.py` - inventory of forms, counts, contexts, filenames, handles.
- `scripts/apply.py` - ordered, protected replacement with backup and JSON safety.
- `scripts/verify.py` - leftover and artifact detection, leak vectors, exit code for loops.

Scripts need Python 3.8+ and no third-party packages. Run them from the skill
directory or by absolute path; they import their shared helper from `scripts/`.

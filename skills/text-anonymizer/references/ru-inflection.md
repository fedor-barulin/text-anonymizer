# Russian-language specifics

Read this before building a mapping for Russian text. Russian is inflected, so a
find-and-replace of the dictionary form silently breaks every oblique case, and the
most common brand roots are also ordinary words.

## Contents

- [Declension: replace the form, not the lemma](#declension)
- [City → target city: case table](#city-table)
- [Demonyms and adjectives](#demonyms)
- [Homonyms: the protect list](#homonyms)
- [Invisible ties in Russian text](#invisible-ties)
- [Handles, puns and wordplay](#handles)
- [Grammar pass checklist](#grammar-pass)

<a id="declension"></a>
## Declension: replace the form, not the lemma

A scanner reports forms, not lemmas. If the inventory shows `Зареченска`,
`Зареченске`, `Зареченском`, you need a pair for each, or a single pair per form.
Replacing only `Зареченск` leaves the endings attached to the new name:

```
BAD:  выручка девелоперов Зареченск растёт   →  выручка девелоперов Сингапур растёт
GOOD: выручка девелоперов Зареченска растёт  →  выручка девелоперов Сингапура растёт
```

The same applies to lists of cities in the nominative ("Приемка квартир Зареченск
Тюмень Новосибирск") - there the nominative is correct, so do not "fix" it.

<a id="city-table"></a>
## City → target city: case table

Build this table for the actual pair before writing pairs. Example: `Зареченск` →
`Сингапур`.

| Case | Source form | Target form |
|---|---|---|
| Именительный | Зареченск | Сингапур |
| Родительный | Зареченска | Сингапура |
| Дательный | Зареченску | Сингапуру |
| Винительный | Зареченск | Сингапур |
| Творительный | Зареченском | Сингапуром |
| Предложный | Зареченске | Сингапуре |

Notes:

- masculine consonant-final cities decline; `Сингапур` declines the same way, which
  makes it a convenient target. Targets ending in `-о` (Косово, Монако) are
  indeclinable - the case endings disappear, and prepositions may need rephrasing.
- Feminine targets (`Москва`, `Казань`) decline differently; do not reuse a masculine
  table.
- Region names behave differently from city names: `Зареченская область` →
  `Сингапур` (a city-state has no oblast), not `Сингапурская область`. Decide the
  administrative level explicitly with the user.
- Abbreviations (`Зар-ск`, `ЗБК` and similar short forms) are separate tokens; add
  pairs for each, including lowercase chat-style spellings.

<a id="demonyms"></a>
## Demonyms and adjectives

These carry the location just as strongly as the city name and are easy to miss:

- demonym: `зареченчанин`, `зареченчанка`, `зареченчане` → `сингапурец`, `сингапурка`,
  `сингапурцы`. Check the actual target demonym; some are irregular.
- adjective: `зареченский`, `зареченская`, `зареченское`, `зареченские` and all
  case forms → `сингапурский` and its forms.
- colloquial adjectives and slang built on the city name often have no dictionary
  form; search the corpus for the stem, not the full word.

<a id="homonyms"></a>
## Homonyms: the protect list

A brand root frequently lives inside unrelated words. Replacing by bare root is the
most destructive mistake in this job. Put these fragments in `protect`:

| Fragment | Why it must survive |
|---|---|
| `мотиваци` | мотивация, мотивационный - ordinary words, not a brand |
| `мотиватор` | мотиватор, мотиваторы - ordinary words |
| `мотивирован` | мотивированный, мотивировать - ordinary words |
| `по мотивам` | "based on" - a prepositional phrase |
| `лейтмотив` | leitmotif - a common noun |
| `мотив` (lowercase, in prose) | "motive/reason" in psychology, product, and art texts |
| `motive` | English word, unrelated to a Cyrillic brand |
| surnames | a surname may contain the brand root; it is a person, not a company |
| unrelated companies | other firms sharing the root (banks, factories, clubs) |

The same trap exists for geography: a region root can belong to a sports club, a
factory district, a different company, or a food brand. Protect those, and tell the
user which ones you protected - some of them are still regional fingerprints and
need a separate decision.

Practical rule: search by the root to **find** candidates, then replace only by
explicit word forms or phrases. Never run a root-level replacement over prose.

<a id="invisible-ties"></a>
## Invisible ties in Russian text

These do not contain the city or employer name, so a term search misses them:

- **Districts and suburbs** of the source city - often the strongest fingerprint,
  because only locals mention them.
- **Local infrastructure**: regional railway (`ХЖД`), metro lines, airports,
  reservoirs, rivers, parks named after local figures.
- **Regional companies**: banks, utilities, retail chains, developers, factories,
  holdings. A partner bank named in a product description identifies the region.
- **Local media and bloggers**: city news channels, well-known local personalities.
- **Codes**: phone area code (`+7 3XX`), postal prefixes, regional domain zones.
  Beware false positives: a hex color like `#22343a` contains `343`.
- **Institutions**: universities, conferences, exhibition centers.
- **Demonyms and slang** (see above).

Run a second scan with these terms once you have identified them, and keep the
resulting list in the report - the user should see what was found beyond the obvious.

<a id="handles"></a>
## Handles, puns and wordplay

- **Handles**: `@city_channel`, `@city_flex`, `@school_city`. Changing the display
  name but not the handle leaks the location. Change both, or leave both and say so.
  Remember that changing a handle breaks the link to the real channel - if the file
  is a working log rather than a publication, ask before rewriting identifiers.
- **Puns**: a channel name may be a portmanteau of the city and a word
  (`Город` + `экстаз`). A literal substitution kills the joke. Invent an equivalent
  pun on the target name, or neutralize it, and flag the choice.
- **Wordplay on the brand**: diminutives, internal nicknames, product sub-brands
  (`BrandTV`, `BrandPay`, `Brandчик`). Each needs its own pair; a bare brand pair
  will not catch them.

<a id="grammar-pass"></a>
## Grammar pass checklist

After `apply.py`, read every changed line and check:

- [ ] case agreement: prepositions and verbs govern the right form
- [ ] lists of cities stay in the case the original used
- [ ] no doubled tokens (`Сингапур Сингапур`) from overlapping pairs
- [ ] no glued suffixes (`Сингапурация`) from a pair applied inside a longer word
- [ ] adjectives and demonyms agree with the new noun in gender and number
- [ ] URLs, emails and domains are consistent with each other
- [ ] the text does not now assert a fact the user never stated

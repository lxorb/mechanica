# Impossible model years in the registry

Read-only audit, 2026-09-20, against `api/data/registry.json` (53,575 rows).

## The 124 was a miscount — correct it before acting on it

I reported "124 impossible-year rows". That number counted **year values, not rows**: 124 values
spread over **7 rows**, and every one of those values is a plausible historical year. Counted
properly:

| test | rows |
|---|---|
| year < 1885 or > 2028 | **0** |
| year not four digits | **0** |
| year < 1950 | 7 (all Harley, all genuine — see below) |
| year span > 25 years | 2 (both Harley archive ranges) |

**No row in the registry currently has an impossible year.** The only real malformed years were the
five already retracted through `badyear.drop.json`; they are documented below because the faults that
produced them are still live in two adapters.

## serviceinfo.harley-davidson.com — 7 rows, not a fault, do not drop

These are Harley's historical archive. A naive `year >= 1950` bound deletes all seven.

| id | make | model | years | url |
|---|---|---|---|---|
| serviceinfo-harley-davidson-com-99403-93-1903-english-owner | Harley-Davidson | The Legend Begins | 1903, 1969 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99403-93 |
| serviceinfo-harley-davidson-com-99404-93-1909-english-owner | Harley-Davidson | Parts Listing | 1909–1932 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99404-93 |
| serviceinfo-harley-davidson-com-99405-93-1911-english-owner | Harley-Davidson | Oper./Maint./Spec. Book | 1911–1930 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99405-93 |
| serviceinfo-harley-davidson-com-99410-93-1917-english-owner | Harley-Davidson | Shop Dope/Service Bulletins | 1917–1949 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99410-93 |
| serviceinfo-harley-davidson-com-99406-93-1930-english-owner | Harley-Davidson | Parts Listing | 1930–1949 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99406-93 |
| serviceinfo-harley-davidson-com-99407-93-1930-english-owner | Harley-Davidson | Oper./Maint./Spec. Book | 1930–1949 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99407-93 |
| serviceinfo-harley-davidson-com-99419-93-1940-english-owner | Harley-Davidson | 's Military Models - WLA/XA | 1940–1945 | https://serviceinfo.harley-davidson.com/documents/lookup?reference=99419-93 |

Two real defects here, neither about years:

- **The title carries the year range twice** — `"1903-1969 1903-1969 The Legend Begins (99403-93)"`.
  The adapter prepends a range it has already taken from the listing text.
- **The model name is a sliced title** — `"'s Military Models - WLA/XA"` lost its `1940` prefix, so
  the model string starts mid-word. The year was stripped out of the middle of the name, not off
  the front.

These rows are `documents/lookup?reference=…` landing pages, not PDFs, so they never reach ingest.

## yamaha-motor.eu — 4 rows, retracted, fault still live

| id | make | model | raw years | url |
|---|---|---|---|---|
| yamaha-motor-eu-xj6f-201-en-owner-1vi73zcg | Yamaha | XJ6F | **201**, 2011–2016 | https://cdn2.yamaha-motor.eu/prod/owner-manuals/Motorcycles/P1CW28199E4E.PDF |
| yamaha-motor-eu-fz8-n-201-en-owner-3ahgtnky | Yamaha | FZ8-N | **201**, 2010–2015 | https://cdn2.yamaha-motor.eu/prod/owner-manuals/Motorcycles/P2SH28199EGE.PDF |
| yamaha-motor-eu-fz8-n-201-en-owner-ebcanthx | Yamaha | FZ8-N | **201**, 2010–2015 | https://cdn2.yamaha-motor.eu/prod/owner-manuals/Motorcycles/P2SH28199E1E.PDF |
| yamaha-motor-eu-xj6-n-201-en-owner-eskz-kxt | Yamaha | XJ6-N | **201**, 2010–2013 | https://cdn2.yamaha-motor.eu/prod/owner-manuals/Motorcycles/P20S28199EGE.PDF |

**Suspected fault (mine, in `api/app/registry/yamaha.py::yamaha_eu`).** The `years` array from
`yamaha-motor.eu/services/api/owner-manuals` contains a truncated `"201"` alongside the full years —
upstream data, most likely a `"2010"` that lost its last character. The adapter accepts it because
its only filter is `str(y).isdigit()`:

```python
years = sorted({int(y) for y in (row.get("years") or []) if str(y).isdigit()})
```

`201` then becomes the first (lowest) year, so it lands in the row id and derives a `yamaha-xj6f-201`
vehicle. Note the good years on these rows were real coverage — dropping the rows was only safe
because the corrected `yamaha-eu.json` fragment re-added them under clean ids.

## hondamotopub.com — 1 row, retracted, fault still live

| id | make | model | raw year | url |
|---|---|---|---|---|
| hondamotopub-com-ahm-trx500fm2-e-5019-en-owner | Honda | TRX500FM2  E | **5019** | https://2rom-prd-data.hondamotopub.com/om/AHM/TRX500FM2%20%20E/5019/19YM%20TRX500FM2%20%20E_32HR4650.pdf |

**Suspected fault (mine, in `api/app/registry/honda.py::_region`).** This one is upstream typo, not
parsing: Honda's AHM portal itself files the document under model year `5019`, and the filename
confirms the truth (`19YM…` = 2019 model year). The adapter takes `model_year` verbatim with
`y.isdigit()` and never range-checks it. Two secondary smells in the same row: the model name carries
a double space (`TRX500FM2  E`), and a TRX500 is an ATV, so the AHM region is leaking non-motorcycles
into a motorcycle registry.

## What the merge-time check should do

- **Bound: 1885 … current year + 2.** Not 1950 — that erases the seven Harley rows above, which are
  the oldest genuine manuals in the database.
- **Reject the value, keep the row**, when the rest of its years are sane: three of the four Yamaha
  rows carried six or seven good years next to the bad one, and dropping whole rows cost coverage
  that had to be re-added from a fragment.
- **Log per site with the raw value**, so an upstream typo (Honda `5019`) is distinguishable from an
  adapter bug (Yamaha `201`) without re-reading the source.
- Re-checking is cheap: the whole audit is one pass over `registry.json`, no network, no PDF reads.

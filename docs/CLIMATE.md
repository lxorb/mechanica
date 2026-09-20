# Climate Fit

The manuals already print rules that depend on where the vehicle lives — an antifreeze floor, a
temperature-banded oil grade, "service more often in dusty conditions", a salt-corrosion washdown.
None of them knows where the vehicle is. Climate Fit resolves those printed rules against the
measured climate at the nearest NOAA ISD station and shows **the manufacturer's own line**, with the
page it is printed on. No prose, no generated advice, no model call at request time.

Built 2026-09-20. Every number below is measured on this machine unless it says otherwise.

## What it is made of

| artefact | what | size | built by |
|---|---|---|---|
| `api/data/climate/stations.json` | the 12,776 ISD stations whose `END >= 20250101` | 1.58 MB | `--stations` |
| `api/data/climate/isd-2024.jsonl` | one reduced row per station-year | 3.5 MB | `--isd` |
| `api/data/climate/climatology.json` | merged per-station record the runtime reads | 4.34 MB | `--climatology` |
| `api/data/climate/rules/{manualId}.json` | the extracted rulebook, one file per manual | ~1 MB total | `--rules` |
| `api/data/climate/extract_cache.json` | pass B answers keyed by `sha256(ruleType\|window)` | — | `--rules --model` |
| `api/data/climate/rules_report.json` | per-manual counts, drops, model spend | — | `--rules` |
| `api/data/climate/anomalies.json` · `families.json` | the cross-OEM table and the audited model-family clusters | — | `--anomalies` |
| `api/data/climate/quality_ablation.json` | the quality-code ablation, shipped as a report | — | `--ablation` |

Nothing raw is stored. A station-year is streamed over plain HTTPS, reduced **in the stream**, and
thrown away; only the reduced row survives. The 2024 sweep streamed **4,260 MB** and parsed
**121,751,290 observations** in **537 s** at 48 threads, and left 3.5 MB on disk.

## Build

```bash
cd api
.venv/Scripts/python -m tools.climate_build --stations
.venv/Scripts/python -m tools.climate_build --isd --years 2024 --threads 48
.venv/Scripts/python -m tools.climate_build --climatology
.venv/Scripts/python -m tools.climate_build --rules --model --budget 15
.venv/Scripts/python -m tools.climate_build --anomalies
.venv/Scripts/python -m tools.climate_build --ablation --limit 400
```

`--list`, `--country` and `--max-size-gb` mirror the flags on Voloridge's own
`s3://voloridge-hack-mit-2026/src/noaa-isd/fetch.py`, so a judge can swap one fetcher for the other.
The sweep is resumable: a station id already in `isd-{year}.jsonl` is skipped, so an interrupted run
picks up where it stopped.

## NOAA ISD, and the two traps

`s3://noaa-isd-pds` is public and anonymous and also answers on plain HTTPS
(`https://noaa-isd-pds.s3.amazonaws.com/...`), so there is no boto3, no AWS account and no key in
this pipeline.

1. **`isd-history.csv` is mostly history.** 29,661 stations, of which **12,776** have
   `END >= 20250101`. Without that filter a nearest-station join silently lands on a station that
   stopped reporting in 1994.
2. **Observations are not hourly.** International Falls reported 15,007 quality-passed readings in
   2024 — roughly one every 35 minutes — and a thin station reports six a day. So the stored
   quantity is the **share** of quality-passed readings below each threshold, plus the raw reading
   count; hours are only ever derived as `share × 8,766` at render time, and the UI says
   "108 readings below −25 °C (~63 h)" so the reader can see which number came out of the archive.
   Station-years with fewer than 2,000 quality-passed readings are dropped (1,701 of 12,416).

Air temperature is 1-based characters 88–92, signed tenths of °C, `+9999` = missing; character 93 is
the quality code and `2,3,6,7,9` are dropped. Measured over 400 station-years: **0.12%** of readings
carry a suspect or erroneous code, and 6 of 400 annual minima move at all. It still decides verdicts:
at `263240-99999` the 2024 minimum is **−21.5 °C with the filter and −25.1 °C without it**, so
keeping the filter is what stops a false "action needed" against the −25 °C floor.
(`api/data/climate/quality_ablation.json`.)

`isd-history.csv`'s `CTRY` column is NOAA's own and it collides: `CH` covers both ZUERICH-FLUNTERN
and WUDAOLIANG (4,613 m, Tibetan plateau). Reports print the raw code, never a guessed country name.

## The rulebook: three passes

`api/app/climate/rules.py`, build-time only.

- **Pass A — deterministic.** One regex family per rule type over the page text layer. No model, no
  cost. For `antifreeze_floor`, `oil_grade_band` and `altitude` the regex also parses the value, so
  **the whole demo path costs $0**. The patterns spell out the characters the PDFs actually print:
  U+2212 MINUS SIGN, U+2013 EN DASH, U+2265 for "at least". A scan for ASCII `"-25"` finds a
  fraction of them.
- **Pass B — structuring.** Only the candidate windows Pass A could not parse reach the model: a
  ±400-character window, one structured call per window, **never per page**. Route
  `climate.extract`, model `gpt-5.6-luna`, hard USD cap enforced against the cost store the LLM door
  already writes. Cached by `sha256(ruleType|window)`, so a rerun is free.
- **Pass C — grounding, mandatory, on both passes.** The quote must be a character-for-character
  substring of the page's own text layer under the same fold `app/ingest/ground.py` uses. An
  invented threshold is a seized engine, so a rule that fails this is dropped and counted in
  `rules_report.json`.

Measured over the whole corpus (`api/data/climate/rules_report.json`):

| | |
|---|---|
| manuals scanned / with at least one rule | **529 / 519** |
| pages scanned | **93,932** |
| rules kept | **3,056** — antifreeze 1,028 · salt 605 · wet 446 · cold-start 361 · dust 301 · oil band 170 · heat 142 · altitude 3 |
| candidate windows sent to the model | **2,031** (one per rule type per page, never a whole page) |
| model rules dropped by pass C | **29** |
| spend on route `climate.extract` | **$0.67** of a **$15** cap, `gpt-5.6-luna` |
| wall clock | **453 s** at 16 threads; a rerun is **$0.00** off the cache |

Pass A alone — antifreeze, oil band and altitude, which is the whole demo path — costs **$0**.

Two clause shapes worth knowing, both of which broke a naive regex:

- the value is on the **next line**: `Antifreeze protection to at\nleast: −25 °C`;
- the value is a **range** where only the second end carries the unit: `−25 … −45 °C`. That is a
  mixing window, not a promise of −45, so the extractor takes the end closest to zero — the weakest
  guarantee.

## Verdicts: 0 tokens, tens of milliseconds

`api/app/climate/stations.py` holds two module-level tables, re-read when the file's mtime moves —
the same trick `app/registry` uses. A verdict is arithmetic over one station record and one printed
rule.

| status | means |
|---|---|
| `breached` | the manual's condition is met here often enough to act on |
| `borderline` | met, but marginally — within 3 °C of a floor, or under 5% of the year for a band |
| `ok` | not met |
| `unknown` | not measurable: no station within 50 km, no air-quality sensor within 25 km, no elevation |

A station further than **50 km** away renders `unknown`, never `ok`. `dust_interval` renders
`unknown` until `air.json` exists — never a guess.

Measured, warm process: **3–6 ms** per fit; the first call in a process also loads the 4.34 MB
climatology (~120 ms). `/climate/fit` memoises by `(manualId, round(lat,2), round(lon,2))` and sends
`Cache-Control: public, max-age=60`, exactly as `/api/catalog` does.

## Endpoints

| method | path | body / query | returns |
|---|---|---|---|
| `GET` | `/climate/station` | `lat`+`lon`, or `q` (a station name) | `StationClimate`, with `km` |
| `POST` | `/climate/fit` | `{manualId, bikeId?, lat, lon}` or `{manualId, place}` | `ClimateFit` |
| `GET` | `/climate/rules/{manual_id}` | — | `list[ClimateRule]` |
| `GET` | `/climate/anomalies` | `ruleType?`, `make?` | the cross-OEM table |

A typed name resolves against `stations.json` itself — there is no external geocoder anywhere in
this feature — and then `km` is `null` rather than `0.0`, because the station *is* the answer and
there is no distance to report.

## UI

`web/counter/js/climate.js` + `web/counter/css/climate.css`. One overlay, registered with `bus.js`
so it gets its own history entry (`#book+conditions`) and the header Back, the hardware Back and
Escape all close it first. Opened from the **Cond** button in the Book bar, next to Parts; the
`breached` rows also render as a strip above the Parts rows. The namespace is `.cf-*`, not `.cv-*`:
`css/chat-ui.css` already owns several unscoped `.cv-` rules (`.cv-foot`, `.cv-head`, `.cv-x`) and
they leak.

Screenshots of every step, taken against a local API by driving the real app in headless Chrome:
`docs/pitches/voloridge/shots/` — Book, Conditions at Minneapolis and International Falls, the
Bangkok negative control (0/4 breached), the tap that opens p. 215, the Parts strip, and the
geolocation path that prints the 10.8 km station distance.

Each row is a claim, a number and a page:

```
ANTIFREEZE PROTECTION                                          action needed
Antifreeze protection to at least: −25 °C (−13.0 °F)
108 readings below -25 °C (~63 h/yr), low -30.6 °C at             p. 215
FALLS INTERNATIONAL AIRPORT, 2024
```

Tapping it opens the PDF on p. 215. **The manual is still the answer**; we only worked out that it
applies to you.

Location, in this order, with no dialog on first paint: a place the counter already typed
(`localStorage`), then `navigator.geolocation` **only if permission is already granted**, then a
typed city resolved against the station table.

## Deploying

`api/.dockerignore` excludes `data/`, so the image ships no climate artefacts. Either add
`COPY data/climate ./data/climate` to `api/Dockerfile`, or sync `api/data/climate` to the blob
`data` container and set `CLIMATE_DIR`. `app/climate/paths.py` looks in `CLIMATE_DIR`, then
`DATA_DIR/climate`, then the repo's `api/data/climate`. Without them `/climate/*` answers
404/empty and nothing else in the API changes — the router is included inside the same
import-and-continue pattern the registry adapters use.

## Reproducing the findings

```bash
api/.venv/Scripts/python docs/pitches/voloridge/findings.py   # -> docs/pitches/voloridge/findings.md
api/.venv/Scripts/python docs/pitches/voloridge/antifreeze_scan.py
api/.venv/Scripts/python docs/pitches/voloridge/isd_probe.py sample 260
api/.venv/Scripts/python -m pytest api/tests/test_climate.py -q
```

`findings.py` regenerates both tables from the committed artefacts, including the seeded
260-station draw (seed 11) that the pitch quotes.

## What is not built

- **OpenAQ.** `api/app/climate/openaq.py` reduces a location-day to `pm10P90`/`dustyDays` and the
  builder has `--openaq`, but no sweep has been run and `air.json` is not committed, so
  `dust_interval` and `wet_interval` verdicts render `unknown` with the reason printed. That is the
  honest boundary; nothing guesses.
- **Multi-year.** Only 2024 is reduced. `--years 2019:2024` works and `merge_years` already folds
  several years into one record with `years: [..]`.
- **Held-out precision/recall.** Pass C guarantees every quote is real, but nobody has hand-labelled
  a held-out set, so the extractor's recall is unmeasured.

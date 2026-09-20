# Climate Fit — implementable spec

Owner of this document: the Voloridge-pitch agent. Owner of the implementation: whoever the founder
hands it to. Everything below is either already verified on this machine (marked **measured**) or an
explicit instruction. Nothing here needs an AWS account, a key, or a credit card.

Feature in one line: **the manuals already print rules that depend on where the vehicle lives; we
resolve those rules against 600 GB of hourly weather and global air quality, and show the
manufacturer's own line.**

---

## 1. What we already have (measured 2026-09-20)

| thing | number | source |
|---|---|---|
| registry rows | **53,557** | `api/data/registry.json` |
| distinct URLs behind them | **28,200** | same — 47% of rows point at a file another row already points at |
| portal hosts / makes | **84 / 80** | same |
| markets / languages | **59 / 43** | same |
| catalog vehicles | **27,751** (23,140 motorcycles, 4,611 cars) | `api/data/bikes.json` |
| …with a free manual offered | **13,537** | same |
| warm manuals live | **532** | `GET https://mechanica.emilvinu.ch/api/manuals` |
| pages / sections in them | **95,365 / 90,955** | same |
| vehicles those manuals cover | **659**, 9 makes | same |
| extracted specs (local corpus) | **107,452** across 508 spec files | `api/data/specs/*.json` |
| extracted specs (all ingest runs) | **137,379** | `api/data/mass_report.jsonl`, 648 `done` rows |
| grounded highlights | **431,292** (0 discarded, 2 clamped) | same |
| ingest cost | **$61.61 total, $0.095/manual** | same |

**Manuals containing at least one environment-conditional clause: 522 of 529 local page files
(98.7%).** Per clause family, counted over 93,932 pages of page text:

| clause family | manuals | occurrences |
|---|---|---|
| road salt / coastal / corrosion | 518 | 3,817 |
| dusty / sandy | 487 | 1,168 |
| antifreeze | 394 | 2,349 |
| wet / muddy / rain | 371 | 1,060 |
| ambient temperature | 340 | 1,123 |
| freezing / cold weather | 81 | 108 |
| high altitude | 43 | 74 |
| severe operating conditions | 41 | 55 |

That table is the dataset nobody has built: a corpus of **manufacturer rules that are conditional on
an environment the manual cannot see.**

---

## 2. External datasets (both on Voloridge's curated list)

### NOAA Integrated Surface Database — **[curated]**

- Registry: <https://registry.opendata.aws/noaa-isd/>
- Bucket: `s3://noaa-isd-pds` · `us-east-1` · public, anonymous. **Also plain HTTPS**, which is how
  the probe runs without boto3: `https://noaa-isd-pds.s3.amazonaws.com/<key>` (verified).
- `isd-history.csv` — 2.9 MB, **29,661 stations**; columns `USAF, WBAN, STATION NAME, CTRY, STATE,
  ICAO, LAT, LON, ELEV(M), BEGIN, END`. **12,776 have `END >= 20250101`** (measured) — the rest are
  historical and must be filtered or the nearest-station join silently lands on a station that
  stopped reporting in 1994.
- `isd-inventory.csv` — per station per year, monthly observation counts. Use it to skip empty years
  instead of issuing a doomed GET.
- Data: `data/{year}/{USAF}-{WBAN}-{year}.gz`, one gzipped fixed-width file per station-year,
  **0.1–1.0 MB each** (measured). Total archive ~600 GB uncompressed.
- Record layout (1-based character positions, from the ISD format document): air temperature
  **88–92** signed tenths of °C with `+9999` = missing, **93** = quality code; dew point 94–98;
  sea-level pressure 100–104; wind 61–63 / 66–69. In Python: `line[87:92]`, quality `line[92:93]`.
  **Quality codes `2,3,6,7,9` must be dropped.** Measured over 284 cached station-years and
  3,003,373 readings: only **0.12%** carry a suspect/erroneous code and only **1.4%** of station-years
  have their annual minimum move at all — but at Russian station `263240-99999` the 2024 minimum moves
  from **−25.1 °C to −21.5 °C**, which flips the antifreeze verdict. Small effect, decisive outcome.
- Working reducer: `docs/pitches/voloridge/isd_probe.py` — run it, it is the real thing.

### OpenAQ — **[curated]**

- Registry: <https://registry.opendata.aws/openaq/> · Bucket `s3://openaq-data-archive` ·
  `us-east-1` · anonymous.
- Layout: `records/csv.gz/locationid={id}/year={YYYY}/month={MM}/location-{id}-{YYYYMMDD}.csv.gz` —
  one gzipped CSV per location per day, 1 KB to a few hundred KB.
- Columns: `location_id, sensors_id, location, datetime, lat, lon, parameter, units, value`.
  `parameter` ∈ `pm25, pm10, no2, o3, so2, co`.
- **The bucket has no location index.** Discovery is either the OpenAQ v3 API (free key, header
  `X-API-Key`) or listing `locationid=` prefixes. Plan: one offline pass with the API to build
  `locations.json` (id, name, lat, lon, country, parameters), committed to the repo so the runtime
  never needs the key.

### Helper tooling Voloridge published

`aws s3 sync --no-sign-request s3://voloridge-hack-mit-2026/src ./src` gives a README + `fetch.py`
per dataset. Our reducer does not depend on them, but **name them in the pitch** — it shows we read
what they shipped. Their NOAA `fetch.py` has `--list`, `--country`, `--max-size-gb`; our builder
mirrors those flags so a judge can swap one for the other.

---

## 3. Build plan

Two artefacts, built offline, committed as data, served hot.

### 3.1 The rulebook — `api/tools/climate_build.py --rules`

Input: every warm manual's pages (`store.pages(manual_id)`, 95,365 pages) and specs
(`store.specs(manual_id)`, 137,379 rows).

**Pass A — deterministic candidate finder (no model, no cost).** One regex family per rule type,
run over page text and spec quotes. Emits candidate windows with page number and character span:

| rule type | trigger | value parsed |
|---|---|---|
| `antifreeze_floor` | `antifreeze protection (to at least)?` near a signed `°C`/`°F` | threshold °C |
| `oil_grade_band` | `ambient temperature` within 120 chars of `SAE \d{1,2}W[-/]\d{2}` and a `[≥><≤]\s*-?\d+ ?°C` | (threshold °C, comparator, grade) |
| `dust_interval` | `dust(y)?\|sandy` within 200 chars of an interval (`\d[\d.,]* ?(km\|mi\|miles\|hours\|h)\b`) or of `more (frequently\|often)` | base interval + "more often" flag |
| `wet_interval` | `wet\|muddy\|rain` in the same shape | same |
| `salt_wash` | `road salt\|salted road\|sea air\|coastal` near an imperative verb (`clean\|wash\|rinse\|lubricate`) | none (boolean rule) |
| `cold_start` | `below \d+ ?°C\|freezing` near `start\|warm(-\| )up\|battery` | threshold °C |
| `altitude` | `altitude (of\|above)` + a `\d[\d,]* ?(m\|ft)` | threshold m |
| `heat_limit` | `above \d+ ?°C\|high ambient` near `display\|battery\|charging\|coolant` | threshold °C |

**Pass B — structuring, one cheap call per candidate window, not per page.** Reuse
`api/app/llm.py` route style; add route `"climate.rules"`, model `gpt-5.6-luna` ($0.20/M). Input is
the ±400-character window plus the page number; output is the typed `ClimateRule` below. Budget:
~6,000 candidate windows × ~700 tokens ≈ **$0.90 for the whole corpus** (order-of-magnitude from the
$0.095/manual ingest cost). Cache by `sha256(window)` so a rerun is free.

**Pass C — grounding, mandatory.** Every emitted rule carries `quote`; drop the rule if `quote` is
not a character-for-character substring of the page's text layer after the same whitespace
normalisation `api/app/ingest/ground.py` uses. This is the difference between a feature and a
liability: an invented threshold is a seized engine. Record `rulesDropped` per manual in the build
report, exactly as `sectionsDropped` is recorded today.

Output: `api/data/climate_rules/{manualId}.json` → `list[ClimateRule]`, plus
`api/data/climate/rules_report.json` with per-manual counts, dropped counts and model spend.

### 3.2 The climatology — `api/tools/climate_build.py --isd --years 2019:2024`

1. Fetch `isd-history.csv`, keep `END >= 20250101` → **12,776 stations** → write
   `api/data/climate/stations.json` (~1.2 MB: `id, name, ctry, state, icao, lat, lon, elevM`).
2. For each station-year, stream the `.gz` and reduce **in the stream** — never write the raw file
   in production (the probe caches it only so a rerun is cheap). One pass accumulates:
   `obs`, `minC`, `maxC`, hours below `0/-10/-20/-25/-30/-35`, hours above `35/40`,
   `freezeThawCycles` (0 °C crossings, day-resolution), `meanC`, `p01C`, `p99C`, `dewSpreadMean`.
   **Observations are not hourly** — Minneapolis reported 13,760 quality-passed readings in 2024,
   roughly one every 38 minutes, and a thin station reports six a day. So count observations, store
   the *share* of quality-passed readings below each threshold, and derive hours as
   `share × 8,766` only when rendering. Never call a raw observation count "hours"; the UI says
   "108 readings below −25 °C (~63 h)". Also store `obs` so the UI can grey out a thin station.
3. Reduce the 6 years per station into one record with `years: [..]` and per-threshold
   **mean hours/year** and **worst year**. Size: 12,776 rows × ~40 numbers ≈ **4 MB JSON**, or 1.3 MB
   as `climatology.parquet` if DuckDB is available.
4. Throughput: 12,776 stations × 6 years ≈ 76,000 objects ≈ **40–50 GB gzipped streamed**. Measured
   locally at 24 threads over public HTTPS: 82.4 MB / 250 objects in ~3 minutes → ~7 hours for the
   full sweep from Switzerland. **On the Voloridge EC2 instances (us-east-1, same region as the
   bucket, free transfer via the S3 gateway endpoint) budget under an hour at 128 threads.** Ship the
   reduced file; the raw sweep is a one-time offline job. If time is short, ship `--years 2024`
   only (12,776 objects, ~8 GB, ~15 min on EC2) and say so.
   *Go to the Voloridge booth and ask for the instance — the challenge PDF explicitly offers it, and
   "we ran it on your cluster" is a free point.*
5. Every object is content-addressed by key; the builder skips a key whose local size matches, so the
   sweep resumes after any interruption.

### 3.3 Air quality — `api/tools/climate_build.py --openaq --years 2024`

1. One offline discovery pass against the OpenAQ v3 API → `api/data/climate/aq_locations.json`
   (id, name, lat, lon, country, parameters). Committed; runtime never calls the API.
2. For each location with `pm10` or `pm25`, stream `year=2024` days and reduce to:
   `pm10_p50, pm10_p90, pm25_p50, pm25_p90, dustyDays` (days with `pm10` daily mean > 50 µg/m³,
   the WHO interim target-1 24-hour level), `days`, `sensors`.
3. Output `api/data/climate/air.json`. Expect a few thousand usable locations; drop any with < 60
   reporting days and record how many were dropped.
4. **Join to stations**: for each ISD station, nearest OpenAQ location within 25 km (haversine);
   store `aqLocationId` and `aqKm` on the station record. Stations with no location inside 25 km get
   `aqLocationId: null` and the dust rules then return `unknown`, never a guess.

### 3.4 The anomaly table — `api/tools/climate_build.py --anomalies`

Group the rulebook by `(ruleType, normalisedName)` and emit, per group: the distinct values, how
many manuals print each, the split by market / make / model year, and a `spread` score. Two
sub-analyses:

- **Cross-OEM agreement**: does every maker print the same threshold for the same thing?
- **Model-year drift**: within one model *family*, did the printed value change between years? Family
  normalisation is the fuzzy join in this project: strip the year, lowercase, collapse
  `factory edition|fe|r|s|gt|adventure` suffix tokens, then cluster by token-set ratio ≥ 0.9 over the
  27,751-vehicle catalog. Every cluster is written to `api/data/climate/families.json` **with its
  members** so a human can audit a bad merge — no silent fuzzy matching.

Output `api/data/climate/anomalies.json`, which powers the insight screen and the pitch slide.

---

## 4. Schemas

Add to `api/app/models.py` (camelCase, byte-compatible with `web/.../types.ts`, same as every other
model in that file):

```python
class ClimateRule(BaseModel):
    id: str                    # sha1(manualId + page + ruleType + value)[:12]
    manualId: str
    ruleType: Literal["antifreeze_floor", "oil_grade_band", "dust_interval", "wet_interval",
                      "salt_wash", "cold_start", "altitude", "heat_limit"]
    name: str                  # the manual's own label, e.g. "Antifreeze protection"
    comparator: Literal["below", "at_or_below", "above", "at_or_above", "always"] | None = None
    thresholdC: float | None = None      # normalised to Celsius
    thresholdM: float | None = None      # metres, for altitude rules
    value: str | None = None             # "SAE 5W/40", "10000 km", "-25 °C" - the printed string
    intervalKm: int | None = None
    page: int
    quote: str                 # character-for-character from the page text layer
    sectionId: str | None = None

class StationClimate(BaseModel):
    id: str                    # "727470-14918"
    name: str
    ctry: str
    lat: float
    lon: float
    elevM: float | None = None
    years: list[int]
    obs: int
    minC: float
    maxC: float
    meanC: float
    hoursBelow: dict[str, float]   # {"0": 3048.2, "-10": 611.0, "-25": 8.4} mean hours per year
    hoursAbove: dict[str, float]
    worstMinC: float               # coldest single observation in the window
    freezeThawPerYear: float
    aqLocationId: int | None = None
    aqKm: float | None = None
    pm10P90: float | None = None
    dustyDays: int | None = None

class ClimateVerdict(BaseModel):
    rule: ClimateRule
    status: Literal["ok", "borderline", "breached", "unknown"]
    evidence: str              # "108 readings below -25 C (~63 h) at FALLS INTERNATIONAL, 2024"
    magnitude: float | None = None   # hours/year, or percent of year
    stationId: str
    stationKm: float

class ClimateFit(BaseModel):
    manualId: str
    bikeId: str | None = None
    station: StationClimate
    verdicts: list[ClimateVerdict]
    breached: int
    checked: int
```

`store.py` gains, on the `Store` protocol and both backends (`FileStore`, blob, mongo), exactly the
shape the existing `specs()` pair already uses:

```python
def climate_rules(self, manual_id: str) -> list[ClimateRule]: ...
def put_climate_rules(self, manual_id: str, rules: list[ClimateRule]) -> None: ...
```

`stations.json`, `climatology.json`, `air.json` and `anomalies.json` are read once per process into
module-level caches in `api/app/climate/stations.py`, invalidated by file mtime — the same trick
`registry` already uses.

---

## 5. Endpoints

All under the existing FastAPI app in `api/app/main.py`, so they arrive at
`https://mechanica.emilvinu.ch/api/...` with no worker change (`run_worker_first: ["/api/*"]` already
proxies everything).

| method | path | body / query | returns |
|---|---|---|---|
| `GET` | `/climate/station` | `lat`, `lon` | `StationClimate` — nearest active station, with `km` |
| `POST` | `/climate/fit` | `{manualId, bikeId?, lat, lon}` | `ClimateFit` |
| `GET` | `/climate/rules/{manual_id}` | — | `list[ClimateRule]` |
| `GET` | `/climate/anomalies` | `ruleType?`, `make?` | the cross-OEM / drift table |

`/climate/fit` is pure computation over two in-memory tables — **no model call, no network, no cost.**
Target p95 under 30 ms; cache by `(manualId, round(lat,2), round(lon,2))` in the existing
answer-cache style. Add `Cache-Control: public, max-age=60` in the worker exactly as `/api/catalog`
has, so repeat views are free.

New package `api/app/climate/`:

```
__init__.py      fit(manual_id, lat, lon) -> ClimateFit ; the only thing main.py imports
rules.py         Pass A regexes + Pass B prompt + Pass C grounding (build-time)
isd.py           fixed-width parse + per-station reduce (build-time; lift from isd_probe.py)
openaq.py        OpenAQ discovery + reduce (build-time)
stations.py      runtime: load tables, nearest station, evaluate a rule -> ClimateVerdict
anomalies.py     build-time: grouping, family clustering, spread scoring
```

Follow the pattern in `api/app/registry/__init__.py`: import adapters one at a time inside `try`, log
and continue, so a half-written module never takes the API down.

---

## 6. UI — one screen, no new paradigm

`web/counter/js/screens/conditions.js`, opened from the Book screen bar next to the existing Parts
button (`web/counter/js/screens/book.js` line ~249 builds that bar; add one `bar-btn bar-word`) and
shown as a strip at the top of the Parts sheet (`screens/invoice.js`).

Location is obtained in this order, no dialog on first paint:
1. `navigator.geolocation` if the user already granted it;
2. a typed city, resolved against `stations.json` by name (no external geocoder);
3. the shop's saved postcode in `localStorage`.

Each row is one `ClimateVerdict`, rendered in the product's existing voice — a claim, a number, and a
page:

```
COOLANT          breached
Your manual: antifreeze protection to at least -25 °C.
Your station: FALLS INTERNATIONAL AIRPORT, 4.6 km - 108 readings below that in 2024, low -30.6 C.
                                                        -> Manual p. 215
```

Tapping the row does what every other row in this app does: opens the PDF at that page with the
manual's own line highlighted. **The manual is still the answer.** We add the "does this apply to
me" that the manual could never print, and nothing else. Status colours reuse the existing token set;
`unknown` renders grey with "no station within 50 km" rather than disappearing.

Chat gets one tool, `climate_fit(lat, lon)`, registered beside the existing manual tools in
`api/app/chat.py`, so "do I need different oil here in January?" is answered with the manual's own
page and the station's own hours — never with prose.

---

## 7. The insight, and how it was validated (already done, before the build)

**Finding 1 — one number, nine markets.** Of the 508 local spec files, **206 manuals print an
antifreeze floor, and every single one prints −25 °C.** By market: EU 100, US 69, WW 26, RW 4, AR 3,
JP 1, PH 1, CN 1, BR 1. Zero variance across 9 markets, 4 makes and 3 model years. Reproduce:

```bash
api/.venv/Scripts/python docs/pitches/voloridge/antifreeze_scan.py
# distinct antifreeze floors: [('-25', 206)]
# by market: eu 100, us 69, ww 26, rw 4, ar 3, jp 1, ph 1, cn 1, br 1
```

Watch the minus sign: the PDFs print U+2212 and U+2013, never ASCII `-`. A scan for `"-25"` finds a
fraction of them — one of several places where this corpus's text layer is not the character you
would type, and a trap the rule extractor's regexes must handle everywhere.

**Finding 2 — how often that number is wrong.** `isd_probe.py sample 260`, seed 11, against the
12,776 stations still reporting: 250 had a 2024 file, 210 had ≥ 2,000 quality-passed observations,
**48 of 210 (22.9%) recorded a temperature below −25 °C during 2024.** 82.4 MB streamed, 2,384,890
observations parsed. A second independent sample (different filter on the station list, 217 usable)
gave 22.6% — the estimate is stable. Thresholds: below −20 °C 29.5%, −30 °C 13.8%, −35 °C 8.6%.
Countries breaching, in order: Russia, US, Canada, Norway, Finland, Kazakhstan — **and Fiji and
Bolivia**, which are high-altitude stations, not high-latitude ones. That is the unexpected bit: the
manual's single number fails on altitude as well as latitude, which is why `altitude` is its own rule
type in §3.1.

**Finding 3 — the rule that is already personalised, and nobody notices.** KTM prints a
temperature-banded oil grade: *"Engine oil grade at ambient temperature ≥ 0 °C — SAE 10W/50; at
ambient temperature < 0 °C — SAE 5W/40"* — **KTM 1390 Super Adventure R 2026 US, p. 215**. That same
page also prints *"Antifreeze protection to at least: −25 °C"*, and the full lubricant chart is on
pp. 239–240, which is why the demo bike shows both verdicts against one page. The same table appears
in 1290 Super Adventure S 2024 US p. 166 and 1390 Super Duke RR 2026 EU p. 183. Nearest-station
join, 2024 (`isd_probe.py cities`, measured):

| city | station | km | share of 2024 readings below 0 °C | what p. 215 says |
|---|---|---|---|---|
| Phoenix | PHOENIX SKY HARBOR INTL | 6.6 | **0.0%** | 10W/50 all year |
| Zurich | ZUERICH-FLUNTERN | 2.1 | 6.1% | 5W/40 for ~3 weeks |
| Minneapolis | MINNEAPOLIS-ST PAUL INTL | 10.8 | **20.7%** | 5W/40 for a fifth of the year |
| International Falls MN | FALLS INTERNATIONAL | 4.6 | **34.6%** | 5W/40 for a third of the year |
| Bangkok | BANGKOK METROPOLIS | 7.5 | 0.0% | 10W/50, and the rule never fires |

**Finding 4 — "more often" is never quantified.** 487 of 529 manuals tell you to service the air
filter more often in dusty conditions. Not one says how much more often, and not one knows whether
your air is dusty. OpenAQ does: `pm10_p90` and `dustyDays` turn "more often" into "Your location is
at the 91st percentile of PM10 among reporting stations; the manual's own severe-conditions column
on p. 174 applies to you." (Example clause, verbatim: Kawasaki Versys 1100 2026 US p. 174,
*"Service more frequently when operating in severe conditions: dusty, wet…"*; the same manual's
p. 216 says *"roads are salted or near the ocean"*.)

### How each claim is validated

1. **Extraction is grounded, not generated.** Pass C drops any rule whose quote is not a
   character-for-character substring of the PDF text layer. Today's equivalent gate discarded 0 of
   431,292 highlights and dropped 290 of 110,094 sections (0.3%) — the same gate, same code path.
2. **Held-out manual audit.** Hand-label every environment-conditional clause in 20 randomly chosen
   manuals (~2 h of human time, or an independent second model with a different prompt). Report
   precision and recall of the extractor in `rules_report.json` and in the pitch, with the actual
   numbers, whatever they are.
3. **Negative controls.** Bangkok, Dubai, Miami, Delhi must return zero `breached` cold rules. If a
   cold rule fires in Bangkok, the join or the comparator is broken. These four run in CI.
4. **Join-quality histogram.** Publish the distribution of nearest-station distance across the demo
   set and across 1,000 random populated coordinates. Any verdict from a station > 50 km away is
   rendered `unknown`, not `ok`.
5. **Quality-code ablation, as a shipped report.** Re-run the reduction with the filter disabled and
   publish the diff: measured on the cached sample, 0.12% of readings flagged, 1.4% of station-years
   with a moved minimum, and one station (`263240-99999`, 2024) whose verdict flips from breached to
   fine. Keep this in `rules_report.json` — the honest version is more convincing than an
   exaggerated one. **Do not repeat the −46.9 °C figure as a quality-filter result**: that number
   came from the name-based station join landing on the wrong station, a different bug (item 4).
6. **Reproducibility.** Seed 11, fixed station list, `isd_probe.py` in the repo, and every threshold
   in a constant, not a literal in a loop.

---

## 8. Demo moment (exact inputs)

1. Type **KTM 1390 Super Adventure R 2026** in the search box → confirm.
   **Pin the US manual** (`ktm-1390-super-adventure-r-2026-us-om`, 247 p.): that one vehicle maps to
   two warm manuals, and the page numbers differ by market — the antifreeze floor is p. 215 in the US
   manual and pp. 194/212 in the EU one, same −25 °C. A verdict is per *manual*, never per vehicle,
   and the UI must name which manual it read.
2. The manual opens. Tap **Conditions**. The browser has already granted location, so the strip is
   populated before the tap finishes animating.
3. Set location to **Minneapolis** (typed, so it is deterministic on stage):
   `MINNEAPOLIS-ST PAUL INTERNATIONAL, 10.8 km · 13,760 observations in 2024`.
   - `OIL — action needed · 20.7% of 2024's readings below 0 °C · your manual, p. 215: SAE 5W/40`
   - `COOLANT — ok · coldest 2024 observation −22.2 °C · floor −25 °C, p. 215`
4. Change the location to **International Falls, MN** — one field, no reload.
   - `COOLANT — breached · 108 readings below −25 °C in 2024, low −30.6 °C · p. 215`
   - `OIL — action needed · 34.6% of the year below 0 °C · p. 215`
5. Tap the coolant row. The PDF opens on p. 215 with *"Antifreeze protection to at least −25 °C"*
   highlighted. **The manufacturer said it; we only worked out that it applies to you.**
6. Change to **Bangkok**: every cold rule goes grey, and the dust rule lights up from OpenAQ. The
   negative control is part of the demo, on purpose.
7. Final screen: the anomaly table. *206 manuals. 9 markets. One number.* Next to it, the 22.9%.

Total: 70 seconds. Two typed inputs, no logins, no waiting on a model.

---

## 9. What we can honestly claim after building

- "We reduced **600 GB** of NOAA hourly observations to a **4 MB** climatology over **12,776**
  currently-reporting stations, and we stream it — we never store the raw archive."
- "We extracted **N** environment-conditional rules from **532 manuals / 95,365 pages**, every one
  grounded character-for-character against the PDF text layer, **M** dropped for failing that check."
- "**98.7%** of the manuals we hold contain at least one rule that depends on an environment the
  manual cannot see."
- "**206 manuals print an antifreeze floor. All 206 print −25 °C. In 9 markets.**"
- "**22.9%** of a random sample of 210 station-years breached that floor in 2024."
- "A verdict costs **0 tokens and ~30 ms**; the feature adds **$0** per question to a product that
  already answers for $0.0003."
- Whatever the held-out precision/recall turns out to be — stated as measured, not as a target.

---

## 10. File manifest for the implementing agent

Create:

```
api/app/climate/__init__.py          fit() - the only public entry point
api/app/climate/rules.py             extraction passes A/B/C  (build-time)
api/app/climate/isd.py               ISD fetch + fixed-width parse + reduce  (lift isd_probe.py)
api/app/climate/openaq.py            OpenAQ discovery + reduce  (build-time)
api/app/climate/stations.py          runtime tables, nearest station, verdict evaluation
api/app/climate/anomalies.py         grouping, family clustering, spread  (build-time)
api/tools/climate_build.py           CLI: --rules --isd --openaq --anomalies --years --threads --list
api/data/climate/stations.json       12,776 active stations
api/data/climate/climatology.json    reduced per-station record
api/data/climate/air.json            reduced per-OpenAQ-location record
api/data/climate/aq_locations.json   OpenAQ discovery output (committed; no API key at runtime)
api/data/climate/families.json       model-family clusters with members, for audit
api/data/climate/anomalies.json      the insight table
api/data/climate/rules_report.json   per-manual counts, drops, spend
api/data/climate_rules/{manualId}.json
web/counter/js/screens/conditions.js
```

Edit:

```
api/app/models.py        + ClimateRule, StationClimate, ClimateVerdict, ClimateFit
api/app/store.py         + climate_rules() / put_climate_rules() on Store, FileStore
api/app/store_blob.py    + the same pair
api/app/main.py          + 4 routes (section 5)
api/app/chat.py          + the climate_fit tool
web/counter/js/screens/book.js     + one bar button -> openOverlay("conditions")
web/counter/js/screens/invoice.js  + the conditions strip above the parts rows
web/counter/sw.js        bump the cache version (currently v7)
docs/ARCHITECTURE.md     + a row in Components and in the cost/latency table
```

Do not touch: the registry adapters, `ingest/*`, `parts_catalog.py`. Nothing in this feature needs
them to change.

### Ordering, with a 6-hour clock

| # | step | hrs | unblocks |
|---|---|---|---|
| 1 | `isd.py` + `stations.json` + `climatology.json` for 2024 only | 1.0 | everything |
| 2 | `rules.py` Pass A + C for `antifreeze_floor` and `oil_grade_band` only | 1.0 | the demo |
| 3 | `/climate/station` + `/climate/fit` + models + store | 0.75 | the UI |
| 4 | `conditions.js` + the book bar button | 1.0 | the demo |
| 5 | `anomalies.py` + `anomalies.json` + the insight screen | 0.75 | the pitch's punchline |
| 6 | Pass B (model) for the remaining six rule types | 0.75 | breadth |
| 7 | `openaq.py` + dust rules | 0.75 | the second dataset |
| **–** | **total** | **6.0** | 3.5 h critical path if 1+2 run in parallel with 5 |

Steps 1–5 are the demo. If the clock runs out, ship 1–5 and say in the pitch that OpenAQ is wired but
the sweep covers only the demo cities — an honest boundary beats a vague claim, and this is the
audience that will check.

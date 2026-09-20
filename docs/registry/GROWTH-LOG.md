# Registry growth log

One entry per handbook-growth cycle. Numbers come from `cd api && .venv/Scripts/python -m tools.registry stats`.
The **exhausted** lists are the point of this file: every source written there has been checked and
must not be re-walked. Read the last entry's *next leads* before starting a cycle.

## Ownership

From 2026-09-20 the handbook-growth agent is the **only** writer of `api/data/registry.json` and
`api/data/bikes.json` (the earlier registry agent has finished for good). Nothing else touches them,
so the only way they can be corrupted now is a self-inflicted race: `crawl` stores straight into the
registry while `merge-fragments`/`--replace` rewrites the whole file. Never overlap the two — write
fragments, then run exactly one merge, then `seed-catalog`, `catalog.mjs`, `sync_blob`, in that order.

## How a cycle ends (the sequence, in order)

```
cd api
.venv/Scripts/python -m tools.registry merge-fragments --replace <my-fragment>
.venv/Scripts/python -m tools.registry seed-catalog      # ← REQUIRED, see the trap below
cd .. && node web/tools/catalog.mjs
api/.venv/Scripts/python -m pytest api/tests -q
cd api && .venv/Scripts/python -m tools.sync_blob --json-only
.venv/Scripts/python -m tools.registry stats
```

**The trap:** `merge-fragments` rewrites `bikes.json` from `bikes_from_registry()`, which keeps a
seed-catalog vehicle only when a free PDF covers it. Every merge therefore deletes the bikez-seeded
vehicles that have no manual — 10,512 of them in cycle 1 — and the catalog silently shrinks.
`seed-catalog` puts them back from the cached CSV (`api/data/seeds/`, gitignored). Always run it
after a merge, and always take the *after* numbers from the run that follows it.

---

## Cycle 1 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 53,557 | **53,576** | +19 |
| free English owner PDFs | 24,210 | **24,224** | +14 |
| distinct PDF files | 14,770 | **14,781** | +11 |
| catalog vehicles | 27,751 | **27,765** | +14 |
| …with a `manualUrl` | 13,537 | **13,551** | +14 |

Motorcycle rows 44,653 (16,445 free en PDFs, 8,347 files, 23,154 vehicles, 9,438 with a PDF);
car rows 8,923 (7,779 / 6,434 / 4,611 / 4,113). 85 sites, 81 makes.

### Added

* **Royal Alloy** — `api/app/registry/royalalloy.py`, fragment `royalalloy.json`. New make, 81st.
  `www.royalalloy.com/wp-json/wp/v2/media?media_type=application` lists all 39 documents on the
  site in one call; 16 owner rows + 3 maintenance rows over **13 distinct PDFs**, all verified
  `%PDF-` by a ranged GET (13/13). GP125/150/180/200/300, GT125/150, TG125/180/200/300, 2018–2024.
  Two quirks the adapter has to handle and that will bite anyone re-reading it: the whole library
  was re-uploaded on 2024-08-10, so the WordPress date is not the model year (the issue stamp in
  the file name is — `20200805`, `2018.7.26`); and one file covers a whole range
  (`GP125150180EFI…`, `RA GP125S 200S`), so displacements are matched against the sizes Royal Alloy
  actually sells rather than read as a number, which is what keeps `20231107` from becoming a model.
  WordPress also kept up to four copies of the same manual (`-1.pdf`, `-2.pdf`); the shortest URL
  wins the row id.

### Tried this cycle and empty — do not re-walk

* **Kawasaki flipbooks** (the 1,233 KTIVS rows that are not PDFs) — re-confirmed dead from a new
  angle. The viewer template links `{bookpath}pdf/{page}.pdf`, i.e. **one PDF per page**, never a
  whole manual; there is no single-file download in the package. `kawasaki_pdf.py`'s docstring is right.
* **JLR** — `ownerinfo.jaguar.com` / `ownerinfo.landrover.com` `/model/<code>/<year>/document/<id>`
  (131 rows, 0 PDFs) 302 to the site root for any non-browser client. SPA, no static document.
* **WordPress media sweep, 26 brands.** No `wp-json` or no documents: lexmoto.com, keeway.com,
  zontes.com, rieju.com, italjet.com, ajpmotos.com, mutt-motorcycles.com, herald-motorcycles.co.uk,
  malaguti.bike, sym-global.com, macbor.com, horwin.com, ultraviolette.com, revoltmotors.com,
  peugeot-motocycles.com, fantic.com, beta-motor.com, scomadi.com, kymco.com, sym.com.tw,
  hyosungmotors.com, daelim.co.kr, orcal.fr, masaimotors.com. Answers the route but not JSON:
  silence.eco, bimota.it, kymco.eu.
* **Lambretta** — WordPress, 18 documents, every one a scooter *catalogue*. Brochures, no handbook.
* **Motron** — WordPress, 4 documents (AK-434, MCA-4800, RTS-200), all for products the brand no
  longer lists. Real PDFs, but nothing in the catalogue to hang them on; not indexed.
* **Rieju** — `rieju.com/<cc>/manuals` renders the model range client-side: 256 KB of HTML with no
  PDF, no JSON payload and no form action in the document. `/us/manuals` times out entirely.
* **Guessed paths that 404 or time out.** Recorded only so nobody guesses the same strings again —
  these brands are *not* cleared, they just need a real link found first:
  mitsubishi-motors.com.au/.co.nz/.ie `/owners/manuals*`, mazda.co.uk + mazda.com.au
  `/owners/manuals/`, nissan.com.au + nissan.ca `/owners/manuals-guides.html`, suzuki.co.nz
  `/motorcycle/owners-manuals`, hondamotorcycles.com.au `/owners`, kawasaki.eu `/en/owners-manual`,
  lincoln.com `/support/owner-manuals/` (timeout), scomadi.com `/downloads`.

### Next leads, best first

1. **BRP's other ten categories.** `operatorsguides.brp.com/` lists 12: `/P/1` ATV, `/P/2` Evinrude,
   `/P/3` Johnson, `/P/4` Lynx, `/P/5` 3-Wheel, `/P/6` Rotax, `/P/7` Sea-Doo Boats, `/P/8` Sea-Doo
   Watercraft, `/P/9` Side by Side, `/P/10` Ski-Doo, `/P/11` Sea-Doo Pontoons, `/P/14` Motorcycle.
   `americas.py` crawls **two** of them (5 and 14). Same verified host, same `/readguide/<id>`
   `application/pdf` stream, same regexes — this is the single biggest untapped block of free
   official handbooks left, probably four figures.
   **Blocked on one decision, not on work:** `kind` is `"motorcycle" | "car"` end to end —
   `catalog.mjs` writes `k:1` for a car and nothing for anything else, and `parts_catalog.py` only
   has profiles for those two — so a Ski-Doo would be filed as a motorcycle unless a third kind is
   introduced across the registry, the catalog builder and the parts taxonomy. Ask the founder
   before spending the cycle.
2. **Five rows carry an impossible model year**, and each mints a junk vehicle:
   `yamaha-motor-eu-xj6f-201-…`, `…fz8-n-201-…` (×2), `…xj6-n-201-…` (a truncated `2010`) and
   `hondamotopub-com-ahm-trx500fm2-e-5019-en-owner` (a `19YM` file read as year 5019). The fix is
   in `yamaha.py` / `honda_intl.py` — clamp the year to 1900–2032 — not a `.drop.json`, because the
   rows' other years are good.
3. **Regional mirrors, properly.** The guessing in this cycle was wasted requests. Next time find
   the real manual URL from each site's own sitemap or nav before probing: Mitsubishi (AU/NZ/IE —
   `.co.uk` and `.ca` already work, so the HTML pattern is known), Mazda UK/AU, Nissan AU/CA,
   Lincoln (its manuals are very likely on `fordservicecontent.com`, the host `cars_ford.py`
   already fetches — a new car make for almost no new plumbing).
4. **Suzuki, Kawasaki and the Piaggio group are closed**, and each has a module docstring proving
   it (`suzuki_intl.py`, `kawasaki_pdf.py`, `piaggio.py`). 2,060 / 2,398 / 1,068 vehicles will stay
   without a manual until one of those OEMs publishes differently. Do not re-open them on a hunch.

### Housekeeping

`api/tests` is green on everything the registry owns (90 passed, 5 skipped for
`-k "registry or catalog or bike or doctype or car"`). The full suite has 8 pre-existing failures
in `test_offers.py` (one LLM-cost assertion) and `test_voice_agent.py` / `test_voice_elevenlabs.py`
(prompt wording) — other agents' surfaces, untouched by this cycle and failing before it.

---

## Cycle 2 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 53,576 | **53,575** | −1 |
| free English owner PDFs | 24,224 | **24,223** | −1 |
| distinct PDF files | 14,781 | **14,780** | −1 |
| catalog vehicles | 27,765 | **27,761** | −4 |
| …with a `manualUrl` | 13,551 | **13,547** | −4 |

A correctness cycle, not a growth one: the only movement is the five impossible-year rows coming
out. **No new source landed.** Read the gap table and the leads below before starting cycle 3 —
the reason this cycle found nothing is written down there, and it is not bad luck.

### Done

* **Year clamp.** `plausible_years()` in `_http.py` keeps only 1900–2032 and is now applied in
  `yamaha.py` (the EU feed ships a truncated `201` alongside 2011–2016) and `honda_intl.py`
  (Motopub answers `5019` for a `19YM` file). Both portals print these; neither is our parsing.
  `registry.json` and `bikes.json` now contain **zero** impossible years, verified.
* **The five junk rows retracted** — `badyear.drop.json`, plus `--replace yamaha-eu` against a new
  `yamaha-eu.json` fragment so the four Yamaha handbooks come back re-keyed under their real years
  instead of being lost. Only the Honda `TRX500FM2 5019` row is gone for good: its year is
  unknowable from the portal and the file is an ATV guide anyway.
* **Lincoln: checked and not reachable.** `cars_ford.py` has always listed Lincoln in `BRANDS`; the
  reason it yields nothing is that `lincoln.com/support/owner-manuals-details/owner-manuals-library`
  **404s** — Ford's library has 73 nameplates and every one is a Ford. Also checked: every
  `/support/owner-manuals*/<model>/<year>` shape on lincoln.com 404s; `/support/owner-manuals/` is an
  AEM React app whose "Owner Manuals Sitemap" is a client route with no server URL; the
  `support/sitemap.txt` in `robots.txt` returns zero bytes and `sitemap.xml` is a Word-wrapped XML
  blob; and Lincoln slugs on ford.com (`navigator`, `aviator`, `nautilus`) return the empty
  fallback page — 1,198,5xx bytes, **0 documents**, against 1,205,948 bytes and 4 for `mustang`.
  Lincoln PDFs do sit on `fordservicecontent.com`, but nothing public enumerates their names, and
  guessing file names is not enumeration. **Do not re-attempt without a new entry point.**

### The gap table (catalog vehicles with no `manualUrl`) — start cycle 3 from this

Motorcycles, worst first. "same model" = the registry already has a free English PDF for that exact
make+model at a *different* year; "normalise" = it would match if model names were compared with
punctuation and case stripped; "unknown" = no free English PDF exists for that model at any year.

| make | missing | have | same model | normalise | unknown | state of the source |
|---|---|---|---|---|---|---|
| Yamaha | 2,518 | 2,849 | 301 | 284 | 1,933 | library mined out (344 base codes probed, 30 carry bikes) |
| Kawasaki | 2,398 | 64 | 520 | 88 | 1,790 | US KTIVS catalogue is the whole reachable set; rest are flipbooks |
| Suzuki | 2,060 | 34 | 17 | 71 | 1,972 | every national site walked; JP + DE only, UK is VIN |
| Honda | 1,944 | 1,271 | 423 | 136 | 1,385 | 41 Motopub codes, 479 candidates tried |
| Harley-Davidson | 1,375 | 9 | 43 | 0 | 1,332 | per-file guest `viewToken`, no static URL |
| Aprilia | 721 | 0 | 0 | 0 | 721 | `manuals.aprilia.com` is a lead form, PDF arrives by e-mail |
| Triumph | 542 | 816 | 113 | 7 | 422 | 12 of 15 doc types 404 without a subscription |
| Ducati | 415 | 376 | 39 | 2 | 374 | Contentful, headful browser; pre-2015 not published |
| BMW | 359 | 478 | 165 | 40 | 154 | only `BA-SPRACHE` 00/01 mapped |
| Moto Guzzi | 347 | 0 | 0 | 0 | 347 | same lead form as Aprilia |
| GasGas 302 · KTM 280 · Husqvarna 251 · Royal Enfield 184 · QJ 15 · LiveWire 5 | | | 234 | 63 | 720 | |

Cars: Opel 170 (0 have), Land Rover 76, Jaguar 54, Fiat 49, Tesla 43, Peugeot 26, Alfa 23,
Citroën 17, Jeep 12, Lancia 12, Dacia 10, Mercedes 3, DS 2, Volvo 1.

**What the table says, and it is the finding of this cycle:** roughly **11,000 of the 14,214**
missing vehicles are models for which *no free English PDF exists anywhere we can reach* — the six
biggest motorcycle makes are each individually exhausted, with a module docstring proving it. Only
two pools are actually addressable without a new OEM:

* **~1,855 vehicles** whose exact model already has a free English PDF at a neighbouring year.
  These are real gaps in the OEM's own publishing, not ours — do **not** stretch a 2017 handbook
  over a 2015 bike; that is inventing a claim the manufacturer never made.
* **~690 vehicles** that would match on a punctuation-and-case-insensitive comparison
  (`Multistrada V4S` vs `Multistrada V4 S`, `FC250` vs `FC 250`, `R Nine T` vs `R nineT`).
  This one is legitimate and is the **single cheapest four-figure-ish win left**: it needs an alias
  key in `pdf_index()`/`bikes_from_registry()`, not a crawl. It changes `_pick` semantics, so it
  wants a test per make and the founder's nod before it ships.

### Tried this cycle and empty — do not re-walk

* **Lincoln**, in full, as above.
* **Polestar** — `polestar.com/<cc>/manual/<model>/<year>/` is a real, enumerable manual browser
  (20 markets, model + year in the path) but it is an HTML reader like Tesla's. The page's
  "Downloads" tab is a client route: `/uk/manual/polestar-2/2027/downloads` 404s, as do the 2021,
  2025 and 2026 shapes. No PDF found. Worth one more look only if the downloads route is recovered
  from the app bundle.
* **robots/sitemap sweep, 12 car makes** — mg.co.uk, byd.com, polestar.com, rivian.com,
  lucidmotors.com, isuzu.co.uk, tatamotors.com, auto.mahindra.com, vauxhall.co.uk, haval.com.au,
  mgmotor.eu, omoda.com.au: not one owner's-manual PDF in any declared sitemap. Only
  `auto.mahindra.com/customer-awareness/owner-s-manual` exists as a page (200, 272 KB) and it
  renders its list client-side with no PDF in the document.
* **Direct manual paths, 10 car makes** — mg.co.uk, isuzuutes.com.au, vauxhall.co.uk,
  marutisuzuki.com, kgm.co.uk, lucidmotors.com, cars.tatamotors.com, bydauto.co.uk: every
  `/owners/manuals`-shaped path 404s.

**Method note for cycle 3, learned the hard way twice:** probe with the *default* crawler UA, not
`BROWSER_UA`. Akamai on `ford.com`/`fordservicecontent.com` silently drops a Chrome UA, which is
what made Lincoln and several others look unreachable in cycle 1's sweep when they were merely
mis-probed. And stop guessing paths: go `robots.txt` → declared sitemaps → the page, or don't go.

### Next leads, best first

1. **The normalisation alias, ~690 vehicles.** Cheapest real win on the board, no HTTP at all.
   Needs a decision because it changes what `_pick()` may answer with.
2. **New makes that publish English PDFs and have no adapter yet** — none of these were reached
   this cycle and all are unproven: MG, BYD, Polestar (PDF route), Rivian, Lucid, Isuzu, Tata,
   Mahindra, KGM/SsangYong, Great Wall/Haval, Omoda/Jaecoo, Chery, VinFast. Each needs its real
   support URL found first (their public sitemaps do not declare the support tree).
3. **Vauxhall** is the one with a known 170-vehicle payoff: Opel has 468 rows and **zero** free
   English PDFs because the PSA asset hosts serve FR/DE. Vauxhall is Opel in English. Its
   `/owners/vehicle-support/manuals.html` 404s, so the entry point has to be found another way.
4. **Do not re-open** Yamaha, Kawasaki, Suzuki, Honda, Harley-Davidson, Triumph, Aprilia or
   Moto Guzzi on a hunch. Eight docstrings say why, and cycle 2 re-confirmed two of them.

### Cycle 2, second half — the year audit closed out

`docs/registry/BADYEARS.md` (read-only audit by another agent) reported "124 impossible-year rows".
**It was 124 year *values* across 7 rows, and all 7 are genuine** — Harley's historical archive,
1903–1949. Re-measured against the live file: **0 rows** outside 1885 … today + 2, **0** with a
non-four-digit year. Nothing was retracted for a year, and nothing should be.

* **Bound is `1885 … today + 2`** — `FIRST_MODEL_YEAR` + `model_years()` in `_http.py`, computed,
  not hardcoded (`range(1885, 2029)` today). A 1950 floor would have deleted the oldest genuine
  manuals in the database; the top is two model years ahead, which is as far as any OEM publishes.
* **`merge-fragments` now rejects the value, not the row.** `_bad_years()` strips any year outside
  the bound, the row keeps its sane years, and only a row with nothing left is dropped. Every
  offender is printed **per site with the raw value** — `site | [201] | kept | id | fragment` — so
  an upstream typo (Honda `5019`) reads differently from an adapter bug (Yamaha `201`). Proven with
  a poisoned fragment: the `[201, 2011, 2012]` row merged as `[2011, 2012]`, the `[5019]`-only row
  was dropped, and neither was silently discarded.
* **Both live faults fixed at the source.** `yamaha.py::yamaha_eu` filtered on `str(y).isdigit()`
  and let `"201"` become the row id; `honda.py::_region` (the EU/Motopub walk — `honda_intl.py` has
  the same function and got the same fix) took `model_year` verbatim. Both now go through
  `plausible_years()`. Honda's US listing is clamped too.
* **Honda no longer leaks quads.** `NOT_A_MOTORCYCLE` in `honda.py` and `honda_intl.py` drops TRX /
  FourTrax / Rancher / Foreman / Rubicon / Recon / Rincon / Pioneer / Talon / Big Red / MUV / SXS /
  ATC models before they are ever queried, and logs what it skipped. It removes **0 rows today** —
  the only one that had been indexed was the `TRX500FM2 5019` row already retracted — so this is a
  guard against re-introduction on the next crawl, in line with the founder's "motorcycles and cars
  only". Verified: `TRX500FM2  E`, `Pioneer 1000`, `Talon 1000X` skip; `CBR1000RR-R`, `CRF450R`,
  `NC750X` keep.
* Tests: **170 passed, 13 skipped** across registry, catalog, store, cars and API.

Final cycle-2 state: **53,575 rows, 24,223 free English owner PDFs, 14,780 distinct files,
27,761 vehicles, 13,547 with a `manualUrl`**, 0 impossible years, Harley's 7 archive rows intact.

---

## Cycle 3 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 53,575 | **77,993** | +24,418 |
| free English owner PDFs | 24,223 | **24,236** | +13 |
| distinct PDF files | 14,780 | **14,783** | +3 |
| catalog vehicles | 27,761 | **27,776** | +15 |
| …with a `manualUrl` | 13,547 | **15,449** | **+1,902** |

Two things: the matching work below turns manuals the registry already held into offers, and one
new multi-language crawl adds 24,418 rows. **Alias match +301, language fallback +1,586**, and
KTM/Husqvarna/GasGas in every language the portal prints (+15 vehicles, +14,828 distinct PDFs). Motorcycles 9,434 → **10,999**, cars 4,113 →
**4,435**. Roster 594 → 630 KB raw / 84 → 89 KB gzip, still inside the 700 KB budget.
Full suite: **767 passed, 20 skipped, 0 failed.**

### How a vehicle is matched now — three passes, strictly ordered, never mixed

1. **Exact** `slug(make, model, year)`, as before.
2. **Alias** — `alias_key()` rubs the punctuation out of the model name (case, hyphen, space,
   period, slash, `&` → `and`) and keys on make + that + year. What survives is the model's whole
   alphanumeric sequence *in order*, which is why this can only ever merge two spellings and never
   two model families: `CB500F` and `CB500X` stay apart, so do `RS 660` and `RS 457`. The make and
   the year are inside the key, so an alias never reaches across either, and a core shorter than
   three characters gets no key at all (`R` would match far too much).
3. **Language fallback** — only when passes 1 and 2 found *nothing*, the vehicle is offered the
   manufacturer's own handbook in another language, ranked by the vehicle's own market first and
   then `LANG_FALLBACK` (de, fr, es, it, nl, pt, ja, sv, da, no, fi, pl, then the rest).
   `Bike.lang` is stamped with that language and is `None` for English, so a reader is told before
   they open it. `catalog.mjs` carries it into the roster's extra field as `l: {"<year>": lang}`.

`_ingestable()` is unchanged, so **no foreign row is ever queued for unattended ingest** —
`free_owner_manuals()`, `list-free` and `ingest-free` still see English only. `_fetchable()` is the
new, wider predicate the foreign index uses.

Tests: `api/tests/test_registry_match.py`, 24 cases — the alias key both ways, a neighbouring model
and a neighbouring year both refused, English beating a foreign row for the same vehicle, a foreign
row being labelled, the market-before-language order, and paid/non-PDF rows never offered in any
language.

### Language fallback, by language and by make (1,586 vehicles)

| lang | vehicles | | make | vehicles |
|---|---|---|---|---|
| id (Indonesian) | 332 | | Yamaha | 851 |
| th (Thai) | 302 | | Suzuki | 370 |
| de | 240 | | Opel | 170 |
| vi (Vietnamese) | 215 | | Fiat | 49 |
| ja | 177 | | Peugeot | 26 |
| fr | 157 | | Alfa Romeo | 23 |
| it 38 · es 32 · ro 16 · mk 12 · lt 11 · el 10 · uk 9 · ru 7 · pl 6 · nl 5 · da 4 · + 8 more | 123 | | Citroën 17 · QJ 15 · Honda 14 · Triumph 13 · Jeep 12 · Lancia 12 · Dacia 10 · DS 2 · Ducati 1 · Volvo 1 | 97 |

That Opel 170 is the whole Opel gap closed — the PSA asset hosts publish those books in French and
German, and cycle 2's log named it as the one car gap with a known payoff.

### Every alias pairing — 301 vehicles over 146 spellings

| make | catalogue name | registry name | vehicles |
|---|---|---|---|
| BMW | `F650GS` | `F 650 GS` | 1 |
| BMW | `F800 S` | `F 800 S` | 2 |
| BMW | `F800 ST` | `F 800 ST` | 2 |
| BMW | `G650X Challenge` | `G 650 Xchallenge` | 1 |
| BMW | `G650X Country` | `G 650 Xcountry` | 1 |
| BMW | `G650X Moto` | `G 650 Xmoto` | 1 |
| BMW | `K1200 GT` | `K 1200 GT` | 1 |
| BMW | `K1200GT` | `K 1200 GT` | 1 |
| BMW | `K1200LT` | `K 1200 LT` | 1 |
| BMW | `K1200R` | `K 1200 R` | 1 |
| BMW | `K1200S` | `K 1200 S` | 1 |
| BMW | `R 12` | `R 12` | 1 |
| BMW | `R 12 G/S` | `R 12 G/S` | 1 |
| BMW | `R Nine T` | `R nineT` | 4 |
| BMW | `R Nine T Pure` | `R nineT Pure` | 5 |
| BMW | `R Nine T Scrambler` | `R nineT Scrambler` | 1 |
| BMW | `R Ninet Urban GS` | `R nineT Urban G/S` | 5 |
| BMW | `R1200GS` | `R 1200 GS` | 1 |
| BMW | `R1200GS Adventure` | `R 1200 GS Adventure` | 1 |
| BMW | `R1200R` | `R 1200 R` | 1 |
| BMW | `R1200RT` | `R 1200 RT` | 1 |
| BMW | `R1200S` | `R 1200 S` | 1 |
| BMW | `R1200ST` | `R 1200 ST` | 1 |
| Ducati | `Multistrada V4S` | `Multistrada V4 S` | 2 |
| GasGas | `EC300` | `EC 300` | 1 |
| Honda | `CB1100 Ex` | `CB1100EX` | 2 |
| Honda | `CB1100 RS` | `CB1100RS` | 1 |
| Honda | `CBR 250R` | `CBR250R` | 1 |
| Honda | `CBR 300R` | `CBR300R` | 2 |
| Honda | `CBR 300R Abs` | `CBR300R ABS` | 1 |
| Honda | `CMX500A` | `CMX500-A` | 1 |
| Honda | `CRF 50 F` | `CRF50F` | 1 |
| Honda | `CTX 700` | `CTX700` | 2 |
| Honda | `Click 125I` | `Click125i` | 2 |
| Honda | `GL1800 (Goldwing)` | `GL1800 Gold Wing` | 2 |
| Honda | `Montesa Cota 4RT 260` | `Montesa Cota 4RT260` | 1 |
| Honda | `PCX 125` | `PCX125` | 1 |
| Honda | `ST 1300 Abs` | `ST1300 ABS` | 1 |
| Honda | `Trail 125` | `Trail125` | 1 |
| Husqvarna | `FC250` | `FC 250` | 1 |
| Husqvarna | `FC350` | `FC 350` | 1 |
| Husqvarna | `FC450` | `FC 450` | 1 |
| Husqvarna | `TC250` | `TC 250` | 1 |
| Husqvarna | `TC85 17-14` | `TC 85 17/14` | 1 |
| Husqvarna | `TC85 19-16` | `TC 85 19/16` | 1 |
| KTM | `125 Exc Sixdays` | `125 EXC Six Days` | 5 |
| KTM | `250 Exc Sixdays` | `250 EXC Six Days` | 2 |
| KTM | `250 Exc-F Sixdays` | `250 EXC-F Six Days` | 1 |
| KTM | `250 SXF Prado` | `250 SX-F Prado` | 1 |
| KTM | `300 Exc Sixdays` | `300 EXC Six Days` | 1 |
| KTM | `300 Exc Tpi Erzberg Rodeo` | `300 EXC TPI Erzbergrodeo` | 1 |
| KTM | `450 Exc Sixdays` | `450 EXC Six Days` | 2 |
| KTM | `530 Exc Sixdays` | `530 EXC Six Days` | 2 |
| KTM | `990 Superduke R` | `990 Super Duke R` | 1 |
| Triumph | `Bonneville T 100` | `Bonneville T100` | 1 |
| Triumph | `Daytona MOTO2 765` | `Daytona Moto2™ 765` | 1 |
| Triumph | `Scrambler 1200XE` | `Scrambler 1200 XE` | 2 |
| Triumph | `Street Twin Gold Line` | `Street Twin Goldline` | 2 |
| Yamaha | `BWS 125` | `BW'S 125` | 7 |
| Yamaha | `DT 125 Re` | `DT125RE` | 1 |
| Yamaha | `DT 125 X` | `DT125X` | 1 |
| Yamaha | `Delight` | `D'ELIGHT` | 4 |
| Yamaha | `Delight 125` | `D'ELIGHT 125` | 1 |
| Yamaha | `FAZER8` | `FAZER 8` | 3 |
| Yamaha | `FAZER8 Abs` | `FAZER 8 ABS` | 2 |
| Yamaha | `FJR 1300` | `FJR1300` | 5 |
| Yamaha | `FJR 1300 A` | `FJR1300A` | 3 |
| Yamaha | `FJR 1300 Ae` | `FJR1300AE` | 2 |
| Yamaha | `FJR 1300 As` | `FJR1300AS` | 3 |
| Yamaha | `FZ 6` | `FZ6` | 1 |
| Yamaha | `FZ25` | `FZ 25` | 1 |
| Yamaha | `Fascino 125FI` | `FASCINO 125 FI` | 1 |
| Yamaha | `MT-07` | `MT07` | 1 |
| Yamaha | `MT-09 TR` | `MT-09TR` | 2 |
| Yamaha | `MT-09SP` | `MT09 SP` | 1 |
| Yamaha | `MT-10 SP` | `MT-10SP` | 3 |
| Yamaha | `MT-125` | `MT125` | 3 |
| Yamaha | `MT-25` | `MT25` | 4 |
| Yamaha | `MT09TR GT` | `MT-09TRGT` | 1 |
| Yamaha | `NMAX155` | `NMAX 155` | 2 |
| Yamaha | `PW 50` | `PW50` | 1 |
| Yamaha | `SCR 950` | `SCR950` | 1 |
| Yamaha | `SR 400` | `SR400` | 1 |
| Yamaha | `T MAX` | `TMAX` | 2 |
| Yamaha | `TDM 850` | `TDM850` | 2 |
| Yamaha | `TDM 900` | `TDM900` | 8 |
| Yamaha | `TDM 900 - A` | `TDM900A` | 2 |
| Yamaha | `TDM 900A` | `TDM900A` | 2 |
| Yamaha | `TENERE700` | `TENERE 700` | 2 |
| Yamaha | `TRACER 900GT` | `TRACER 900 GT` | 2 |
| Yamaha | `TRACER 9GT` | `TRACER 9 GT` | 1 |
| Yamaha | `TRACER 9GT` | `TRACER 9 GT+` | 1 |
| Yamaha | `TT-R 125` | `TT-R125` | 3 |
| Yamaha | `TT-R 125 E` | `TT-R125E` | 3 |
| Yamaha | `TT-R 125 LW` | `TT-R125LW` | 2 |
| Yamaha | `TT-R 125 Lwe` | `TT-R125LWE` | 1 |
| Yamaha | `TT-R 225` | `TT-R225` | 1 |
| Yamaha | `TT-R 230` | `TT-R230` | 1 |
| Yamaha | `TT-R 250` | `TT-R250` | 1 |
| Yamaha | `TT-R 50 E` | `TT-R50E` | 1 |
| Yamaha | `TT-R 90` | `TT-R90` | 2 |
| Yamaha | `TT-R 90 E` | `TT-R90E` | 3 |
| Yamaha | `TT-R125 - LW` | `TT-R125LW` | 1 |
| Yamaha | `TT-R125 LW E` | `TT-R125LWE` | 1 |
| Yamaha | `TT-R125LW E` | `TT-R125LWE` | 1 |
| Yamaha | `TT-R90 E` | `TT-R90E` | 1 |
| Yamaha | `TTR125LWE` | `TT-R125LWE` | 2 |
| Yamaha | `TW 125` | `TW125` | 5 |
| Yamaha | `TW 200` | `TW200` | 4 |
| Yamaha | `TZR 50` | `TZR50` | 3 |
| Yamaha | `V-Max 1200` | `VMAX 1200` | 1 |
| Yamaha | `WR 125R` | `WR125R` | 1 |
| Yamaha | `WR 125X` | `WR125X` | 1 |
| Yamaha | `WR 250 F` | `WR250F` | 4 |
| Yamaha | `WR 450 F` | `WR450F` | 4 |
| Yamaha | `WR125 X` | `WR125X` | 2 |
| Yamaha | `X-Max 250` | `XMAX 250` | 11 |
| Yamaha | `X-Max 250 Abs` | `XMAX 250 ABS` | 2 |
| Yamaha | `X-Max 300` | `XMAX 300` | 4 |
| Yamaha | `X-Max 400` | `XMAX 400` | 3 |
| Yamaha | `X-Max 400 Abs` | `XMAX 400 ABS` | 1 |
| Yamaha | `XJR 1300` | `XJR1300` | 10 |
| Yamaha | `XJR 1300 SP` | `XJR1300SP` | 2 |
| Yamaha | `XSR 125` | `XSR125` | 1 |
| Yamaha | `XT 350` | `XT350` | 1 |
| Yamaha | `XT 600 E` | `XT600E` | 2 |
| Yamaha | `XT 660 R` | `XT660R` | 2 |
| Yamaha | `XT 660 X` | `XT660X` | 2 |
| Yamaha | `XT 660R` | `XT660R` | 1 |
| Yamaha | `XT 660X` | `XT660X` | 1 |
| Yamaha | `XVS650 A` | `XVS650A` | 1 |
| Yamaha | `YBR 125` | `YBR125` | 4 |
| Yamaha | `YBR 250` | `YBR250` | 1 |
| Yamaha | `YZ 125` | `YZ125` | 5 |
| Yamaha | `YZ 250` | `YZ250` | 5 |
| Yamaha | `YZ 250 F` | `YZ250F` | 5 |
| Yamaha | `YZ 426 F` | `YZ426F` | 1 |
| Yamaha | `YZ 450 F` | `YZ450F` | 4 |
| Yamaha | `YZ 65` | `YZ65` | 1 |
| Yamaha | `YZ 85` | `YZ85` | 5 |
| Yamaha | `YZ 85 LW` | `YZ85LW` | 3 |
| Yamaha | `YZ 85LW` | `YZ85LW` | 2 |
| Yamaha | `YZ450 FX` | `YZ450FX` | 2 |
| Yamaha | `YZ85 LW` | `YZ85LW` | 3 |
| Yamaha | `YZF 600 R` | `YZF600R` | 2 |
| Yamaha | `YZF-R 125` | `YZF-R125` | 2 |

### Handoff: the roster carries `l`, the counter app does not read it yet

`web/store/ttm-catalog.json` rows now ship `extra.l = {"<year>": "de"}` for the 1,586 vehicles whose
offered manual is not in English. `web/counter/js/index-data.js:108` destructures
`{i, o, k}` and ignores `l`, so the offline roster currently shows those vehicles as an ordinary
on-demand manual with no language shown. That file is the counter agent's, not mine — it needs one
line (`const lang = extra?.l?.[year]`) and a badge, so a rider is told the book is in German before
`/manuals/ensure` fetches it. The data side is done and stable; nothing breaks without the change.

### Source added: KTM · Husqvarna · GasGas, every language the portal prints

`pierer.py` has always filtered through `keep_lang()`, so the default `REGISTRY_LANGS=en` kept
2,382 of the rows the one AEM component actually publishes. Re-run with `REGISTRY_LANGS='*'` it
yields **26,784 rows over 14,828 distinct PDFs** — KTM 18,333, Husqvarna 5,893, GasGas 2,558 — in
de 2,389 · en 2,379 · es 2,329 · fr 2,305 · it 1,937 · nl 1,678 · ja 1,644 · cs 1,636 · fi 1,596 ·
pl 1,586 · sv 1,526 · pt 1,493 and more. No adapter change was needed; the row ids already carry
the language, so the 2,379 English rows merged onto themselves and **24,418 rows are new**.
Verified: 8 non-English samples across four languages, 8/8 `%PDF-`.

It moves the vehicle count barely (+15) because KTM prints the same models in every language, so
almost all of it lands on bikes an English manual already covered — but it is 14,828 real official
handbooks the registry can now answer with, and it is what makes the language fallback worth having
for the next make that is *not* English-first.

**The same one-line experiment is owed to every adapter that calls `keep_lang()`:**
`americas.py`, `bmw.py`, `electric.py`, `euro_small.py`, `honda.py`, `honda_intl.py`,
`kawasaki.py`, `royalenfield.py`, `suzuki_intl.py`, `triumph.py`, `triumph_pdf.py`, `yamaha.py`,
`yamaha_intl.py`, `royalalloy.py`. `yamaha_intl.py` and `triumph_pdf.py` were already built with
`'*'`; the rest have not been measured. Run each with `REGISTRY_LANGS='*'` into its own fragment,
verify a sample, merge. Start with **Honda** and **BMW** — both are multi-language portals feeding
the two biggest remaining unknown-model pools.

Caveat for whoever commits this: `api/data/registry-fragments/pierer-langs.json` is **9.2 MB**, and
`registry.json` is now 36.6 MB in the blob. Neither is a problem for the sync, but it is a large
file to put in git — squash or gitignore it if the repo policy says so; the adapter reproduces it
from one command.

### Cycle 3 final state

**77,993 rows · 24,236 free English owner PDFs · 14,783 distinct files · 27,776 vehicles ·
15,449 with a manual (1,601 of them in another language).** 767 tests pass, 0 impossible years,
roster 631 KB raw / 89 KB gzip.

---

## Cycle 4 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 77,993 | **89,141** | +11,148 |
| free English owner PDFs | 24,236 | **24,281** | +45 |
| distinct PDF files | 14,783 | **14,822** | +39 |
| catalog vehicles | 27,776 | **29,638** | +1,862 |
| …with a `manualUrl` | 15,449 | **17,464** | **+2,015** |
| …offered in another language | 1,586 | **3,558** | +1,972 |

Motorcycles 12,383 with a manual (was 11,014), cars 5,081 (was 4,435). **788 tests pass.**

### The `REGISTRY_LANGS='*'` sweep

Every adapter that calls `keep_lang()` was re-run with the gate open, dumped to its own
`langs-<module>.json` fragment, and sample-verified before merging — **32 non-English samples across
7 fragments, 32/32 `%PDF-`, 0 bad.**

| adapter | English-only | all languages | new rows | languages |
|---|---|---|---|---|
| `honda.py` | 1,486 | **4,170** | +2,684 | 21 — ja 906, es 207, ko 197, pl/cs/sk 126 each, pt, it, nl … |
| `yamaha.py` | 4,162 | **6,480** | +2,318 | 16 — de 334, fr 333, it 267, es 263, nl 235, pt 234, sv 189 … |
| `bmw.py` | 946 | **1,512** | +566 | 2 — the `BA-SPRACHE` 00/01 pair really is en + de, nothing was being skipped |
| `royalenfield.py` | 168 | **352** | +184 | 9 — es 58, pt 27, fr 20, it 19, de 19, ja 15, th 14, tr 12 |
| `electric.py` | 38 | **63** | +25 | 6 — NIU prints de/fr/it/es/nl beside English |
| `cars_gm.py` | 2,185 | 2,218 | +39 | 1 — GM's Solr core is `en_US` only; the 39 are new English files |
| `kawasaki.py` | 1,308 | 1,320 | +12 | 2 — 12 Spanish rows, none of them a fetchable PDF |
| `suzuki_intl.py` | 361 | 361 | 0 | 2 — already built with ja + de, nothing gated |
| `euro_small.py` | 94 | 94 | 0 | 1 — Sherco and Benelli publish English only |
| `americas.py` | 582 | **3,775** | +3,193 | 17 — fr 523, es 383, de 330, sv 323, fi 323, ja 279, nl 248, it 238, pt 224 … Polaris/Indian and BRP both print a dozen languages |
| `triumph.py` | — | still crawling when the cycle ended (1 req / 1.8 s over 304 names) | — | **carry to cycle 5**: run it, verify, merge |

`yamaha_intl.py`, `triumph_pdf.py` and `pierer.py` were already built with `'*'`. That closes the
list from cycle 3 except `triumph.py`. `americas.py` landed late and was merged in a second pass —
4/4 verified, and its Can-Am rows prove `operatorsguides.brp.com` serves the non-English guides from
the same `/readguide/<id>` route.

### Source added: Honda Japan — `honda_jp.py`, 2,127 rows over 1,668 PDFs

`honda.co.jp/manual/` redirects to `/ownersmanual/HondaMotor/auto/`, and that page loads its entire
catalogue from one static file, `./data/search.json`: 2 categories, 36 document kinds, **119
nameplates, 668 model years, 1982–2027**. Document urls are
`honda.co.jp/ownersmanual/pdf/auto/<FolderName>/<PDFFileName>` — no session, no VIN, no browser.
815 of the rows are the handbook itself (`オーナーズマニュアル` / `オーナーズガイド`); the rest are the
navigation head unit, quick guides and equipment booklets, each filed under its own `docKind` so
`_pick()` ranks them below a handbook. 8/8 verified `%PDF-`.

The hard part was names: every name in that file is Japanese and `slug()` strips non-ASCII, so all
119 models would have collapsed to one id. `FolderName` is Honda's own romanisation, and the split
is data-driven — the base is the longest other folder that is a strict prefix, widened by the
prefixes two folders share (`acty` from `actytruck`/`actyvan`, `clarity` from `clarityphev`) —
so the family always comes from Honda's list, never from a list I typed. 21 tests in
`api/tests/test_honda_jp.py` cover the naming (including that it stays injective, so no two
nameplates collapse) and the category→`docKind` map.

This is what moved the vehicle count: **+1,856 vehicles**, nearly all Honda Japan nameplates that
existed nowhere in the catalogue before, and Honda is now the biggest beneficiary of the language
fallback at 1,830 vehicles.

### Language fallback now covers 3,558 vehicles

ja 1,579 · id 404 · th 348 · vi 270 · de 268 · fr 159 · ko 114 · es 99 · pl 61 · it 40 · rest 216.
By make: Honda 1,830 · Yamaha 965 · Suzuki 370 · Opel 170 · Fiat 49 · Royal Enfield 27 · Peugeot 26 ·
Alfa Romeo 23 · Citroën 17 · QJ 15.

(A second merge folded `americas.py` in after the numbers above were first taken; the table at the
top of this entry is the final state, and `stats` agrees with it.)

### The roster budget is now the binding constraint

`ttm-catalog.json` blew past its 700 KB limit at 706 KB on the first rebuild. Fixed inside
`catalog.mjs` by packing `extra.l` the way `packMarket` already packs markets: **one bare string
when every on-demand year of a model shares the language**, which is almost always true, and the
per-year map only for a genuinely mixed model. That brought it to **678 KB raw / 98 KB gzip** —
22 KB of headroom, which the next source will eat. Cycle 5 has to either raise `LIMIT` (a call for
the counter agent, since it owns what the browser downloads) or pack the roster harder; `extra.o`,
the on-demand year list, is now the biggest single field and would compress well as a range.

### Next leads, best first

1. **Finish `triumph.py`** with `REGISTRY_LANGS='*'` — the last adapter on the `keep_lang()` list.
   It was still crawling when the cycle ended; `triumph_pdf.py` already indexes every language, so
   expect overlap rather than a large gain, but measure it rather than assume.
2. **Honda Japan motorcycles.** The car portal is `/ownersmanual/HondaMotor/auto/`; the path shape
   says there should be a sibling, and Honda Japan certainly publishes 取扱説明書 for bikes. Checked
   and dead so far: `/ownersmanual/HondaMotor/motorcycle/`, `honda.co.jp/motor-manual/`. The two
   index pages (`/ownersmanual/`, `/ownersmanual/HondaMotor/`) are ~2 KB shells with no category
   list in the document. Find the bike portal's own entry point rather than guessing more folders.
3. **The same `search.json` trick elsewhere.** A portal whose page is a renderer over one static
   JSON is the cheapest possible source, and it is worth looking for the pattern on the other
   Japanese makers (Toyota/Lexus JP, Nissan JP, Mazda JP, Subaru JP) — all four publish Japanese
   owner's manuals and none is indexed.
4. **`kawasaki.py`'s 12 Spanish rows are not fetchable**, which re-confirms that everything outside
   the US KTIVS catalogue is a flipbook. Do not re-open Kawasaki.

---

## Cycle 5 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 89,141 | **99,295** | +10,154 |
| free English owner PDFs | 24,281 | 24,281 | 0 |
| distinct PDF files | 14,822 | **14,822** | 0 |
| catalog vehicles | 29,638 | **30,560** | +922 |
| …with a `manualUrl` | 17,464 | **18,551** | **+1,087** |
| …offered in another language | 3,558 | **4,645** | +1,087 |

Motorcycles 12,383 with a manual, cars 6,168 (was 5,081). **843 tests pass.**
Roster **666 KB raw / 99 KB gzip**, against the new 1,000 KB / 150 KB limits.

### The roster budget, raised and made real

`web/tools/catalog.mjs`: `LIMIT` is now **1,000 KB raw** and a new `GZIP_LIMIT` of **150 KB** —
gzip is what the phone downloads, so it is the one that matters and it is now enforced, not just
printed. Both sizes fail the build and both are printed on every run.

`extra.o` is **range-packed** the same way the `years` field already was: `{r:[from,to]}` when the
on-demand years are a dense run, the list otherwise. That took the roster from 678 KB to 659 KB
before this cycle's rows went in. `index-data.js` expands it with the `yearsOf()` it already had —
one line, and strictly safer than the old `new Set(extra.o)`, because `yearsOf()` returns `[]` for a
malformed value instead of throwing and taking the whole offline roster down.

**Two reader fixes in `web/counter/js/index-data.js` (the counter agent's file, touched minimally
and deliberately):** it now expands a ranged `o`, and it reads a bare-string `l`. Cycle 4 compacted
`l` to a string when a model's on-demand years share a language — the same shorthand `market`
already uses — but the reader only understood the per-year map, so those vehicles were silently
showing as English. Both are one line; the alternative was shipping data the app mis-renders.

### Source added: Toyota and Lexus Japan — `cars_toyota_jp.py`, 1,457 rows over 1,436 PDFs

`toyota.jp/ownersmanual/<slug>/index.html` redirects to `manual.toyota.jp/<slug>/`, which is plain
server-rendered HTML listing every handbook ever published for that model. **91 Toyota slugs come
out of toyota.jp's own sitemaps**, so a new model appears on the next crawl; **Lexus lists its 22
models on `manual.lexus.jp/` itself** and is the same portal in a different skin. Toyota 1,044 rows,
Lexus 413, 1,060 of them the complete handbook, 2009–2027. 10/10 verified `%PDF-` across both.

Rather than matching either site's class names, the parser walks the page as a sequence — heading,
`生産年月：` production-month label, next link — which is the structure both skins share.
**Years come from the production range, not the file name:** `2013年02月～2014年11月` covers model
years 2013 *and* 2014, and an open-ended newest range runs to next model year. Toyota has moved to
an HTML manual plus a printed *abridged* edition, so the newest PDFs say 抜粋版 and are filed
`quickstart`; the older complete books are `owner`, navigation books `infotainment`. 13 tests in
`api/tests/test_cars_toyota_jp.py` cover exactly the year parse and that classification.

The slug splitter honda_jp.py grew in cycle 4 is now shared: `name_families()` and `pretty_slug()`
live in `_http.py` and both Japanese adapters use them (`landcruiserprado` → `Land Cruiser Prado`).

### Triumph, the last `keep_lang()` adapter

`triumph.py` with `REGISTRY_LANGS='*'`: **11,658 rows in 16 languages** (en 1,985, es 1,028,
pt 1,014, fr 937, it 928, de 928, nl 926, ja 921, sv 908, th 555 …) over 920 non-English files,
5/5 verified. Triumph now holds **26,806 rows over 1,118 distinct PDFs**. That closes the
`keep_lang()` list started in cycle 3 — every adapter has been measured.

**Watch this when merging a Triumph fragment.** The auto-`--replace` heuristic fired ("9,673 of
11,658 ids new but no new files") and retracted 16,124 rows, because the scope is
`(triumphtechnicalinformation.com, motorcycle)` — which `triumph_pdf.py` shares. Nothing was lost:
all 17,129 `triumph_pdf.json` rows are in the same merge and were written straight back, verified
id by id afterwards. 165 vehicles did disappear, all of them derived from stale live-crawl rows the
fragment supersedes and none of them carrying a PDF. **Two adapters writing one site into one scope
is a trap**: if either is ever merged without the other in the same run, the missing one's rows are
deleted. Keep `triumph_pdf.json` and `langs-triumph.json` merged together, or give them distinct
sites.

### Checked this cycle and empty — do not re-walk

* **Honda Japan motorcycles do not exist as a portal.** honda.co.jp's sitemap declares exactly two
  manual trees: `/ownersmanual/HondaMotor/auto/` (cars, indexed) and `/ownersmanual/HondaMotor/power/`
  (power equipment — generators and mowers, not vehicles). `/ownersmanual/HondaMotor/motorcycle/`,
  `honda.co.jp/motor-manual/` and `honda.co.jp/motorcycle/` all 404. Japanese Honda bike manuals are
  reachable only through Motopub's `HMJ`-style distributor codes, which `honda.py` already walks.
* **Mazda Japan** — `mazda.co.jp/owner_support/manual/<model>/` exists per model and serves an HTML
  viewer only (`www2.mazda.co.jp/carlife/owner/manual/<model>/…/index.html`). No PDF.
* **Subaru Japan** — `subaru.jp/dealerservice/ownersmanual/<model>/` renders its document list
  client-side; 30 KB of markup with no document url in it.
* **Nissan Japan** and **Suzuki Japan** — robots.txt declares one sitemap each and neither contains
  a manual tree. `suzuki.co.jp/car/support/` 404s to its own error page.
* **Daihatsu** — `manual.daihatsu.co.jp` does not resolve.

### Next leads, best first

1. **The `manual.<brand>.jp` shape is worth one more sweep.** Toyota and Lexus both use it; Daihatsu
   (a Toyota subsidiary whose models are already in the Toyota portal as `pixis*`) does not, but
   Toyota also runs regional manual portals — `manual.toyota.com.au`, `.co.nz`, `.com.tw` are
   untested and would be **English** rather than Japanese, which is the metric that matters most.
2. **Toyota/Lexus JP `infotainment` rows (275) and `supplement` (120)** are indexed but never win a
   `_pick`. Fine as is — noted so nobody mistakes them for missing coverage.
3. **English is where the ceiling is.** Free English owner PDFs have not moved in two cycles
   (24,281): every source found since is non-English. The remaining English-shaped ideas are the
   regional Toyota portals above, Lincoln (dead, cycle 2), and the car makes with no adapter at all
   (MG, BYD, Polestar, Rivian, Lucid, Isuzu, Tata, Mahindra, KGM, Haval, Omoda, Chery, VinFast) —
   none of which declares a support tree in its public sitemap, so each needs its real manual URL
   found by hand before probing.

---

## Cycle 6 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 99,295 | **99,313** | +18 |
| **free English owner PDFs** | 24,281 | **24,299** | **+18** |
| distinct PDF files | 14,822 | **14,840** | +18 |
| catalog vehicles | 30,560 | **30,578** | +18 |
| …with a `manualUrl` | 18,551 | **18,569** | +18 |

A small cycle by row count and the first movement in the English number for three cycles. Roster
**667 KB raw / 99 KB gzip**. `index-data.js` was **not** touched — the roster format is unchanged.

### The Triumph trap is now impossible — the guard is in the tool

`tools/registry.py` builds a `(site, kind) -> fragments that write it` map before any retraction:

* **The auto-`--replace` heuristic stands down on a shared scope.** It is a guess, and a guess must
  never be the thing that deletes a sibling adapter's rows. It now prints
  `NOT replacing, it shares a scope (triumphtechnicalinformation.com with triumph_pdf)` and moves on.
* **An explicit `--replace` on a shared scope keeps the union.** What survives is every id from
  every fragment that writes that scope, so `--replace langs-triumph` now reports
  `26,806 row(s) own 1 site/kind scope(s), 0 superseded (scope shared with triumph_pdf, all present)`
  instead of retracting 16,124.
* **A held-back co-owner refuses the scope outright.** `--skip` now still *reads* the skipped
  fragment, purely to learn what it covers, so
  `--replace langs-triumph --skip triumph_pdf` prints `refusing scope
  triumphtechnicalinformation.com (motorcycle) - also written by triumph_pdf, which this merge
  skipped` and retracts nothing.
* A scope one fragment owns alone still replaces exactly as before.

Four cases in `api/tests/test_merge_scopes.py` pin all four behaviours, including a reconstruction
of the exact cycle-5 shape (ten files re-keyed, all ids new, a co-owner present).

### Source added: MG Australia — `cars_mg.py`, 18 English handbooks

`mgmotor.com.au/owners-manuals` links the whole current range as English PDFs on the site's own
`/brochures/` path (the folder name is MG's; the files are `*_Owners_Handbook.pdf`). 18/18 verified
`%PDF-`. 82nd make, and the first new **English** source since cycle 1.

Six carry a model year in the file name. **The other twelve carry no date and MG's server sends no
`Last-Modified` at all** — checked with HEAD and with a ranged GET, the header simply is not there —
so those rows are dated to the year they were crawled and titled "(current edition)" rather than
given a year they do not have. It is an approximation and it is labelled as one; re-crawling next
year adds a row rather than moving one, which is right, because MG will have reissued by then.

### Checked this cycle and empty — do not re-walk

* **No `manual.toyota.<tld>` siblings exist.** `.com.au`, `.co.nz`, `.com.tw`, `.ca`, `.com`,
  `.co.uk`, `.co.th` and `manual.lexus.com.au` all fail to resolve. The Japanese portal is the only
  one of its kind.
* **Toyota's national sites** — `toyota.com.au`, `.co.nz`, `.ca`, `.co.za` declare sitemaps with no
  manual tree (all 1,800+ "owner"-ish urls are news and dealer pages). `toyota.co.uk/customer/manuals`
  is the pan-European portal (`toyota-europe.com/customer/manuals`, and one host per market:
  `de.toyota.ch`, `kk.toyotakz.com`, `toyota-bishkek.kg`, …) and it renders client-side: 246 KB of
  markup with **no PDF, no JSON and no document path** in it. It is a model/VIN picker, not a file list.
* **BYD Australia's `atto3manual`** is a Microsoft Power Virtual Agents chatbot
  (`web.powerva.microsoft.com/.../bydAustraliaAtto3Owner`), not a document.
* **No manual tree in the sitemap**: `mg.co.uk`, `mgmotor.co.uk`, `mghybridplus.com`,
  `isuzu.co.uk`, `isuzuutes.com.au`, `kgm.co.uk`, `vinfastauto.us`, `cheryauto.com.au`,
  `gwm.com.au`, `gwmhaval.com.au` (188 hits, every one a video thumbnail), `omodajaecoo.com.au`
  (warranty and service terms only), `ldvautomotive.com.au`, `polestar.com` (re-confirmed).
* **Motorcycle mirrors**: `hondamotorcycles.com.au` and `kawasaki.com.au` declare a sitemap with no
  manual tree; `triumphmotorcycles.co.uk/owners` is battery and servicing advice;
  `bikes.suzuki.co.uk/owners` is the VIN lookup `suzuki_intl.py` already documents.

### A real problem this growth has caused: the test suite now times out

`api/data/registry.json` is **46 MB**, and `conftest.py` copies the whole of `api/data` into a temp
dir for every run while `FileStore.registry()` re-reads and re-validates all 99,313 rows on **every
call**. Two tests are now at the edge of the 120 s per-test timeout in `pytest.ini`:

    61.33s  test_bughunt_ingest_guard.py::test_known_pdf_hosts_reads_the_registry_and_the_verified_list
    55.07s  test_bughunt_api.py::test_parts_catalog_route_still_answers

`python -m pytest api/tests -q` **times out** at the committed 120 s; with `--timeout=300` the
suite is green — **849 passed, 20 skipped in 15 min 02 s**.
This is mine in the sense that my growth caused it, but the fix is not in anything I own: it is
either a memoised `FileStore.registry()` (`app/store.py`) or a trimmed fixture in `api/tests/conftest.py`.
**Please route it** — every future cycle makes it worse, and the next agent to run the suite with the
committed `pytest.ini` will see a timeout rather than a failure and may misread it as a broken test.
(One unrelated flake seen once under `-p no:randomly -x`:
`test_bughunt_ondemand.py::test_a_replica_that_died_does_not_hold_the_manual`; that file passes 43/43
in isolation, so it is an ordering interaction in the bug-hunt agent's own tests, not a registry change.)

### Next leads, best first

1. **English is genuinely close to its ceiling from national OEM sites.** Of 25 hosts probed this
   cycle, one published files. The pattern that still works is *the importer, not the maker*: MG's
   Australian importer publishes what MG's British one does not. Worth one cycle of exactly that —
   Australian and New Zealand importers of brands whose home site is gated (Isuzu Ute, LDV, GWM,
   Chery, Omoda, Mitsubishi, Ssangyong/KGM, Foton, Ram AU), probed at `<brand>.com.au/owners*`.
2. **Toyota Europe's `/customer/manuals`** is one client-side call away from being a source. If a
   later cycle can read its XHR (model list -> document list), it would be English for GB/IE and a
   dozen other markets. Needs a browser or the app bundle read, not a plain GET.
3. **The language fallback is where the coverage is**, and it is far from exhausted: 4,645 vehicles
   are served by it today, and every non-English portal found so far came from a make we already had.

---

## Cycle 7 — 2026-09-20

| | before | after | Δ |
|---|---|---|---|
| registry rows | 99,313 | 99,313 | 0 |
| free English owner PDFs | 24,299 | 24,299 | 0 |
| catalog vehicles | 30,578 | 30,578 | 0 |
| …with a `manualUrl` | 18,569 | 18,569 | 0 |

No rows added. The cycle's work is the suite fix and three sources investigated to the bottom —
two of which are now closed for good, with the evidence written down.

### The suite: `FileStore.registry()` is memoised on the file's (mtime_ns, size)

`registry.json` is 40 MB / 99,313 rows: **0.06 s to read, 1.8 s to `json.loads`, 3.0 s to validate**,
and the API and the tests call it many times per process. `FileStore` now caches the validated rows
against the file's own `(st_mtime_ns, st_size)`, so any writer — `put_registry`, the merge tool's
wholesale rewrite, another process — invalidates it without knowing the cache exists. A missing or
unreadable file still returns `[]`. `BlobStore` is untouched.

    first call 4.34s -> second 0.002s -> after `os.utime` re-read (correctly)
    test_known_pdf_hosts_reads_the_registry_and_the_verified_list   61.3s -> 7.3s

**The rows are now shared between callers, so nothing may mutate one in place.** Only two places
ever did — `registry.merge_ua()` (stamps `docKind`/`needsUa`) and the merge tool's `--restamp` —
and the merge tool now takes `[e.model_copy() for e in store.registry()]` before stamping. That
contract is written into the method's docstring, because a future in-place edit would silently
change what every later reader in the process sees.

**The suite is green at the committed limit: 849 passed, 20 skipped, no `--timeout` override.**

**Still slow, and none of it registry-bound** — `bikes()` is 0.73 s and `registry()` is now free, so
what is left is each route's own work. Measured on a *loaded* box (headless Chrome was running for
the Toyota investigation on the same machine), worst first:

    116.7s  test_main.py::test_manuals_list                                  <- 3 s under the limit
     97.7s  test_bughunt_ondemand.py::test_head_answers_wherever_get_does[/cost]
     80.9s  test_bughunt_store.py::test_cost_route_reports_the_largest_manual
     75.0s  test_dropbox_sync.py::test_pagination_follows_has_more
     51.3s  test_bughunt_api.py::test_parts_catalog_route_still_answers

These are `app/main.py`, `app/ondemand.py` and the Dropbox sync — other agents' surfaces, slow for
their own reasons and slow before this cycle too. `test_manuals_list` finishing 3 s inside the limit
is not a margin anybody should rely on. **Please route it**; the registry side of the problem is
fixed and will not be what breaks the suite next.

### Toyota / Lexus Europe: found, fully mapped, and **HTML only** — closed

`toyota.co.uk/customer/manuals` embeds an iframe, `customerportal.tweddle-aws.eu` (Tweddle Group,
Toyota Motor Europe's publisher). Driven through headless Chrome, the whole chain came out, and
**every step answers plain httpx with no token, no cookie and no browser**:

    GET https://diva-api.tweddle.app/pubhub/info/products?
        -> 885 products {brand, model, modelType, year, ngtdModelId} - Toyota 495, Lexus 390,
           48 models, 2006-2026. Verified from httpx directly.
    GET /_next/data/<BUILD_ID>/modelTypes.json?brand=&model=            -> the model types
    GET /_next/data/<BUILD_ID>/generations.json?...&ngtdModelId=136     -> {id, yearFrom, yearTo, count}
    GET https://diva-api.tweddle.app/languages/model/<m>/modelType/<t>/from/<y>/to/<y>
        -> 25 languages, English among them
    GET /_next/data/<BUILD_ID>/publications.json?...&generationId=528&language=en
        -> {_id, partNumber, publicationType: "UG", language, year, contents.ditaId}  (9 for one
           Corolla generation in English alone)

And then it stops: the document is **DITA, not a PDF**. "Browse" opens
`/content?id=<ditaId>` and fetches `diva-api.tweddle.app/pubhub/publications/<ditaId>/content`,
which returns the manual as JSON topics. There is no download link anywhere in the reader, no
`.pdf` response on any call, and no print route.

So this is the Tesla / JLR situation at European scale: real, free, official, English — and not a
file. Indexing it would add tens of thousands of rows that `_is_pdf()` rejects, which means **zero
vehicles gained** and a registry that is already slowing the suite. **Not indexed, deliberately.**
Re-open it only if the product ever learns to ingest a DITA/HTML manual — in which case the recipe
above is complete and needs no browser.

### AU/NZ importers, motorcycles: empty

Sitemaps declared, no manual tree in any of them: `cfmoto.com.au`, `zontes.com.au`, `qjmotor.com.au`,
`vogemoto.com.au`, `kovemoto.com.au`, `symaustralia.com.au`, `kymco.com.au`, `benelli.com.au`,
`motoguzzi.com.au`, `beta-australia.com.au`, `shercoaustralia.com.au`. Only `royalenfield.com.au`
has document pages (WordPress `attachment/download-*`), and Royal Enfield is already indexed at 352
rows in 9 languages, so there is nothing there either. The cycle-6 hope that the *importer* is
looser than the *maker* held for MG Australia and holds for nobody else tried so far.

### Next leads, best first

1. **The product decision that unlocks the biggest English source left.** Toyota/Lexus Europe is
   ~885 products × 25 languages of official manuals that exist only as HTML. Same for Tesla,
   Mercedes MY2025+, JLR from MY2016, Mazda JP, Subaru JP, Polestar. If `/ingest` could take an
   HTML manual, that single change is worth more than every remaining PDF hunt combined. Worth
   putting to the founder as a product question, not a registry one.
2. **Non-English portals remain the only growing seam.** Every source found since cycle 4 has been
   non-English, and the language fallback now serves 4,645 vehicles. Korea (Hyundai/Kia/Genesis
   home sites), China (FAW, Dongfeng, Changan, Geely), Brazil (VW, Fiat, GM do Brasil) and India
   (Maruti, Tata) are all unexplored and all publish PDFs in their own language.
3. **Watch the registry's size.** 40 MB and 99k rows is already the suite's biggest cost even with
   the cache; a Chinese or Brazilian portal could double it again. Worth asking whether rows that
   can never be fetched (`_is_pdf() == False`, 60k+ of them today) should live in a separate file
   from the ones that can.

---

## Cycle 8 — 2026-09-20

Two pieces of work: the catalogue stopped minting vehicles out of document titles, and the registry
learned to **print an online-only manual into a PDF we can ingest**.

### 192 vehicles that were really documents, removed

`bikes.json` carried 192 "vehicles" whose model name was a document title — `Parts Listing`,
`Shop Dope/Service Bulletins`, `The Legend Begins`, `Universal Motorcycle Quick Start Guide`,
`Owners Handbook Warranty`. They headed every gap list and read as garbage in search.

* **Harley-Davidson 164 · Indian 13 · Voge 6 · Kove 5 · Kymco 2 · Hyundai 2.** None had ever been
  ingested. **The registry rows are untouched** — they are real documents and stay exactly where
  they are; only the derivation is refused.
* `registry.is_document_title()` / `names_a_vehicle()` match **phrases, never single words**, so a
  real model is safe: `Road Glide`, `Sport Glide`, `Street Glide Special` and `Tri Glide Ultra`
  survive because the phrase looked for is "user guide", and "spec" alone is not enough — it has to
  be "spec book". The guard sits in `bikes_from_registry()` *and* in the index builder, because the
  old code also re-admitted the junk vehicle through `pdf_index` on the next pass.
* `python -m tools.registry prune-vehicles [--dry-run]` removed the existing ones once and reports
  what it would touch; anything already ingested is kept and named rather than deleted.
* 27 cases in `api/tests/test_document_titles.py`, including twelve real models that must survive.

Catalog **30,578 → 30,386 vehicles**, of which 28 had been carrying a `manualUrl`.

### Rendering online-only manuals: `tools/render_html_manual.py` + `tools/render_pdf.mjs`

The pipeline stays PDF-only; the manual becomes a PDF. For one manual the tool walks the
publisher's own table of contents, fetches each section's HTML from the publisher's own CDN,
assembles it in the publisher's order, and has headless Chrome print A4:

* a first page with make, model, year, language, the **official source URL** and the fetch date;
* one printed page per section (`page-break-before`), the publisher's figures and tables at print width;
* a footer on **every** page: `Official source: <url> · fetched <date>` plus `page/total`;
* nothing rewritten — the words and pictures are the manufacturer's, only the pagination is ours;
* nothing behind a login, and ≤ 2 req/s per host.

**Verified, not assumed.** `verify()` opens the result in PyMuPDF and rejects anything under 8
pages or under 120 characters of text per page, because an ingest that cannot read the text layer
is worthless. First render: **Lexus CT 200h 2014, 173 sections → 254 pages, 878 chars/page**, cover
and footer correct, figures present.

Rows point at **our** blob (`pdf/rendered/<make>/<model>-<year>-<lang>.pdf`) with `source` = the
official page and the new `rendered: true` flag (both fields added additively to `RegistryEntry`),
so nothing ever pretends this is the manufacturer's own file.

Two things worth knowing before the next site:

* **Chrome's `protocolTimeout` is 180 s** and a 250-page manual blows straight through it —
  `Page.printToPDF timed out` is what that looks like. The helper sets 30 minutes, and waits on
  `load` plus an explicit image-settle rather than `networkidle0`, which never fires on a page
  pulling hundreds of CDN figures.
* **The files are big: ~49 MB for 254 pages.** The weight is the publisher's PNG figures, and
  re-saving with `garbage=4, deflate_images=True` buys **0.2 %** (49.23 → 49.15 MB) because they
  are already compressed. Cutting it needs real downsampling or JPEG recoding, which risks the
  legibility of wiring and dashboard diagrams — worth doing deliberately, not as a side effect.
  Budget ~50 MB per rendered manual until then.

### Recipe: Toyota & Lexus Europe (`--site tweddle`)

    GET https://diva-api.tweddle.app/publications?filters={"language":"en","publicationType":"UG"}&limit=100&page=N
        -> every English User Guide. `limit` caps at 100 and `page` is 1-based and is the ONLY
           pager it honours: skip, offset, start, from and pageNumber all answer with nothing.
           566 publications, of which Toyota and Lexus are 457 after de-duplicating to one per
           (make, model, year) - the rest are other Tweddle customers (Kenworth trucks) and are
           skipped rather than mislabelled.
    GET https://diva-api.tweddle.app/pubhub/publications/<ditaId>/content
        -> {publications:[{contents:[...]}], folders:[119], topics:[202]}; walking
           publications[0].contents depth-first through each node's own `contents` is the manual's
           order, and every node carries bodyHtml.url - a public S3 file needing no token.

Render order is **breadth-first across nameplates, newest year first**: every render is one row and
therefore one vehicle, so reaching the most *models* soonest is what a time-boxed cycle should buy.

### Numbers

| | before | after | Δ |
|---|---|---|---|
| registry rows | 99,313 | **99,316** | +3 |
| **free English owner PDFs** | 24,299 | **24,302** | **+3** |
| distinct PDF files | 14,840 | **14,843** | +3 |
| catalog vehicles | 30,578 | **30,389** | −192 documents, +3 rendered |
| …with a `manualUrl` | 18,569 | **18,544** | −28 junk, +3 rendered |

**876 tests pass in 44 s** — down from 15–21 minutes, which is cycle 7's `registry()` memoisation
finally showing its full effect now that nothing else re-reads the file per call.

Three manuals is what fitted: **each render takes 4–6 minutes** (fetch ~200 CDN sections, lay out,
print 250–450 pages), so 457 of them is roughly two days of wall clock, not one cycle. The first
three are Lexus CT 200h 2014 (254 pp), CT 200h 2020 (340 pp) and ES 200 2022 (445 pp), all uploaded
and re-verified as `%PDF-` **from the public blob url**, not just on disk.

**Resuming is the normal case:** `render --site tweddle --all --upload --max-minutes N` reuses every
PDF already on disk (and re-uploads it, idempotently) and carries on from where it stopped;
`--only-rendered` uploads and indexes what exists without rendering anything new. Each render is one
row and therefore one vehicle, so the remaining 454 are 454 vehicles, English, at ~5 minutes each.

The cache lives in `api/data/uploads/rendered/` on purpose: the test harness copies `api/data` for
every run and ignores `uploads`, and a 50 MB-per-manual cache has no business in git. The blob is
the real home.

---

## Cycle 9 — 2026-09-20

The renderer now owns most of the cycle. Two changes to it, one finding about ordering, and a
structure check on the other four HTML-only publishers.

### Renderer: parallel Chrome, and an ordering that is measured rather than assumed

* **`--workers N` runs N Chrome renders at once**, each with its own browser. The HTTP side still
  goes through the one global 2 req/s throttle, so more workers never means hammering the publisher
  harder — only more of the waiting overlapped. Two workers ran clean, no failures.
* **`by_coverage()` orders by how many catalog vehicles a render would actually serve**: existing
  vehicles that have no manual today and that this render would give one to, matched the way
  `_pick` matches — exact id or alias. **For Toyota/Lexus Europe the answer is zero for all 457**,
  and the tool says so on every run (`0 of 457 manual(s) would fill a catalog vehicle that has
  none`). The European model-type names — `Corolla Hybrid Hatchback`, `ES 350h`, `NX 450h+` — are
  not the US catalogue's names, so **every render creates a new vehicle rather than filling an
  empty one**. That makes the yield exactly one vehicle per render, and the tie-break that matters
  is breadth across nameplates, newest year first, which is what it falls through to. The ordering
  is still computed, because the next site may well be the other way round.

### Are Polestar, Tesla, Mercedes and JLR renderable the same way? Checked.

Three things have to be true: a list of (model, year, manual) without a VIN or a login, a
machine-readable table of contents, and each section's body as fetchable HTML. Tweddle has all
three. The others:

| | list | contents | bodies | verdict |
|---|---|---|---|---|
| **Polestar** | partly | yes | **no** | renderable, but ~10× the cost — see below |
| **Tesla** | — | — | — | **unreachable from this network**: `tesla.com` itself answers nothing, root included, to the default and the browser UA alike. Not a path problem and not assessable here. The 19 stale Tesla rows in the registry point at URLs that no longer answer. |
| **Mercedes** | — | — | — | same: `mercedes-benz.com/en/owners/` does not answer from here at all. |
| **JLR** | no | no | no | `ownerinfo.jaguar.com` / `ownerinfo.landrover.com` are 25 KB SPA shells, as cycle 2 found; every document route 302s to the root. |

**Polestar in detail**, because it is the one that could be done. `polestar.com/uk/manual/<model>/<year>/`
answers 200 for polestar-2 across 2024/2026/2027 and lists **21 topic ids** per year; a topic page
`/uk/manual/polestar-2/2027/<32-hex>/` also answers 200 — but **only to a browser User-Agent**, and
what comes back is 251 KB of which the manual body is *not* part: the served HTML is navigation
chrome and the topic text is drawn client-side. So Polestar needs a full Chrome navigation **per
topic** (21+ per manual, against one API call for a whole Tweddle manual) plus chrome-stripping
before printing, for a range of roughly 12–20 manuals (Polestar 2/3/4/5 × a few years), and
polestar-3/4/5 expose only one topic id to a plain fetch, so their structure is not even confirmed.
**Low priority**: the same hour spent on Tweddle buys ~12 manuals with no new machinery.

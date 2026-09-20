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

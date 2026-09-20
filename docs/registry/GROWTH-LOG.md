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

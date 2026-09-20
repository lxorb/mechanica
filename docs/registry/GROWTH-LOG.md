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

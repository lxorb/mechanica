# Ingest findings — for the ingest / registry owner

Checked 2026-09-20 against the live API (27 manuals at the time of the run).
Method: `GET /manuals`, `GET /manuals/{id}`, 5 rider questions per manual through `POST /ask`,
plus the reader rendered in headless Chrome at 390×844. Nothing here was fixed by QA.

## Blocking for a demo

| # | manual(s) | what | why it matters |
|---|---|---|---|
| 1 | `bmw-r-12-g-s-2025` (+ `bmw-r-12-g-s-2026`, `bmw-r-12-2024`) | a **second bike row** for a make/model/year that already has one: `bmw-r12gs-2025` carries `manualId`, `bmw-r-12-g-s-2025` carries `null`. Both are in `/catalog`. | This is the demo bike. The UI resolved the later row and offered **Add manual** instead of opening the R 12 G/S. QA hardened the client (`src/data/index.ts`), but the registry should not mint a second id for an indexed bike. |
| 2 | `kawasaki-ninja-500-2025-us-om`, `kawasaki-versys-1100-2026-us-om`, `kawasaki-vulcan-s-2025-us-om`, `kawasaki-z900rs-2025-us-om` | `title` is **`WARNING`** | The reader header is the cover title (product rule 3). Four manuals read "WARNING" over every page. |
| 3 | `royal-enfield-classic-350-2025-us-om` | `title` is **`HF4"64?<9BEA<4`** — symbol-encoded font read verbatim | Garbage in the header; also means the cover text layer is not decodable, so anything else read from that page is suspect. |
| 4 | `royal-enfield-int-650-2025-us-om` | `outline` is **empty**, `title` is `FOREWORD` | The reader's no-match state is the outline list. QA added a section-list fallback so it is not a blank screen, but the trail line stays empty and `api/tests/test_models.py` had to be relaxed for it. |

## Worth fixing before more manuals land

| # | manual(s) | what |
|---|---|---|
| 5 | `honda-africa-twin-2025-us-om`, `honda-cb500f-2025-us-om`, `honda-cbr650r-2023-us-om`, `honda-grom-2025-us-om`, `honda-rebel-500-2025-us-om` | `title` is `OWNER'S MANUAL` for all five — no model, no year. Five different bikes with an identical reader header. Honda prints the model on the cover; the extractor is taking the wrong line. |
| 6 | `bmw-f-900-r-2025-eu-om` | duplicate section `Battery of the radio-operated key is empty or loss of the radio-operated key` (twice), and `Adjusting compression-stage damping for front wheel without low-slungOE` — the `OE` suffix is glued to the previous word. |
| 7 | `honda-rebel-500-2025-us-om`, `honda-grom-2025-us-om`, `honda-cbr650r-2023-us-om`, `honda-africa-twin-2025-us-om`, `yamaha-tenere-700-2025-eu-om` | 1–2 near-duplicate titles inside the **first 16 sections**, i.e. inside the Ask chip list: e.g. Rebel `Drive chain` p.60 and `Drive Chain` p.67. Two chips, one job. |
| 8 | `honda-africa-twin-2025-us-om` (116 chars), `honda-cbr650r-2023-us-om` (118), `honda-grom-2025-us-om` (104), `bmw-r-12-ninet-2025-eu-om` (94) | longest section titles run 94–118 chars, so an Ask row wraps to 3–4 lines at 390 px. Not broken, but the chip list stops reading as a list. |
| 9 | every manual | `p. N` in the reader is the **PDF page index**, not the folio printed on the sheet: KTM PDF p.77 prints `75`, Honda Rebel PDF p.66 prints `62`. The demo line is "that is KTM's page 77" while the paper says 75. Needs a printed-label map in the `Manual` contract (or `getPageLabels()` where the PDF has one) — a contract change, not a UI change. |
| 10 | `/catalog` | 17,800 bikes, **2.5 MB** uncompressed, fetched on every cold app open (2.3 s on a wired line; the client aborts at 10 s). QA added gzip to `api/app/main.py` (2.5 MB → 207 KB) — **it ships only on the next API deploy**. |

## What is good (checked, no action)

- **Highlights**: 0 out-of-bounds rects across all 27 manuals (`0 ≤ x,y`, `x+w ≤ 1`, `y+h ≤ 1`), 0 highlights outside their section's page range, 0 sections with no highlights, 0 broken page ranges. Rendered: no mark falls outside the paper sheet on any screen checked.
- **Ask chips**: rider tasks first on every auto-ingested manual checked — `bmw-f-900-r` opens on oil level / topping up / chain / ENGINE OIL; `honda-rebel-500` on Engine Oil / Selecting the Engine Oil / Checking the Engine Oil; `husqvarna-svartpilen-401` on engine oil level / oil change / chain tension. Chapter grouping is correct and runs 3–7 groups in the first 16.
- **5 rider questions × the 3 named manuals** (`chain is loose`, `how much oil`, `I need to replace the front brake pads`, `tyre pressure`, `battery is dead`): every one landed on a plausible printed section with markers on the right lines. Examples: F 900 R → `Check the chain tension` p.190, `ENGINE OIL` p.232, `Checking brake pad thickness, front brakes` p.171, `Checking tyre pressures` p.177, `Recharging connected battery` p.195. Rebel 500 → p.87, p.66, p.84, p.69, `Battery Goes Dead` p.100. Svartpilen 401 → p.80, p.133, p.87, p.98, `Charging the 12-V battery` p.102.
- **Titles and trail render without overflow** at 390 px on every manual checked (after the QA header fix; see REPORT.md).

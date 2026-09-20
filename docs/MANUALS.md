# The manual registry

**99,295 rows, 40 portal adapters, not one PDF copied at crawl time.** A `RegistryEntry` stores where a
manual lives — make, model, years, market, language, type, access, URL — and nothing else.
Counts measured 2026-09-20, growth cycle 1 (`cd api && .venv/Scripts/python -m tools.registry stats`, `GET /api/registry`).
The same counts, with the exact definition behind each one, are generated into `docs/pitches/numbers.md`
by `api/tools/pitch_numbers.py --live` — re-run it rather than editing a number here by hand.

| | count |
|---|---|
| registry rows | **99,295** across 88 portals, 81 makes |
| free owner's manuals | 85,761 rows, 49 languages — **27,184 in English** |
| …English **and** a directly fetchable PDF, so `/ingest` can take it unattended | **24,281** |
| …distinct PDF files behind those rows (one file often covers several years) | **14,822** |
| catalog vehicles derived from the registry | **30,560**, of which **18,551** have a free manual — 4,645 of those in the maker's own non-English printing |
| already ingested and warm in Azure Blob | **535 manuals** (`GET /api/manuals`) |

## Where the free manuals come from

One adapter per portal in `api/app/registry/`; the docstring of each file records what broke and why.
"PDFs" = rows that are English, free, and a URL `free_owner_manuals()` will queue unattended.

| make | rows | PDFs | host | note |
|---|---|---|---|---|
| Yamaha | 6,807 | 6,806 | `library.ymcapps.net`, `cdn2.yamaha-motor.eu` | the Owner's Manual Library (POST JSON, 4 calls deep) plus the EU one-call API |
| Triumph | 18,109 | 2,485 | `api.triumphtechnicalinformation.com` | throttled to 1 req / 1.8 s (20 per 10 s limit); most handbooks are viewer pages, not direct PDFs |
| Honda | 1,756 | 1,670 | `cdn.powersports.honda.com`, `hondamotopub.com` | US Sitecore API needs a CSRF token and a Googlebot UA (Akamai); Motopub is **41 distributor codes**, four of them found only by trying 479 candidates |
| KTM · Husqvarna · GasGas | 2,382 | 2,379 | `azwecdnepstoragewebsiteuploads.azureedge.net` | one AEM component, three sites; PDFs on the KTM CDN |
| BMW | 947 | 946 | `manuals.bmw-motorrad.com` | one `Nav.xml` lists every rider's manual. Only `BA-SPRACHE` 00/01 are mapped — the rest are skipped, not guessed |
| Ducati | 383 | 381 | `assets.ctfassets.net` | PDFs are public on Contentful; the page naming them is Akamai-fingerprinted — 403 to httpx **and** to headless Chrome, 200 to headful. The adapter drives a real browser over CDP |
| Indian · Victory | 533 | 527 | `cdn.polarisportal.com` | Cloudflare challenge passed by loading the owner's page first and reusing the cookie jar |
| Hero · TVS · Bajaj | 257 | 257 | own sites | Hero ships a JSON model behind its AEM page; the other two just link the PDFs |
| Royal Enfield | 169 | 168 | `royalenfield.com` | PDF path sits on the download button; no model year published |
| Kawasaki | 1,385 | 152 | `pws.ktivs.net` | Inertia JSON. **Do not send `Accept: application/json`** — that hits the API guard and 401s. Needs `X-Inertia` + a version header |
| Can-Am | 128 | 128 | `operatorsguides.brp.com` | `/readguide/<id>` streams `application/pdf` from a URL with no `.pdf` — hence `PDF_HOSTS` |
| MV Agusta | 239 | 126 | `mva-files.s3.amazonaws.com` | |
| Zero | 134 | 85 | `zeromotorcycles.learnupon.com` | an LMS, not a portal |
| Sherco | 86 | 81 | `sherco.com` | owner's and workshop manuals side by side; the type is read off the file name |
| Suzuki | 451 | 34 | `www1.suzuki.co.jp`, `motorrad.suzuki.de` | mostly Japanese and German market handbooks, so excluded from unattended English ingest |
| Harley-Davidson | 5,156 | 9 | `serviceinfo.harley-davidson.com` | the SIP archive lists **5,177 owner's manuals back to the 1980s**; `/api/documents/{id}` hands out a guest `viewToken` per file, so almost none are a static URL |
| Kove · Sinnis · Cake · Kymco · Vmoto · Voge · NIU · Benelli · Royal Alloy | 189 | 184 | own sites / Sanity / Dropbox | four run WordPress and answer `wp-json/wp/v2/media?media_type=application` |

**Checked and genuinely unreachable** (written down so nobody re-walks them): CFMOTO — every official
source TLS-resets or 403s from outside its region, Googlebot included. LiveWire — documents live inside
Harley's OAuth'd SIP viewer. Beta — VIN only, no index. Moto Morini, Brixton, Ural, Janus, Norton, Mash,
CCM, SWM, Fantic — not one owner's-manual PDF between them (every plausible path plus the sitemaps,
2026-09-20). Energica, Segway, Sur-Ron, Talaria, Stark — nothing free and fetchable.

**Per-VIN portals** get a resolver instead of rows: `registry/dynamic.py`, called by
`ondemand.ensure(bike_id, vin)` when no static PDF is known. Must answer in < 10 s and never raise.

## Service manuals

`type == "service"`, 187 rows, 19 makes. The surprise is that three makers publish theirs free.

| access | rows | who |
|---|---|---|
| **free** | **172** | MV Agusta 113, Zero 49, Sherco 5, Royal Alloy 5 |
| paid | 7 | Honda (helminc, print $50–125) · Yamaha (eBook $14.99/30 days) · Kawasaki (~$90) · Suzuki (~$90) · KTM · Husqvarna · GasGas (print.ktm.com, PDF ~EUR 25–31) |
| subscription | 3 | BMW **EUR 9 / hour** (aos.bmwgroup.com) · Triumph GBP 5.99 / month per bike · Harley-Davidson |
| dealer only | 5 | Ducati · Piaggio · Moto Guzzi · Aprilia · Royal Enfield |

This is the product argument in one table: the manual a *rider* needs is free for 9,438 of our bikes; the
manual a *shop* needs is metered by the hour at the brands that matter most. We fetch none of the paid,
subscription or dealer rows — we let the shop point at the copy it already bought (PDF upload, or the
Dropbox Chooser once `TTM_DROPBOX_APP_KEY` is set).

## Copyright stance

1. **The registry stores locations, not documents.** Every row is a URL on the manufacturer's own host.
   `RegistryEntry` has no field that could hold manual content.
2. **We ingest only manuals that are published free, or that the user holds.** `/ingest` is reached two
   ways: a free OEM URL from the registry, or a PDF the user supplies. There is no third path, and no
   paid, subscription or dealer row is ever fetched.
3. **An ingested PDF is cached**, now in the Azure Blob `pdf` container, because the app renders the
   manufacturer's actual page — that is the product. The container is public-read so the browser can
   range-fetch pages without an API hop; for a free manual that is the same public file the OEM already
   serves, and for a user-supplied manual it is their own copy in their own index.
4. **Nothing is rewritten, so nothing new is authored.** Sections are headings the manual prints, quotes
   are character-for-character, and `ingest/ground.py` drops any quote it cannot find in the PDF text
   layer. Chat may only emit page numbers; the server slices the quote out of the original page.
5. **Attribution is unavoidable, by design.** Every screen shows the manual's cover title and its own
   printed page number. There is no way to read an answer here without knowing which manufacturer wrote it.

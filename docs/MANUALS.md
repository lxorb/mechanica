# The manual registry

**7,511 entries, 15 brands, not one PDF copied.** A `RegistryEntry` stores where a manual lives — make,
model, years, market, language, type, access, price, URL — and nothing else. `api/data/registry.json`.

| | count |
|---|---|
| free owner's manuals | 7,496 |
| …in English | 7,324 |
| …fetchable as a direct PDF, so `/ingest` can index them unattended | **6,282** |
| service manuals (all paid, subscription or dealer-only) | 15 rows, one per brand/market |
| bikes in the catalog, mostly derived from these rows by `bikes_from_registry()` | 17,800 |

## Free owner's manuals — the endpoints that actually work

One adapter per portal in `api/app/registry/`, each returning `RegistryEntry` rows. These endpoints were
found by hand and are live as of 2026-09-19; the comments in each file record what broke and why.

| brand | adapter | endpoint | rows | note |
|---|---|---|---|---|
| KTM | `pierer.py` | `ktm.com/en-us/service/manuals/…/bikemanuals` (+ `.suggestions.json?query=`) | 1,669 | one AEM component, three sites; PDFs on the KTM CDN |
| Husqvarna | `pierer.py` | `husqvarna-motorcycles.com/en-us/service/user-manuals/…/bikemanuals` | 516 | same component |
| GasGas | `pierer.py` | `gasgas.com/en-us/service/manuals/…/bikemanuals` | 194 | same component |
| Kawasaki | `kawasaki.py` | `pws.ktivs.net/manuals` | 1,308 | Inertia JSON. **Do not send `Accept: application/json`** — that routes to the API guard and 401s. Needs `X-Inertia` + a version header |
| Honda US | `honda.py` | `powersports.honda.com` Sitecore downloads API | 1,119 | CSRF token first, Googlebot UA (Akamai), 25 models per batch |
| Honda EU | `honda.py` | `hondamotopub.com`, region `HMEE` | 184 | PDF hrefs scraped off the portal page |
| Triumph | `triumph.py` | `api.triumphtechnicalinformation.com/handbooks/products/model-names` | 975 | throttled to 1 req / 1.8 s (the API limits 20 per 10 s). Handbooks are viewer pages, not direct PDFs |
| BMW | `bmw.py` | `manuals.bmw-motorrad.com/…/01/Nav.xml` | 946 | one XML lists every rider's manual. Only `BA-SPRACHE` 00 (de) and 01 (en) are mapped — the rest are skipped rather than guessed |
| Yamaha EU | `yamaha.py` | `yamaha-motor.eu/services/api/owner-manuals?category=Motorcycles` | 336 | one call returns everything, with the CDN URL |
| Suzuki | `suzuki.py` | `motorrad.suzuki.de/cms/api/delivery/de/GLOBAL/page`, 2016–2025 | 172 | German-market handbooks only; German, so excluded from unattended English ingest |
| Royal Enfield | `royalenfield.py` | `royalenfield.com` `{us,in,uk}/en` manual pages | 77 | PDF path sits on the download button; no model year published, so years come from the seed catalog |

`free_owner_manuals()` is the ingest queue: `type == "owner"`, `access == "free"`, English, and a URL that
ends in `.pdf` or sits on a known direct host. Newest model years first.

## Service manuals — none of them are free

`api/app/registry/service.py`, one static row per brand and market so the registry can answer "can I even
get this?" without a crawl. Prices as coded, checked 2026-09-19.

| brand | market | where | access | price as coded |
|---|---|---|---|---|
| Honda | US | helminc.com | paid | print $50–125 |
| Yamaha | US | yamahapubs.com | paid | eBook $14.99 / 30 days, print $99 |
| Kawasaki | US | kawasaki.com | paid | print ~$90 |
| Suzuki | US | genuinesuzukimanuals.com | paid | ~$90 |
| KTM · Husqvarna · GasGas | EU | print.ktm.com | paid | PDF ~EUR 25–31 |
| Harley-Davidson | US | serviceinfo.harley-davidson.com | subscription | subscription |
| BMW | EU | aos.bmwgroup.com | subscription | **EUR 9 / hour** |
| Triumph | GB | triumphtechnicalinformation.com | subscription | GBP 5.99 / month per bike |
| Ducati | EU | rmi.ducati.com | dealer | professionals only |
| Piaggio · Moto Guzzi · Aprilia | EU | rmiportal.piaggiogroup.com | dealer | professionals only |
| Royal Enfield | IN | royalenfield.com | dealer | dealer only |

This is the whole product argument in one table. The manual a rider needs is free; the manual a *shop*
needs is metered by the hour. We do not index a single one of these — we let the shop point at the copy
it already bought (**Dropbox** or a PDF upload in `AddManual.tsx` → `/ingest`).

## Copyright stance

1. **The registry stores locations, not documents.** Every row is a URL on the manufacturer's own host.
   Crawling it copies nothing; `RegistryEntry` has no field that could hold manual content.
2. **We index pages only for manuals that are published free, or that the user holds.** `/ingest` is
   reached two ways: a free OEM URL from the registry, or a PDF the user supplies (upload or a Dropbox
   direct link). There is no third path, and no paid or subscription row is ever fetched.
3. **An ingested PDF is cached on the instance that ingested it** (`data/pdf/<manual_id>.pdf`), because
   the app renders the manufacturer's actual page — that is the product. For a user-supplied manual that
   is their own copy in their own index; for a free manual it is the same public file the OEM serves.
4. **Nothing is rewritten, so nothing new is authored.** Sections are headings the manual prints, quotes
   are character-for-character, and `ingest/ground.py` drops any quote it cannot find in the PDF text
   layer. We add pointers: ids, page ranges and highlight rectangles.
5. **Attribution is unavoidable, by design.** Every screen shows the manual's cover title and its own
   printed page number. There is no way to read an answer here without knowing which manufacturer wrote
   it — which is the point.

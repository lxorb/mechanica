# Cars

Same registry, same `RegistryEntry`, one extra field: `kind: "car"`. Rows measured 2026-09-20; the
"verified" column is a magic-byte sample of 4 rows per host (`%PDF-`, the row's own `needsUa`),
not a guess: **127 of 127 sampled URLs across 33 hosts really are PDFs**.

| group | rows | files | how it is enumerated | verified |
|---|---|---|---|---|
| **GM** Chevrolet · GMC · Buick · Cadillac · Pontiac · Oldsmobile · Saturn · Hummer · BrightDrop | 2,185 | 1,962 | `cars_gm.py`. One open Solr core, `contentdelivery.ext.gm.com/bypass/gma-search-api/searchapi/solr/gma-public/select?q=*:*` — the same query `gma-cs-mmy-selector-v3.js` runs. `source:aem` rows carry a direct `path`. 1993–2027 | 4/4 |
| **Ford** | 2,018 | 983 | `cars_ford.py`. `ford.com/support/owner-manuals-details/owner-manuals-library` lists 786 model years; each detail page ships its document list as escaped JSON. 72 nameplates, PDFs on `fordservicecontent.com`. 1996–2027. Lincoln has no equivalent library page — its owner-manual page is a separate React app and is not covered | 4/4 |
| **Toyota · Lexus** | TOYOTA_ROWS | TOYOTA_FILES | `cars_toyota.py`. `toyota.com/service/tcom/downloadableManuals/{series}/{year}` is public and answers for Lexus too. No series index exists, so the 130 series slugs are a kept list and every (series, year) pair is asked. PDFs on `assets.sipb.toyota.com` | 4/4 |
| **Hyundai · Genesis** | 799 | 799 | `POST /bin/common/resourceResult {resultType:"manualandwarranties", tags:"my-hyundai:{year}"}` after one cookie GET. 2003–2027 | 8/8 |
| **Stellantis** Jeep · Ram · Dodge · Chrysler · Fiat · Alfa · Lancia · Opel · Peugeot · Citroën · DS | 1,082 | 1,082 | `vehicleinfo.mopar.com/assets/publications/...`, `aftersales.fiat.com/eLumData/...`, `public.servicebox.peugeot.com` + `service.citroen.com` (Opel rides the same PSA platform). Consumer sites are Akamai-walled; the asset hosts are not | 20/20 |
| **Nissan · Infiniti · Mazda · Subaru** | 681 | 681 | `owners.nissanusa.com/content/techpub/...` and the newer `nissanusa.com/content/dam/...`; `mazdausa.com/siteassets/...`; Subaru's model→trim→documentation API rewritten to the permanent `techinfo.subaru.com/stis/doc/ownerManual/` host | 28/28 |
| **Honda · Acura · Mitsubishi** | 245 | 245 | `techinfo.honda.com/rjanisis/pubs/OM/AH/{CODE}/enu/{FILE}.pdf`; `mitsubishi-motors.ca` and `.co.uk` list theirs in plain HTML | 12/12 |
| **Renault · Dacia** | 253 | 253 | `user-manual.{renault,dacia}.com/sites/{brand}/files/...pdf`, walked through each site's own Drupal model/edition index | 12/12 |
| **Premium** Mercedes-Benz · MINI · Jaguar · Land Rover · Tesla | 485 | 332 | `mbusa.com/content/dam/...`, `miniusa.com/content/dam/mini/PDF/archiveownermanuals/...`; JLR is static PDF to MY2015 and an HTML iGuide after; Tesla is HTML only | 12/12 |
| **VW group · Volvo** | 128 | 128 | Only the free edges: VW quick-start guides on `vw.com/idhub/...`, Porsche QSGs on `contentful-assets.porsche.com`, SEAT/Cupra's legacy `seat.com/datamanual-manual/...`, Volvo `volvocars.com/static/support-content/pdfs/...` (Googlebot UA) | 23/23 |

**Three fetch traps.** GM's CDN 403s our crawler UA on the PDFs as well as the API, so every GM row
carries `needsUa: "browser"`. `fordservicecontent.com` is the exact reverse — Akamai silently drops a
Chrome *or* Googlebot UA and serves the file to a plain one — so Ford rows carry no `needsUa` at all;
Volvo needs `googlebot`. `techinfo.honda.com` ships an incomplete TLS chain, so every Honda/Acura URL
is `http://`: on `https` the whole set fails ingest with `CERTIFICATE_VERIFY_FAILED`.

**Free but not fetchable, so recorded and not queued.** Kia hands each PDF out against a one-shot
session token (`kiatechinfo.com` answers a cold fetch with 200 and zero bytes) and keeps one portal row
instead of 37 dead links. Tesla, Mercedes MY2025+ and JLR from MY2016 publish an HTML manual and no
PDF; those rows are real, and `_is_pdf()` keeps them out of the ingest queue.

**Checked and genuinely gated**, so nobody re-walks them: BMW cars and current MINI (`driversguide.bmw.com`
is VIN-search only, no model browse), Audi (`ownersmanual.audi.com`, VIN plus an AWS WAF captcha),
Porsche's full manual and Škoda (CARIAD's OIDC "BOD" platform, 401 unauthenticated), VW's own manual
(VIN; `literature.vw.com` is behind a Cloudflare challenge), and Honda/Acura US `owners.honda.com`
(now a VIN-gated Salesforce portal - techinfo is the way in). **Cars add no `dynamic.py` resolvers**: a
resolver must return a URL `httpx` can fetch, and every one of these needs a captcha, a login, or a
session the ingest fetch does not share.

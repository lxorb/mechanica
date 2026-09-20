# Cars

Same registry, same `RegistryEntry`, one extra field: `kind: "car"`. Rows measured 2026-09-20; the
"verified" column is a magic-byte sample per host (`%PDF-`) with the row's own `needsUa`, not a guess.

| group | rows | files | how it is enumerated | verified |
|---|---|---|---|---|
| **GM** Chevrolet · GMC · Buick · Cadillac · Pontiac · Oldsmobile · Saturn · Hummer · BrightDrop | 2,185 | 1,962 | `cars_gm.py`. One open Solr core, `contentdelivery.ext.gm.com/bypass/gma-search-api/searchapi/solr/gma-public/select?q=*:*` — the same query `gma-cs-mmy-selector-v3.js` runs. `source:aem` rows carry a direct `path`. 1993–2027 | 3/3 |
| **Ford · Lincoln** | see below | | `cars_ford.py`. `ford.com/support/owner-manuals-details/owner-manuals-library` lists 786 model years; each detail page ships its document list as escaped JSON. PDFs on `fordservicecontent.com`. 1996–2027 | 3/3 |
| **Toyota · Lexus · Scion** | see below | | `cars_toyota.py`. `toyota.com/service/tcom/downloadableManuals/{series}/{year}` is public and answers for Lexus too. PDFs on `assets.sipb.toyota.com`. 1996–2027 | 3/3 |
| **Hyundai · Genesis** | 799 | 799 | `POST /bin/common/resourceResult {resultType:"manualandwarranties", tags:"my-hyundai:{year}"}` after one cookie GET. 2003–2027 | 6/6 |
| **Stellantis** Jeep · Ram · Dodge · Chrysler · Fiat · Alfa · Lancia · Opel · Peugeot · Citroën · DS | 1,082 | 1,082 | `vehicleinfo.mopar.com/assets/publications/...`, `aftersales.fiat.com/eLumData/...`, `public.servicebox.peugeot.com` + `service.citroen.com` (Opel rides the same PSA platform). Consumer sites are Akamai-walled; the asset hosts are not | 15/15 |
| **Nissan · Infiniti · Mazda · Subaru** | 681 | 681 | `owners.nissanusa.com/content/techpub/...` and the newer `nissanusa.com/content/dam/...`; `mazdausa.com/siteassets/...`; Subaru's model→trim→documentation API rewritten to the permanent `techinfo.subaru.com/stis/doc/ownerManual/` host | 18/18 |
| **Honda · Acura · Mitsubishi** | 245 | 245 | `techinfo.honda.com/rjanisis/pubs/OM/AH/{CODE}/enu/{FILE}.pdf`; `mitsubishi-motors.ca` and `.co.uk` list theirs in plain HTML | 9/9 |
| **Renault · Dacia** | 253 | 253 | `user-manual.{renault,dacia}.com/sites/{brand}/files/...pdf`, walked through each site's own Drupal model/edition index | 9/9 |
| **Premium** Mercedes-Benz · MINI · Jaguar · Land Rover · Tesla | 485 | 332 | `mbusa.com/content/dam/...`, `miniusa.com/content/dam/mini/PDF/archiveownermanuals/...`; JLR is static PDF to MY2015 and an HTML iGuide after; Tesla is HTML only | 12/12 |
| **VW group · Volvo** | 128 | 128 | Only the free edges: VW quick-start guides on `vw.com/idhub/...`, Porsche QSGs on `contentful-assets.porsche.com`, SEAT/Cupra's legacy `seat.com/datamanual-manual/...`, Volvo `volvocars.com/static/support-content/pdfs/...` (Googlebot UA) | 15/15 |

**Two UA traps, opposite directions.** GM's CDN 403s our crawler UA on the PDFs as well as the API, so
every GM row carries `needsUa: "browser"`. `fordservicecontent.com` does the reverse: Akamai silently
drops the connection for a Chrome *or* Googlebot UA and serves the file to a plain one, so Ford rows
must carry no `needsUa` at all. Volvo needs `googlebot`. `techinfo.honda.com` serves an incomplete TLS
chain — every Honda/Acura URL is `http://` for that reason, and the whole set fails ingest on `https`.

**Free but not fetchable, so recorded and not queued.** Kia — `owners.kia.com` hands each PDF out
against a one-shot session token (`kiatechinfo.com` answers a cold fetch with 200 and zero bytes), so
it keeps one portal row instead of 37 dead links. Tesla, Mercedes 2025+, and JLR from MY2016 publish
an HTML manual and no PDF; those rows are real but `_is_pdf()` keeps them out of the ingest queue.

**Checked and genuinely gated** (written down so nobody re-walks them): BMW cars and MINI's current
range — `driversguide.bmw.com` has a VIN-search route and no model browse, and bmwusa.com says so
outright. Audi — `ownersmanual.audi.com` is VIN plus an AWS WAF captcha. Porsche's full manual and
Škoda — CARIAD's OIDC-gated "BOD" platform, 401 unauthenticated. VW's own manual — VIN, and
`literature.vw.com` sits behind a Cloudflare challenge. Honda/Acura US `owners.honda.com` now redirects
to a VIN-gated Salesforce portal; techinfo is the way in. None of these can be rescued by a
`dynamic.py` resolver: a resolver has to return a URL `httpx` can fetch, and every one of them needs
either a captcha, a login, or a session the ingest fetch does not share — so cars add no resolvers.

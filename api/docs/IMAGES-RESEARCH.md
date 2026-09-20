# Where else do motorcycle photos come from? (2026-09-19)

Baseline: `web/store/bike-images.json` (Commons *file search*, `api/tools/images.py`)
covers ~1.6k of 7,465 make|model families. 5,840 missing, 252 of them with a `manualId`.

| source | verdict | why |
|---|---|---|
| **Openverse API** | **dead** | `api.openverse.org` and `api.openverse.engineering` both answer HTTP 403 "Just a moment..." — a Cloudflare browser challenge — for any scripted client, browser UA included. `POST /v1/auth_tokens/register/` is behind the same wall, so no app key can be obtained. Not usable headlessly. |
| **Wikipedia lead images** | **yes, source #1** | `generator=search&prop=pageimages&piprop=original` on a wiki returns the article's lead image at full size. Article leads are curated whole-bike photos. `en` alone is thin, but `de/fr/es/it/nl/ja/pl/sv/cs/pt/fi/ru` carry model articles English lacks (e.g. `de:Suzuki GSX-R 750`). Files are Commons-hosted, so the licence comes from the Commons `imageinfo`/`extmetadata` API; a file that is *not* on Commons (local fair-use upload) resolves to "missing" and is rejected automatically. Search is loose (`it` answered "Suzuki GSX-R" for a GSX-R 750), so the page **title** must name the model. |
| **Commons categories** | **yes, source #2** | `list=search&srnamespace=14` finds `Category:Suzuki GSX-R 750`; `generator=categorymembers&gcmtype=file` then lists its photos. This is the real gap-filler: a file sitting in a model category is a photo of that model even when its filename is `DSC_0431.jpg`, which `images.py`'s filename matcher can never accept. Exact category titles must be searched for — guessing `Category:<make> <model>` misses (`Suzuki GSX-R750` does not exist, `Suzuki GSX-R 750` does). |
| **Commons relaxed search** | **yes, source #3** | Same endpoint as `images.py` but with `incategory:` / description-level matching and no `filetype:bitmap` restriction, for models with neither an article nor a category. |
| **Wikidata P18** | **skip** | `?item wdt:P31/wdt:P279* wd:Q34493 ; wdt:P18 ?img` yields only **394** items across the whole motorcycle tree, and every one of those files is already reachable via the article or the category. Not worth a second matcher. |
| **Kaggle / HF datasets** | **skip** | The motorcycle image sets on both are brand-level classification dumps (`bike-image-dataset`, `motorcycle-brands`) scraped from dealer and press sites: no per-model label, no per-image provenance, and licences that are either CC BY-NC-SA or simply absent. Redistributing them on trustthemanual would be a copyright problem, not a coverage win. |
| **Manufacturer press kits** | **forbidden** | Copyrighted, per the brief. Not queried. |
| Flickr / Unsplash / Pexels APIs | skip | Need an API key; Flickr's CC subset is already inside Commons for anything a rider would recognise. |

Implemented in `api/tools/images2.py` as a three-source waterfall (Wikipedia lead ->
Commons category -> Commons relaxed search), CC0/CC BY/CC BY-SA/PD only, >=640 px,
whole-bike aspect and title filters, output `web/store/bike-images-2.json`.

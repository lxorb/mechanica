# QA — Handy Book

Live: https://mechanica.emilvinu.ch/counter/ and https://trustthemanual.cloudflare-disjoin783.workers.dev/counter/ (`/` 302s to it on both). Headless Chrome, 390x844 + 1280x800, screenshots in `docs-shots/qa-*.png`.

## Verified against the live API
- Typeahead from the first keystroke over 19.5k bikes; make chips; ready/ondemand/none year chips; VIN `VBKJSA40XXXXXXXXX` -> KTM 390 Duke 2024; photo ID -> 390 Duke with ondemand years.
- 390 -> Confirm -> Pick (chapters are the manual's own headings) -> Brake system -> p.84 with markers on the exact lines -> strip 84/85/86 -> double-tap + ctrl-wheel zoom -> Contents outline (276 rows) -> Follow -> Parts -> Invoice (RevZilla/Partzilla/Amazon).
- Asks: "change the oil" -> p.114, "torque rear axle" -> p.78, "how do I wheelie" stays on Pick with the nearest sections.
- On-demand: photo -> 2019 ondemand chip -> Confirm Yes -> progress bar 74/94/100% -> Pick in ~62 s, manual `ktm-390-duke-2019-eu-om`. `POST /manuals/ensure` also resolves for ktm-390-duke-2023 (ready) and -2020 (running).
- Back: browser Back and the new header Back both walk invoice->follow->book->pick->confirm->identify; on Identify they clear VIN/photo/query first.
- PWA: sw scope + manifest start_url/scope `/counter/`, standalone, theme #e85d04, 5 icons 200. Offline (DNS blackholed) after one visit: shell, fonts, roster, chapters and the PDF page all render from cache.
- `#cost` overlay, cost numbers from `GET /cost`. Zero console errors and zero failed requests on every online step.

## Fixed
- `counter/js/screens/book.js` — the Contents button was hidden whenever the manual has no page thumbnails (always, on our API), so the outline was unreachable; it now shows whenever the manual has an outline and toggles TOC <-> the job's pages (dead `chapter` var dropped).
- `counter/js/screens/confirm.js` — a "none" bike offered only PDF upload; the Manual button now runs `ensureManual` first (progress bar) and falls back to PDF/Dropbox, and passes the VIN.
- `counter/js/ttm.js` — `ensureManual(bikeId, onProgress, {vin})` posts `{bikeId, vin}`.
- `counter/js/bus.js` + `app.js` + `index.html` + `css/counter.css` — `state.vin`, a screen `back()` hook, and the persistent header Back button (44 px, in the ticket bar, hidden only on a bare Identify).
- `counter/js/screens/identify.js` — VIN stored in `state.vin`; sub-state events for the Back button; make chips no longer preview makes on focus, only while typing.
- `counter/sw.js` (v5) — manual PDFs are now cached and sliced for pdf.js Range requests, `/health` `/catalog` `/manuals/{id}` are network-first with a cache fallback (matched on path shape, so the same-origin `/api/*` proxy and a direct API host both work), pdf.js + its worker/fonts from jsdelivr are cached, Google Fonts are precached at install, `store/catalog.json` precached. `app.js` registers the worker before the store probe and re-probes `/health` on `controllerchange`, without which the first visit never caches it and an offline reload dropped to the bundled-only store.
- `counter/manifest.webmanifest` + `counter/icons/*` + `store/CREDITS.md` — Corvette C8 icon set (favicon.ico, 32, 180 apple-touch, 192, 512, 512 maskable with safe-zone padding on ink) from Commons "Chevrolet Corvette Stingray (C8).jpg" by Ghostofakina, CC BY-SA 4.0.
- `store/ttm-catalog.json` — regenerated from the live catalog: 20051 bikes (was 17801).
- `deploy/web.sh` — `npx wrangler deploy` was following `.wrangler/deploy/config.json` and shipping `dist/` (the old React build); it now removes that redirect and passes `--config wrangler.jsonc`. The first live deploy of this app went out only after that fix. (`deploy/web.sh`, `wrangler.jsonc`, `worker/` and the `ttm-api` meta are the hosting agent's from here on.)

## Remaining
- `web/.assetsignore` keeps `store/models/` off the deploy: `yzf-2021/scene.bin` and `honda-cbr650r/scene.bin` are 26.5 MiB, over the Workers 25 MiB per-asset cap, and `js/viewer3d.js` is not imported yet. Compress (Draco/meshopt) and drop the ignore line — owner: 3d agent.
- The bundled roster ships without `manualUrl` (the full set is 1050 KB, over the tool's 500 KB budget), so first paint shows ondemand years only after `GET /catalog` lands ~2 s later — owner: adapter agent.
- Voice and Dropbox buttons stay hidden: `/voice/config` returns no ElevenLabs agent and no Deepgram, and `TTM_DROPBOX_APP_KEY` is unset — owner: voice / hosting agents.
- Confirm -> PDF upload is wired to `Q.ingest` but was not run end to end (a full ingest is minutes) — owner: ingest agent.

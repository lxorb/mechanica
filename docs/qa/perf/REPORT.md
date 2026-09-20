# First load — Mechanica counter app

Owner: performance agent · 2026-09-20 · files: `web/counter/js/app.js`, `web/counter/js/ttm.js`,
`web/counter/sw.js`, `web/tools/perf.mjs` (new), `docs/qa/perf/index-head.patch` (for the
index.html owner to apply).

## How this was measured

`node web/tools/perf.mjs` — headless Chrome, 390x844 @dpr 2, CDP throttling **applied to the
page and to the service worker's own target** (without that second half every warm load
quietly measures an unthrottled phone). `web/` is served locally, gzipped and ETagged the way
the edge serves it, with `/api` proxied to the same Azure container the Worker proxies to, so a
local run boots down the live REMOTE path.

    fast 4G  4 Mbit/s down, 3 up, 20 ms RTT   ·   slow 3G  400 kbit/s, 2000 ms RTT   ·   CPU 4x

Three numbers, all taken inside the page:

| | |
|---|---|
| **fcp** | first contentful paint |
| **field** | the search box is on the glass — in the DOM *and* painted, so a blocked main thread counts against it |
| **card** | the first `.id-card` after `390` was typed; the page types it itself, in the task that first sees the field, so no driver latency is counted |

`landing` is what the page had fetched by the time that first card appeared (Resource Timing,
i.e. what DevTools shows). Raw rows: `docs/qa/perf/*.json`.

## fast 4G + 4x CPU, cold cache

| | fcp | field | card | landing |
|---|---|---|---|---|
| **before** | 443 / 428 / 461 | 6367 / 6320 / 6769 | 7099 / 7016 / 7462 | 55 req · 275 KB |
| **after** | 355 / 635 / 415 | **665 / 887 / 723** | **3774 / 2392 / 3812** | 28-30 req · 226-310 KB |
| after + index.html patch | 563 / 598 | 720 / 844 | 4066 / 3843 | 29-30 req · 288-304 KB |

Median: field **6.4 s to 0.72 s**, card **7.1 s to 3.8 s**, landing **55 req / 275 KB to
29 req / 226 KB**.

The same pair measured earlier with eight browsers fighting over the machine — closer to what a
cheap phone on conference wifi feels like: before field 15.8-32.0 s, card 17.5-34.3 s; after
field 2.2-3.6 s, card 2.9-9.9 s.

## fast 4G + 4x CPU, warm (second visit, worker controlling)

| | fcp | field | card |
|---|---|---|---|
| **before** | 401 / 421 | 5536 / 7021 | 6247 / 7708 |
| **after** | 530 / 240 | **1685 / 1110** | **4040 / 2842** |

## slow 3G + 4x CPU, cold cache

| | fcp | field | card |
|---|---|---|---|
| **before** | 8724 | 25381 | 26227 |
| **after** | 6795 | 19939 | 23547 |
| **after + index.html patch** | **5370** | **9752** | **14884** |

Slow 3G is where the head patch earns its place: at a 2000 ms RTT the module graph is four
serial round trips and the roster is a fifth. modulepreload and preload collapse them.

## Offline (warm visit, then the plug pulled)

| | field | card | result |
|---|---|---|---|
| **before** | 5723 / 10545 | 6428 / 11372 | 60 cards, store `remote` (cached /health) |
| **after** | 5838 / 915 | 7827 / 2615 | 60 cards, store `remote` |

The offline landing search still works, on the bundled roster, with photos. QA's open item 4 —
an offline reload landing straight on a manual — is untouched by this work.

## What changed

### web/counter/js/app.js

1. **Identify is the only screen the first route waits for.** The other four were imported one
   at a time, in series, before the first route — and they drag in the 3D viewer, the chat
   bundle, the PDF reader and the parts sheet: about 90 KB gzipped of JavaScript fetched,
   parsed and compiled in front of the search field. They now load on the first touch or
   keystroke, or on the first idle slot after the roster, whichever comes first. A deep link
   (#pick, #book) still waits for the store and for its own screen, because revive() has to run
   before any screen registers itself. heal() re-routes if a module arrives after its route did.
2. **The service worker registers on `load`, not during boot.** Installing it means precaching,
   and on a cold first visit those fetches raced the ones the search field was waiting for —
   the roster went down the same wire twice.
3. `window.Q` is published before the store resolves (it is the same module namespace object).
4. `Q.uiUp()` after the first route — see ttm.js below.

### web/counter/js/ttm.js

5. **The roster fetch starts with loadCatalog(), not after /health.** It never depended on the
   probe's answer.
6. **The 4.6 MB `GET /catalog` refresh is off the boot path.** It was 9.5 s of a cold fast-4G
   load with every screen module queued behind it, to adopt a delta that is always the same
   thing: a manual indexed since the bundle was built. `GET /manuals` (85 KB, 12 KB gzipped)
   says exactly that, and was already being fetched for catalog().manuals — it now does the
   adoption. refreshRoster() stays exported for `window.TTM_CATALOG = "api"` and the console.
7. **The photo index (1.7 MB raw, 160 KB gzipped) is off the critical path.** Fetched after the
   roster is on screen, applied to 27.4k rows in 4k-row slices with a yield between them,
   memoised per make+model (one ladder walk per model instead of per row), and painted
   synchronously onto whatever findBikes() / bike() is about to hand a screen. One repaint,
   through the `ttm:catalog` event Identify already listens for.
8. **The bundle expands in 600-row slices**, with a yield between them and between merge and
   index, so the 8 s single task that used to swallow the first keystroke is gone.
9. **The search index is built in two stages.** search.js turns 27.4k vehicles into trigram
   sets: 4.9 s of blocked main thread at 4x CPU, measured. Stage one indexes one row per model
   (9.2k rows, about 1.2 s), which for a typed query is the same answer — Identify groups hits
   by make+model and takes the year span from the roster, not from the index. Stage two builds
   the full index behind it and repaints. Both are released one **painted frame** after the
   first screen is up: a task boundary is not enough, and letting the build go there put 1.1 s
   between the field being in the DOM and the field being on the glass.
10. **online() is optimistic while the probe is in the air and the roster is still empty**, so
    Identify's /catalog/suggest top-up is allowed to answer the very first keystroke. That is
    the API-first path the brief asked for, and it is what produces the 2.4 s cards in the
    fastest runs.
11. indexBikes() memoises the registry slug per make+model instead of re-slugging 27.4k rows.
12. User Timing marks for every boot phase (ttm:health, ttm:bundle, ttm:index-lead, ...), so the
    next person can read the boot in the DevTools performance panel without this harness.

### web/counter/sw.js

13. **Precache split in two.** Install takes the shell that a first paint and a working search
    field are made of — files the page is fetching anyway, so one conditional request each.
    Everything the *second* visit needs (the other screens, the chat bundle, the roster, the
    photo index, catalog.json — half a megabyte) is taken only when the page says it is done
    loading (postMessage "precache-rest", with a 15 s fallback off the first fetch), four at a
    time, skipping anything already cached, and **without `cache: "reload"`** — which is what
    stopped the roster being downloaded a second time on every first visit.
14. **activate does no slow work.** A worker is "activating" until its activate handler settles,
    and every fetch from the page it has just claimed waits for that: a 20 s precache delay
    parked there cost a warm load 20 seconds. Found and fixed inside this pass.
15. **Static shell assets are cache-first with a revalidation behind them**; navigations stay
    network first. Thirty conditional requests put the warm search field at 21 s; the cache
    answers them in about a second. A deploy still reaches an open tab: new VERSION, new worker,
    old caches dropped, claim, and app.js reloads — and the navigation that follows is network
    first, so the reload lands on the deployed page.

### docs/qa/perf/index-head.patch — for whoever owns index.html

Two hunks, `git apply`-able. One: preload the roster, modulepreload the six modules behind the
search field, preconnect to the two CDNs pdf.js and three.js come from. Two: media="print" on
the six stylesheets for screens the landing cannot reach — 60 KB of render-blocking CSS in front
of a field that uses none of it. Both are measured above; the second is the more opinionated
half and can be dropped on its own.

## Known trade-offs

- **Stage-one index**: for a few seconds a query that is *only* a year ("2015", no model) finds
  fewer models than it will once the full index lands. Every other query shape — including
  "2024 390 duke", which Identify splits into year plus text before it searches — is unaffected.
- **online() optimism** lasts from the first module until /health answers, and only while the
  roster is still empty. Nothing is tappable in that window, so the only caller is the suggest
  top-up; a suggest that fails is swallowed.
- **adoptManuals() sets manualId on existing rows** rather than replacing the roster, so a
  manual adopted after the index was built leaves a stale hasManual flag inside the index.
  Ranking only: cards read the live row, and Identify orders by the grouped row's state.
- **Cache-first shell** means a deploy reaches an already-open tab through the existing
  controllerchange reload rather than on its very next request.
- Not done, and the biggest single cost left: `search.js buildIndex` itself, 4.9 s at 4x CPU for
  the full 27.4k rows. search.js is not one of my files. Indexing the roster at model depth
  permanently (the shape the cards already use) or moving the build into a worker would take it
  off the main thread entirely.

## Checks

- `node web/tools/bughunt-check.mjs` — 53 passed, 0 failed.
- `node docs/qa/book/book-shots.mjs phone` — all 14 states drive correctly (titles, pages,
  markers, rotation, contents, zoom). Its own `barVisible` assertion (offsetParent !== null)
  started failing at 15:03 today, when book.css/book.js changed under another agent and
  `.book-bar` became `position: fixed` — offsetParent is null for a fixed element, and the bar
  it flags is 44x390 and on screen in every shot. Not this pass, and not mine to fix.
- `node web/tools/orb-shots.mjs` — green but for one timing-sensitive assertion that flakes on a
  loaded machine, a different one each run ("reduced motion: the ring still fills with the
  level", "no layout shift entering or leaving voice mode"). Neither touches the boot path.
- `node --check` on every file touched.

## Traces in this folder

| file | what |
|---|---|
| `before-fast4g-cold-a/b.json`, `before-fast4g-warm.json`, `before-slow3g-cold.json` | the code as it was, quiet machine — the "before" rows above |
| `after-fast4g-cold.json`, `after-fast4g-warm.json`, `after-slow3g-cold.json` | the code as it is now |
| `after-patch-fast4g-cold.json`, `after-patch-slow3g-cold.json` | with index-head.patch applied to the served bytes (`perf.mjs --patch`) |
| `before-loaded-*.json` | the same before/after pair taken while eight browsers were fighting over the machine |

Reproduce any row:

    node web/tools/perf.mjs --only fast4g-cold --runs 3            # local, API proxied
    node web/tools/perf.mjs --only fast4g-warm --offline           # second visit, then no network
    node web/tools/perf.mjs --only slow3g-cold --patch             # with the index.html hints
    node web/tools/perf.mjs --live --only fast4g-cold              # against mechanica.emilvinu.ch
    node web/tools/perf.mjs --noapi --only fast4g-cold             # the LOCAL store path

## Checked and left alone

`web/counter/js/vendor-loader.js` was offered in the brief and is not needed: three.js
(`viewer3d.js:648`), the deep-chat bundle (`chat-ui.js:161`) and pdf.js (`pdf.js:80`) are
already dynamic `import()`s that only run on their own screen. What they were missing is the
connection setup, which is the `preconnect` half of index-head.patch — and, until this pass,
the fact that their screens' modules were being downloaded and compiled on the landing anyway.

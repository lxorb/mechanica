# BUGS-UI — bug hunt pass 2, the UI, 2026-09-20

Pass 1 (`docs/qa/BUGS.md`) read the backend and the routing/search modules and left the screens
"not exercised in a browser". This pass is that: every screen driven headlessly at **390×844
(touch, dsf 3)**, **768×1024 (touch, dsf 2)** and **1280×800**, in **Workshop**, **Night** and
**Paper** by hand and in **all five themes** by the harness, with the API alive, killed mid-flow,
and slowed to 400 kbit/s.

Surfaces read and driven: `counter/js/bus.js`, `theme.js`, `pdf.js`, `climate.js`, `particons.js`,
`parts-search.js`, `pick-search.js`, `index-data.js`, `screens/{identify,confirm,pick,book,invoice,cost}.js`,
`counter/index.html`, all of `counter/css/**`.

Harness: **`node web/tools/bughunt-ui.mjs`** — 13 checks, one per fixed bug, each failing on the
code as it was. `--view desk|tab|phone`, `--only <fragment>`. It serves `web/` locally with
`/api/*` proxied to the live worker (request bodies included, which `theme-shots.mjs` drops), and
cuts the API off at the proxy to drive the error states. A fourteenth check is opt-in because it
takes six minutes: `--only themes` walks all five themes through nine stops and asserts the theme
holds, the console stays silent, the Conditions sheet's bottom edge is the viewport's, and `#cost`
opens cold — theme-shots' two assertions plus the two this pass fixed that a contact sheet cannot
see.

    node web/tools/bughunt-ui.mjs                  -> 13 passed, 0 failed   (390x844)
    node web/tools/bughunt-ui.mjs --view desk      -> 13 green at 1280x800, across two runs:
                                                      12 in one pass, the thirteenth alone after
                                                      a CDP timeout under load
    # Each walk drives a real browser with a software-rasterised WebGL stage. On a box running
    # several agents at once (measured: ~36 Chrome processes) a check times out waiting for
    # `.hit` or `.id-card` while the API itself answers in 0.1-0.4 s — CPU starvation, not a
    # finding. Every failure of that shape names the selector it waited for; UI-H1's
    # empty-roster boot names itself. Re-run the check alone before believing it.
    node web/tools/bughunt-ui.mjs --only themes    -> 1 passed  (5 themes x 9 stops, 0 console errors)
    node docs/qa/book/book-shots.mjs               -> 42 states, 1 flagged (the documented tablet
                                                      harness artifact in docs/qa/book/REPORT.md)

`web/tools/theme-shots.mjs` was run too and its assertions pass (`ok workshop/phone — 10 stops, 0
console errors`); the run was abandoned because its twenty full-page WebGL captures were losing
frames to `Page.captureScreenshot: Internal error` with ~37 other Chrome instances on the box. That
is the swiftshader flakiness its own source comments describe, not a change from this pass — and it
is why the theme walk above exists without captures.

Screenshots: `docs/qa/ui-bugs/` — before/after for UI-01 (the Conditions slab over the reader) and
UI-02 (the cold `#cost`). "Before" is produced by serving the single line that carried the bug as
it was, so each pair differs only by that line. The other two of the worst four are measurements
rather than pictures, deliberately: UI-06's "before" is a page the renderer never painted at all
(`first-contentful-paint` absent at 2.5 s, 12.1 s in the end) and a forced capture of it shows
pixels no user ever sees; UI-05's is a reader that never settles, so any single frame of it is a
transient — the number is `here=pick` vs `here=book, p.7/143`, which is what the check asserts.

## Findings

| id | sev | screen / file | what | state |
|---|---|---|---|---|
| UI-01 | med | Conditions · `climate.js` | the sheet opened as a 202 px slab pinned to the **top** of the viewport, over the reader's own bar | fixed |
| UI-02 | med | `#cost` · `cost.js`, `bus.js` | a cold load of the meter's own address showed the landing page and nothing else | fixed |
| UI-03 | med | Parts · `bus.js` | an open sheet lost its history entry: one Back closed nothing, the next did nothing at all | fixed |
| UI-04 | med | Parts · `bus.js` | walking back onto `#book+invoice` from another screen opened the sheet and shut it in the same frame | fixed |
| UI-05 | med | Book · `book.js` | a reload on an outline heading threw the reader away and dropped to Pick | fixed |
| UI-06 | med | boot · `index.html` | a hanging `fonts.googleapis.com` blanked the whole app: first paint 0.3 s → **12.1 s** | fixed |
| UI-07 | low | Pick · `pick.css` | the bike chip — the way back to Confirm — was 34 px tall against the product's own 44 px floor | fixed |
| UI-08 | low | Parts · `invoice.css` | `p. N` mention chips were 42 px wide | fixed |
| UI-09 | low | Parts · `invoice.js` | an offers call that throws left the skeleton and its crawling bar on screen for ever | fixed |
| UI-10 | low | Pick · `pick.js` | a catalog fetch landing after the screen is gone repainted it and could re-mount the 3D stage behind another screen | fixed |
| UI-11 | low | `bus.js` | an entry with no hash and no state hid every section — a blank app with nothing to tap | fixed |
| UI-12 | low | Parts · `parts-search.js` | no ceiling on query tokens (pass 1's BUG-08, in the one search that was missed) | fixed |
| UI-13 | low | Book · `book.js` | two answers opened inside 900 ms left the first sheet glowing for ever | fixed |
| UI-H5 | **high** | boot · `app.js` / `ttm.js` (not mine) | nothing called `ttm.js`'s new `uiUp()`, so the search index never built and the landing found nothing — caught on the working tree at 14:23, **fixed by its owner at 14:32**, ten minutes later | closed |
| UI-H1 | med | boot · `app.js` (not mine) | the whole first frame waits on the catalog: no search field within 40 s at 400 kbit/s, and a reload lands on Identify whenever the roster is not ready at that instant | handoff |
| UI-H2 | low | `viewer3d.js` (not mine) | the model and the HDRI are fetched and then aborted on every Pick entry | handoff |
| UI-H3 | low | `ttm.js` (not mine) | `mergeDuplicates()` carries a merged row's `manualId` but not its new `lang` | handoff |
| UI-H4 | low | registry (not mine) | six Harley "Universal … Quick Start Guide (…)" rows render as six identical cards at 390 px | handoff |

**13 fixed · 0 open · 4 handoff · 1 caught and closed by its owner.** By severity: 6 med, 7 low
fixed; 1 high (closed), 1 med, 3 low handed off.
Zero console errors and zero page errors on every online step of every run, at every viewport, in
every theme. The only failed requests anywhere in the walk are UI-H2's two aborted model loads.

---

## Fixed

### UI-01 — Conditions opened as a slab across the top of the reader · med
**Repro** Book → `Cond` at any viewport. The sheet sits `top 0 … 202 px` of an 844 px screen,
over the reader's own bar, instead of rising from the bottom edge.
`docs/qa/ui-bugs/01-conditions-before.png` vs `-after.png`.
**Root cause** `climate.js::node()` built its `<aside>` as `class="ov cv"`. `cv` is chat-ui's
full-screen view: `css/chat-ui.css` declares `.cv { justify-content: stretch; z-index: 60 }`, and
`stretch` is not a flex value, so it computes as `flex-start` — the bottom sheet is anchored to the
top of a full-height flex column. Nothing in Conditions is a chat view; every one of its own rules
is `.cf-*`.
**Fix** `class="ov cf"`. `.ov` already provides the bottom-sheet layout and `.cf-sheet` its
max-height, so no CSS was added. (This was open item 6 in `web/QA-FINAL.md`, still unfixed.)
**Test** `bughunt-ui.mjs`: "Conditions is a bottom sheet" — asserts the aside no longer carries
`cv`, that `justify-content` is `flex-end`, and that the sheet's bottom edge is the viewport's.

### UI-02 — a cold load of `#cost` showed the landing page · med
**Repro** open `https://mechanica.emilvinu.ch/counter/#cost` in a fresh tab: the landing screen,
hash rewritten to `#identify`, no meter, ever. (Reaching it by editing the hash on an already-open
page worked, which is how it kept passing QA.)
`docs/qa/ui-bugs/03-cost-before.png` vs `-after.png`.
**Root cause** two, in series.
1. `cost.js` decided `const wanted = readHash() === "cost"` at module scope — but it is imported by
   `screens/pick.js`, the **third** screen app.js imports, and `bus.js::bootFromHash()` has already
   run during the **first** one and rewritten the URL to `#identify` (`#cost` is not a step).
2. It then waited for a `"screen"` event to open itself. The boot emits exactly one, from that same
   `bootFromHash()` — before this module exists. `firstGo()` takes `go()`'s `onlyReplace` early
   return and emits nothing.
**Fix** `bus.js` exports `bootHash`, the hash captured at module load — bus.js is the first module
in the graph, so it is the address the user actually typed; `cost.js` reads that, and opens itself
in `initCost()` instead of waiting for an event it cannot hear. `bus.js::hashFor()` additionally
leaves a non-step hash alone when it **replaces** an entry (it already does on popstate), so the
address bar still says `#cost` while the meter is up.
**Test** `bughunt-ui.mjs`: "a cold load of #cost opens the meter" — also asserts the figures land.

### UI-03 — an open sheet lost its own history entry · med
**Repro** Book → Parts → tap a part (detail) → Back. Before: the URL reads `#book` although Parts
is still open — the entry that named the sheet has been overwritten with the screen's own, so the
stack now holds `#book` twice and the extra press is dead: measured at 1280×800, two Backs in a row
both ended at `#book` with nothing on screen changing.
**Root cause** `go()` wrote `"#" + id` unconditionally. Parts is an overlay entry (`#book+invoice`)
over the same screen, so every `replaceState` from Book — and `onPop` calls one on every step —
overwrote the entry that named the sheet.
**Fix** `hashFor()` / `histFor()` in `bus.js`: a URL written while a sheet is open carries it.
**Test** `bughunt-ui.mjs`: "an open overlay keeps its history entry".

### UI-04 — walking back onto a sheet opened it and shut it in the same frame · med
**Repro** Book → Parts → tap a `p. N` chip on a part (this leaves for the reader) → Back. Before:
Parts reopened and closed instantly, and the entry was rewritten to `#book`.
**Root cause** `onPop()` called `syncOverlay(overlay)` **before** `go(id)`, and `go()` closes
whatever sheet is open as its first act of switching screens.
**Fix** close before the screen switch, open after it, then stamp the URL so it names what is
actually on screen.
**Test** `bughunt-ui.mjs`: "leaving a screen with an overlay open still walks back".

### UI-05 — a reload inside Book lost the page · med
**Repro** Pick → tap any contents heading → MANUAL → reload. Before: **Pick**, with the page gone.
**Root cause** most headings have no indexed section behind them (the KTM manual: 20 sections
under 270 outline rows), so `pick.js` synthesises a job and parks it on the manual record
`T.manual()` is holding. A reload refetches that record, the parked job is gone, `Q.jobById()`
answers `null`, and `enterScreen()` bounced. `app.js` keeps the bike, the job id and the page
across a reload precisely so this does not happen — and for an **indexed** section it worked
(verified: `p.76/143`, title intact), which is why it was never caught.
**Fix** `book.js::reviveJob()` — on a miss, rebuild a one-page job from `state.jobId` + `state.page`
and park it the same way. The reader comes back on the same page; the bar names the chapter from
the outline as it always did.
**Test** `bughunt-ui.mjs`: "a reload on an outline heading keeps the reader open".

### UI-06 — a hanging font CDN blanked the whole app · med
**Repro** open the app with `fonts.googleapis.com` unreachable-but-slow (flaky garage wifi, a
captive portal, a DNS black hole). Measured with a 12 s hang: **first contentful paint 12,100 ms**,
field usable at 14.2 s. Every other byte of this app is local and service-worker cached. There is no
screenshot pair because there is nothing to photograph: the renderer records no paint at all for
those twelve seconds, and forcing a capture of that page shows pixels the user never gets.
**Root cause** `index.html` loaded Barlow + Big Shoulders as a plain `<link rel="stylesheet">`, which
is render-blocking, from a third party.
**Fix** `media="print" onload="this.media='all'"` plus a `<noscript>` copy. The faces already carry
`display=swap`, so a cold load was already a FOUT; this only decides whether the app is on screen
while it waits. After: **FCP 116 ms**, field at 2.3 s, with the CDN still hanging. The normal path
did not get slower (308 → 284 ms).
**Test** `bughunt-ui.mjs`: "a hanging font CDN cannot blank the app" — fails over 4 s.

### UI-07 — the bike chip on Pick was a 34 px target · low
`.who` measured **171×34** at every viewport and in every theme. It is not decoration: it is the
way back to Confirm. `min-height: 44px` (and 12 px of trailing padding) in `css/screens/pick.css`.
**Test** in `bughunt-ui.mjs`, plus the standing geometry sweep below.

### UI-08 — `p. N` chips in a part's mentions were 42 px wide · low
`.pv-mentions .pv-page` had the height but not the width; `min-width: 44px`.

### UI-09 — a failed offers call left Parts loading for ever · low
`fetchOffers()` awaited `T.partOffers()` with no `catch` of its own (the only one is on the caller,
which paints nothing) and read `body.offers.length` without checking the shape. A throw — or a 200
that is not the expected shape — left the skeleton rows and the bar crawling to 97 % with no end.
Today's adapter resolves `null` on a dead API (verified: killing the proxy mid-detail falls back to
the manual's own shop links in ~6 s), so this is one layer of defence, not a live break.
**Fix** both calls catch, and one `offersOf()` reads the shape.
**Test** `bughunt-ui.mjs`: "a dead API ends in shop links, never a stuck skeleton" (proxy killed).

### UI-10 — Pick's loader had no token on leave · low
`leave()` bumped `askGen` but not `gen`, the token `load()` checks. Leaving Pick while the catalog
fetch is in flight therefore repainted a hidden screen and called `startViewer()` on it — and if the
bike record had arrived in the meantime, the key differs, so that is a **second** WebGL context
mounted behind whatever the user is now looking at, which nothing disposes. `gen += 1` in `leave()`.
**Test** `bughunt-ui.mjs`: "leaving mid-load never mounts a second 3D stage" (canvas count).

### UI-11 — a blank app on one history step · low
`onPop()` with neither a hash nor a `state.screen` hid every `section[data-screen]` and cleared the
rail: a ground-coloured page with nothing on it and no way back but a reload. Reachable only if
something pushes a hash-less entry, which nothing does today. It now lands on Identify.

### UI-12 — the parts search had no query ceiling · low
Pass 1 capped `search.js` and `pick-search.js` at `MAX_QUERY_TOKENS = 12`; `parts-search.js` runs
the same Damerau ladder over every token of every row and was missed. Same cap, declared locally so
the file stays dependency-free.

### UI-13 — an ask-flash could stick · low
`flash()` cleared the class only on the sheet it was about to flash, so two answers opened inside
900 ms left the first one glowing permanently.

---

## Handoff — the exact repro, for the owner

### UI-H1 — boot hangs on the catalog, and a slow one loses the mechanic's place · med · `app.js` / `ttm.js`
**Repro** `emulateNetworkConditions` 400 kbit/s, 400 ms latency, cold cache, `/counter/`:
first paint 3.6 s, and `.id-q` **never appeared within 40 s**. On a fast link the same walk has the
field at 2.3 s. QA-FINAL's own number (Fast 4G + 4× CPU: 10.2 s) is the same effect, smaller.
**Suspected line** `app.js::boot()` — `window.Q = await pickStore();` is awaited **before**
`await import("./screens/identify.js")`, so nothing renders until `/health` (2.5 s timeout) plus the
593 KB roster bundle have both landed. `findBikes()` already forces the search index lazily, so the
field can exist and accept keystrokes before the roster does; an empty-handed Identify is a far
better first frame than an empty page. Suggested shape: import the screens and `firstGo()` first,
then `pickStore()`, then the `ttm:catalog` event identify.js already listens for.

**Second symptom, same cause.** `revive()` needs the roster complete at the instant it runs
(`if (!Q.bike(spot.bikeId)) return false`). `bootRemote()` resolves with an **empty** roster when
the bundle fetch and `/catalog` both time out under load, and fills it a few seconds later — so a
reload inside Book lands on **Identify** with the mechanic's place intact in `sessionStorage` and
unused. Reproduced twice in a row on a contended box (roster 29,938 by the time it was read back,
0 when `revive()` asked). One line of insurance: re-run `revive()` + `firstGo()` once on the
`ttm:catalog` event when the first attempt found nothing, or await the roster before `revive()`.
`web/tools/bughunt-ui.mjs`'s reload check retries once and names this case, so it is not confused
with UI-05.

### UI-H5 — the landing search found nothing at all · **high** · `app.js` / `ttm.js` · **closed**
**Caught at 14:30 on the working tree (`ttm.js` saved 14:23, `app.js` saved 13:55) while the boot
path was being rewritten by another agent, and fixed by that agent at 14:32 — `app.js` now calls
`Q.uiUp()` and ttm.js added a 3 s self-release as a backstop. Verified green at 14:33: 28 cards,
29,749 rows indexed. Written up because a half-landed refactor of the front door is worth a record,
and because the backstop is the interesting part of the fix.**
**Repro** open `/counter/`, type `390 duke`, wait: **no cards, ever**. Measured in-page:
`Q.bikes().length` 29,746, `search.indexedCount()` **0**, `Q.findBikes("390 duke")` **[]** — and
calling `search.buildIndex(Q.bikes())` by hand right then works fine (723 ms, 29,746 rows, 3 hits).
So the roster is there, the index code is fine, and nothing ever builds it. No page error, no
unhandled rejection.
**Root cause** `ttm.js` now gates its heavy passes behind `afterUi()`, whose queue is drained by
`export function uiUp()` — and its own comment says *"app.js calls uiUp() the moment it has routed
to a screen"*. **Nothing calls it:** `grep -rn "uiUp" web/counter/js/` matches only ttm.js's own
declaration and that comment. So `waiting` never drains, `indexSoon()` — which sets `indexing =
true` synchronously before awaiting `afterUi` — never finishes, and `findBikes()`'s
`if (!indexed && !indexing)` force never fires because `indexing` is stuck true for the life of the
page. The image pass is gated on the same queue.
**Fix** one line in whichever file the owner prefers: `Q.uiUp()` right after `firstGo()` in
`app.js::boot()`, or have ttm.js drain the queue itself on the first `screen` event. Worth a guard
too: `indexing` should be cleared on any path that abandons the build, and `findBikes()` could
force after a deadline rather than never while `indexing`.

### UI-H2 — the 3D model is fetched and then aborted · low · `viewer3d.js`
**Repro** enter Pick on `ktm-390-duke-2024` and watch the network: exactly one request each for
`store/models/generic/naked/model.glb` and `store/models/env/auto_service-1k.hdr`, both ending
`net::ERR_ABORTED`, while `[data-viewer3d]` still reaches `ready`. Repeats on every entry. No user
impact found; it is either a double fetch whose loser is cancelled or an abort fired after the bytes
are in. Worth a look because it is the only network noise left in the app.

### UI-H3 — a merged row keeps its manual but drops its language · low · `ttm.js`
**Suspected line** `ttm.js::mergeDuplicates()` — `if (!win.manualId && lose.manualId) win.manualId
= lose.manualId;` and the same for `manualUrl` / `ondemand`, but not for the new `lang`. A row that
inherits another's manual should inherit the language that manual is written in, or the new tag
(below) will be missing on exactly those vehicles.

### UI-H4 — six identical cards · low · registry
**Repro** type `harley-davidson universal` at 390 px: six cards, every one reading
`HARLEY-DAVIDSON / UNIVERSAL MOTORC… / 2023–2025`. What tells them apart — the language list — is
inside the model name, past the ellipsis. The new language tag helps where the registry assigns
one, but the rows themselves are the problem.

---

## Also shipped in this pass — the manual's language

The registry now assigns official manuals in other languages to vehicles with no English one
(**1,587** of 27,226 roster rows carry it; 633 bundle rows). Carried through and shown:

- `index-data.js` — `extra.l` (a per-year map, like `manuals`) is expanded onto the bike as `lang`,
  and `decorate()` normalises the API's own `lang` the same way. `null` / `"en"` both mean English
  and show nothing; `langOf()` is the one place that decides.
- **Year chips and the card's year line** (`identify.js`) — a quiet uppercase `FR` inside the chip,
  inheriting its colour, so it works in all five themes and in every chip state. A card covers a
  whole model, so it only carries the tag when **every** year that has a manual is in the same one
  language; a mixed model says nothing and lets the chips tell it.
- **Confirm** — a `--slab` stamp beside the year, quieter than the year and cc stamps because it is
  a caveat, not an identity.
- Verified at 390 px: `triumph tt600` → chips `2003 FR … 2000 FR` (52 px tall), Confirm `2003` `FR`;
  `alfa romeo 147` → chips `2009 IT 2008 IT 2007 IT 2005` and no card tag, because 2005's manual is
  English. `ktm-390-duke-2024` shows nothing anywhere.
- **Test** `bughunt-ui.mjs`: "a non-English manual is tagged, an English one is not".

---

## Checked and **not** bugs

Recorded so pass 3 does not re-chase them.

- **No listener leak.** With `addEventListener`/`removeEventListener` both counted, window and
  document listeners are **flat** across 10 Pick↔Book cycles and 10 Identify↔Confirm cycles
  (window 10, document 3, unchanged). An earlier count that only tallied additions looked like a
  leak; it was the row handlers of rebuilt lists, which go with the nodes.
- **No timer, observer or canvas leak** over the same 20 switches: `setInterval` balance 0,
  IntersectionObservers created but each `setPages()` disconnects the previous pair, `<canvas>`
  count stays 1 (the 3D stage), sheets in the DOM stay bounded by the virtualiser.
- **Reduced motion** — `[data-swapping]` is never armed and the theme still swaps; the counter.css
  rule that kills the crossfade outranks it as documented.
- **Print** — no horizontal overflow at 390 in `emulateMediaType("print")`.
- **Refresh on every hash** — `#identify`, `#confirm`, `#pick` restore themselves from
  `sessionStorage`; `#book` with an **indexed** job comes back at `p.76/143` with the title intact;
  `#bogus` keeps the current screen instead of bouncing.
- **The photo path** — the KTM hero fixture through `.id-file` reaches Confirm with 7 alternatives,
  the split photo/catalogue frame, and Back that pops the photo, then the query, then goes dark.
  (Photo *accuracy* remains QA-FINAL item 2, identify-backend.)
- **Keyboard** — tab order theme → field → camera → cards; ArrowDown from the field enters the grid,
  arrows walk the grid and the year chips, ArrowUp returns to the field; the 3 px `--focus` ring is
  on every stop. The theme disc being the first stop is deliberate (it is first in the DOM).
- **Geometry** — at 390/768/1280 in Workshop, Night and Paper, across landing, cards, chooser,
  Confirm, Pick, Pick-search, Book, contents, all-pages, Parts, part detail, Conditions and `#cost`:
  no horizontal scroll, nothing escaping the viewport that a clipping ancestor does not already cut,
  no text spilling an `overflow: visible` box, and no interactive element under 44 px once UI-07 and
  UI-08 were fixed. The longest model name in the roster (104 chars) and the longest chapter title
  both ellipsise.
- **`pdf.js`** — `releaseCanvas()` really does zero the bitmap, the LRU is capped at 12 sheets, a
  `forget()` drops the document and its rasters, and `renderPage()`'s `wanted` WeakMap discards a
  render whose canvas has since been handed to another page.
- **Theme persistence** — `localStorage` is read once before first paint and every read/write is in
  a `try`; a dark system still only votes on a genuinely first visit.
- **The landing showing no cards on a starved box is `ttm.js::indexSoon()` working as designed,
  not a fault in Identify.** While `indexing` is true `findBikes()` deliberately does not force the
  27.4k-row build, so a CPU with nothing to spare (measured: the search index still at 0 rows 12 s
  after the roster landed, while `/api` answered in 0.1–0.4 s) leaves the field answering nothing
  until the slices get through. Identify's own `/catalog/suggest` top-up is the intended cover for
  that window. Worth knowing before reading a `.id-card` timeout as a bug — and worth a thought by
  the adapter owner as to whether the force should happen after some deadline rather than never
  while `indexing`.

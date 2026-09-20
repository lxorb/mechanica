# Book (reader) — top bar, mobile pass, loading

Owner: book agent. Files changed: `web/counter/js/screens/book.js`, `web/counter/css/screens/book.css`,
`web/counter/js/pdf.js`. Screenshots: `before/` (reproduction) and `after/` (fixed), 390x844 dsf 3,
768x1024 dsf 2, 1280x800. Harness: `book-shots.mjs`, `book-load.mjs`, `book-checks.mjs` in this folder.

## Root causes of "the top bar doesn't properly display"

1. **A single tap on the page hid the whole bar, and there was nothing left to tap.**
   `viewEl` listened for `click` / `touchend` and armed `toggleImmersive()` after 360 ms. Any still
   tap — stopping a momentum scroll, a glove brushing the page — flipped `immersive`, and
   `[data-root].immersive .book-bar { display: none }` took the bar away. The shell's own ticket bar
   and 4-step rail are already `display: none` for `body[data-here="book"]`, so the reader was left
   with zero chrome: no chapter, no page number, no Back, no Parts. The state also **persisted**
   through a page jump, a rotation, the contents view and a chapter change, which is why it read as
   "very often" rather than "once". `before/phone-09-after-tap.png` is the whole bug in one picture.
   *Not* a cause: `position: sticky` (the bar is a flex row, not sticky) or the zoom transform (the
   bar is a sibling of the transformed `.page-col`, never inside it).

2. **The bar was painted from the manual, which arrives after the screen does.**
   `paint()` awaited `Q.manual(job.manualId)` before writing `titleEl` / `stampEl`, so every entry
   showed an empty title and no page number until `GET /manuals/{id}` answered — and *forever* if it
   failed, since `manualRec = (await Q.manual(...)) || {}` has no fallback. Reproduced at
   `before/tablet-01-entered.png` and `before/desktop-01-entered.png` (`title="" stamp="-"`).

3. **Four writers of the bar, none of them complete.** `paint()`, `setPages()` and `setCurrent()`
   each wrote a different subset of title / stamp / cover / mode button, so the contents view and the
   all-pages toggle each left a different part of the bar stale.

4. **The bar was over-stuffed and under-sized on a phone.** Nine non-shrinking flex children in
   390 px left the chapter title ~130 px ("12.12 Che..."), and every control was 30x28 px — well under
   the 44 px the product's own rules require.

## What changed

- **The bar carries identity only and is never hidden.** Back · contents · chapter · `p. N/M`, 44 px
  tall, 44 px targets, chapter title at 0.92 rem. Immersive now hides only the bottom rows
  (`.page-strip`, `.book-acts`); one tap on, one tap off, and the answer to "where am I" never leaves.
- **Actions moved to a thumb row at the bottom** (`.book-acts`: ALL · ask · mic · COND · PARTS), each
  `flex: 1`, min 44x44. Matches DESIGN rule 5 (bottom controls, one-handed, 44 px).
- **`paintBar()` is the single writer**, called from `paint()`, `setPages()`, `setCurrent()`, the
  page-count backfill and the ensure path. `paint()` now paints from the **job** (which already names
  its chapter and first page) before awaiting the manual, so the bar is right on the first frame and
  survives a failed `GET /manuals/{id}`. On a page it shows the chapter; in the contents it shows the
  manual's own cover title.
- Page strip chips 40 -> 44 px; strip 44 -> 48 px.
- `scrollIntoView()` replaced with a direct `viewEl.scrollTop` set — it walked the ancestors and could
  shift the shell.
- **Zoomed pages are re-rasterised, not magnified.** `wantW()` = sheet width x quantised zoom (capped
  at 1600 CSS px), and a 220 ms debounce after the gesture re-renders whatever is on screen. DPR cap
  stays 2. Measured: phone 764 px bitmap over 382 CSS px -> at 3x zoom, **2292 px over 1146 CSS px**,
  still exactly 2.00x. Before, it stayed 764 px over 1146 (0.67x) — visibly soft.
- **A rotation while zoomed resets to fit** instead of leaving `.page-pad` sized for the old viewport.
- **The all-pages toggle keeps the place**, not just the page: `scrollMark()` records the fraction of
  the current sheet you are on and `setPages({ offset })` restores it.
- Markers untouched — already percentage-of-sheet inside an `inset: 0` box, so they scale with the
  page. Verified, not assumed (below).

## Loading

- **Page-shaped skeleton.** Every `.page-sheet` that has not painted is `--paper` with one slow sweep
  (`page-sweep`, 1.3 s), on a box already set to the page's real aspect ratio — so nothing moves when
  the canvas lands. `prefers-reduced-motion` drops the sweep, keeps the paper.
- **The 3D stage's ring, reused.** `makeRing()` in book.js emits the same `.viewer3d-load*` markup as
  `progressRing()` in viewer3d.js and uses its CSS verbatim (css/viewer3d.css is already global): no
  second visual language, no new CSS. It rides on the sheet being read.
- **Real bytes.** `pdf.js` now keeps a per-file record (`idle | loading | ready | failed` + loaded /
  total from pdf.js's `onProgress`) with `onDoc(url, fn)` / `docStatus(url)` / `forget(url)`. Known
  total -> percentage; no total -> the indeterminate spin, which is the truth (Azure serves Range, so
  pdf.js pulls chunks and no whole-file total exists).
- **Boot skeleton.** `enterScreen()` opens on one A4 placeholder with the ring before `jobById()` has
  even resolved, so the first frame is never an empty dark box.
- **On-demand ingest.** No `manual.file` -> `Q.ensureManual(bikeId, onProgress)` drives the same ring
  from `done / pages`, then repaints and rasterises.
- **Nothing spins forever.** A failed document, a failed ensure, or 25 s (`STALL_MS`) with no progress
  flips the ring to the quiet `is-failed` state, stops the sheet's sweep (`.is-stalled`) and makes the
  ring a tap target. The retry calls `forget(url)` and starts over — traced as
  `failed > idle > loading > failed` across the tap, so it really re-fetches.

## Verified

`node docs/qa/book/book-shots.mjs` (390x844 dsf 3 + touch, 768x1024 dsf 2 + touch, 1280x800), driving
the live API through a local proxy, `ktm-390-duke-2024/chain-tension-check` (p.77-78, 4 highlights):

- **42 states, 0 flagged.** Entered, rendered, scrolled, all-pages, page jump, zoomed, scrolled while
  zoomed, unzoomed, after a tap, rotated, unrotated, contents, chapter opened, marks, marks rotated.
  At every one: bar present at 44 px full width, nothing clipped, no bar overflow, chapter and
  `p. N/M` correct, every control >= 44x44, no horizontal page scroll at fit. Zero console errors.
- **Markers**: p.77's first highlight measured as a fraction of its sheet at four widths —
  236 / 382 / 526 / 792 px — is identical to 4 decimals (`x 0.1595, y 0.4584, w 0.2066, h 0.0237`),
  through a rotation.
- `node docs/qa/book/book-checks.mjs`: layout shift 1-2 column-height changes for a whole manual (the
  single base-ratio correction, not per sheet); zoom raster 2.00x DPR held at 3x zoom; all-pages
  toggle returns to `p.78 + -0.534` / `p.77 + 0.403`, unchanged.
- `node docs/qa/book/book-load.mjs --whole` (cold cache, `emulateNetworkConditions` ~400 kbit/s,
  400 ms latency, whole-file trickled PDF): spin -> 25% -> 91% -> content, skeleton sweeping
  throughout, bar correct the whole time. `after/phone-load-whole-b.png`.
- `node docs/qa/book/book-load.mjs --fail` (manual `file` rewritten to a 404): spin -> quiet failed
  ring in ~1.5 s, sweep stops, tap retries. `after/phone-load-fail-c.png`.

## Notes / left alone

- Single-tap immersive is kept (it is the standard reader gesture and now only toggles the bottom
  rows, which one tap brings back). If the founder wants no gesture at all, it is one line in
  `onClick` / `onTouchEnd`.
- `before/tablet-15-marks-rotated` is a harness artifact: that run had walked into a one-page chapter,
  so the p.77 chip it clicks did not exist. Phone and desktop cover the assertion.
- The bottom is now two rows (strip 48 + actions 48). On 390x844 that leaves 704 px for the page,
  which still fits an A4 sheet at 382x540 with room.

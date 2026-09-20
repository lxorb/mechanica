# UI polish pass — 2026-09-20

Founder's brief, verbatim: *"For the landing page, change the text to 'search for motorcycle
part or upload image.' For 'Is this your bike?' make it only one step when the PDF is
missing—do not have two upload steps. Make everything normal case, not uppercase, with only
the first letter capitalized. Ensure the down arrow fits inside its box. In desktop view, make
the bike large in the left panel and the instruction manual on the right. Make the interface
less boxy and smoother."* — plus nine follow-ups from five screenshots (below).

Shots: `before/` and `after/`, `<theme>-<viewport>-<stop>.png`, 390×844 and 1280×800 in
Workshop and Night. Re-runnable: `node docs/qa/ui-polish/shots.mjs --tag after`.

---

## 1 · Landing copy

`js/screens/identify.js` — the single field's placeholder and `aria-label` are now
**"Search for motorcycle part or upload image"**. VIN auto-detect is untouched: the field
still flips to the mono/spaced VIN treatment on a WMI prefix and jumps at 17 characters.

41 characters do not fit a 390 px field at the old 1.15 rem, and the one line on the landing
is the whole instruction, so it may not be cut. The landing field's type now steps
0.86 → 1 → 1.2 rem at 390 / 440 / 640 px, and the placeholder weight dropped 700 → 500.

Every other visible landing string was already a noun or an acronym: `VIN` (tag), `Photo`
(aria), make chips (catalog data). The header word `MECHANICA` became **Mechanica**
(`index.html`).

## 2 · "Is this your bike?" — one step, not two

**Root cause.** `manualState(bike) === "none"` means the registry knows *no* manual for the
vehicle — neither `manualId` nor `manualUrl` nor `ondemand`. `showActions("none")` answered
that with an unlabelled book-glyph button. Pressing it ran `onAdd()` →
`Q.ensureManual()` → `POST /manuals/ensure`, which for a bike with no `manualUrl` answers
`status: "none"` essentially always (the catalog *is* the API's own knowledge, refreshed from
`GET /catalog`). `runWork()` then fell through to `showSource()` — a second row, *PDF ·
Dropbox · ✕*. So: prompt 1 was a lookup that could not succeed, prompt 2 was the real upload.
Reproduced on **Ducati 1199 Panigale 2012–2014** (`before/workshop-390-confirm-none.png` →
`…-confirm-none-2.png`), a model with no manual in any year in both the bundled catalog and
the live `/api/catalog`.

**Fix** (`js/screens/confirm.js`): the `none` card is now one step —
"Is this your bike?", the line *"Manual not available. Upload the PDF."*, and one control,
**Upload PDF**, which opens the file picker on the first tap. `showSource()` and the whole
`.confirm-source` row are gone; a failed `ensureManual` from the `ondemand` path now lands in
the same single card (`shownState = "none"`) instead of a second prompt. Dropbox, when
`TTM_DROPBOX_APP_KEY` is ever set, renders inside that same row — a second *source*, not a
second *step*. It is unset everywhere today, so the control count is exactly one.

**Traded away, deliberately:** the automatic free-manual lookup on the `none` path. It is kept
where it can actually find something — the `ondemand` state, behind the Yes the rider presses
anyway. If the registry ever starts resolving manuals for bikes it has no row for, this is the
line to revisit.

## 3 · Sentence case everywhere

`text-transform: uppercase` is gone from every stylesheet in `web/counter/css/` **except
`voice-orb.css`** (see *Not done*). 33 rules. Tracking followed: any `letter-spacing` at
0.05 em or above came back to 0.01 em — wide tracking is a setting for capitals and reads as
gaps between letters in sentence case. Four selectors keep both, because their text is a code
and not a label: `.is-vin .id-q`, `.id-vin-tag`, `.confirm-lang`, `.id-lang`, `.ask-span`.

Literal uppercase in source: `"IS THIS YOUR BIKE?"` → `"Is this your bike?"`,
`<span>MECHANICA</span>` → `Mechanica`. `"PDF"` and `"VIN"` stay — acronyms.

The manual's own headings are **not** touched: "MEANS OF REPRESENTATION" on Pick is the
chapter title as KTM printed it, and product rule 2 says nothing in the manual is rewritten.

## 4 · Glyphs that fit their box

The founder's "down arrow" is Pick's expand twist: a `›` character at 1.6 rem that CSS rotated
90° into a chevron hanging outside its 48 px cell. Both text glyphs in Pick are now stroked
SVG paths in a flex-centred square — `send` (`SEND_PATH`) and `hit-x` (`TWIST_PATH`, rotated
by CSS with a 160 ms transition). Same treatment for `.ov-x`, `.ticket-back` and `.btn-icon`
generally: `display:flex`, a real width *and* height, `line-height: 1`, `padding: 0`,
`overflow: visible`, and `svg { display:block; flex:none }`. Every one is ≥ 44 px.

## 5 · Desktop layout (≥ 1100 px)

**Pick** (`css/screens/pick.css`) — `[data-root]` becomes a two-column grid, 55 / 45.
`.stage` goes `display: contents` so its two children can land in different columns: the 3D
bike is `grid-row: 1 / span 3`, sticky at the gutter, `calc(100dvh - 134px)` tall (ticket bar
44 + rail 10 + 44 + two gutters); the search field, the headings and the MANUAL button take
the right column. `--column` is widened to `min(1600px, 100vw)` on that screen only, so the
step rail measures from the same token and lines up with the panels.

**Book** (`css/screens/book.css` + `js/screens/book.js`) — Book had no bike at all, so one
was added: an `aside.book-stage` holding a `viewer3d` mount, `display: none` and disposed
below 1100 px. Above it the reader column becomes 28 / 72 — bike left (sticky, ≤ 460 px,
≤ 52 vh), reader, page strip and thumb row right. It highlights the part the open section is
about via `partFor(job.title, job.keywords)`, re-synced on every `enterScreen`. The
breakpoint is watched with `matchMedia`, so dragging a window narrow hands the WebGL context
straight back.

Phone layouts are unchanged in both: every rule above is inside `@media (min-width: 1100px)`.

## 6 · Less boxy, smoother

One shape system, declared once in `counter.css` `:root`:

| token | value | job |
| --- | --- | --- |
| `--r-sm` / `--r` / `--r-lg` / `--r-pill` | 10 / 14 / 20 / 999 px | tiles · cards, fields, buttons · sheets · chips |
| `--hair` | 1.5 px | the structural border, was 3 px |
| `--edge` | `color-mix(in srgb, var(--line) 42%, transparent)` | that hairline, on anything clickable |
| `--edge-soft` | `…22%…` | dividers *inside* a box, and surfaces |
| `--lift` | two-stop soft shadow off `--shadow` | raised things only |
| `--ease` / `--t-fast` / `--t-mid` | `cubic-bezier(.2,0,0,1)` / 160 ms / 200 ms | hover, press, appear |
| `--gutter` / `--column` / `--gap` | 12 / 720 px / 10 px | one gutter, one content width, one gap |

`--edge` is mixed out of `--line`, so **all five themes keep their own rule colour with no
line added to `themes.css`** — a theme is still only a list of colours. No new colour was
introduced anywhere. Contrast is unaffected: nothing here touches a text pair, and
`theme-contrast.mjs` reads the same tokens it always did. Every tap target stayed ≥ 44 px, and
the collapsed-border tricks that depended on 3 px (`margin-left: -3px`, `border-top: 0`,
`outline-offset: -6px`) were replaced by real gaps and inset rings.

---

## The nine follow-ups

1. **Pick rows clipped.** `.hit-go` min-height 52 → 60 px, padding 8/10 → 14 px, `.hit-t`
   line-height 1.2 → 1.35 with 1 px of bottom padding, `.hit-b` gap 1 → 3 px, `overflow:
   visible`. The page stamp is `align-self: center` inside that taller row. The selected row
   no longer draws an `outline` with a negative offset — it states itself with its own
   `border-color` plus an inset ring, so nothing bleeds onto a neighbour.
2. **Consistent gaps, aligned edges.** `--gutter` / `--column` / `--gap`, used by `main`, the
   rail, the identify dock (which keeps its full-bleed sticky ground but pads its field to the
   same column), the card grid, the chips, the hits, the offer rows and the confirm body.
3. **No match highlight on text.** `.id-make b` / `.id-model b` and `.hit-t mark` are plain —
   no background, no `box-shadow`, inherited colour. (`.mark` in Book is the *manual's*
   highlighter over the PDF and is untouched — that is the product.)
4. **Clickable ⇒ bordered.** `.btn`, `.card`, `.tile`, `.hit`, `.pv-pill`, `.pv-offer`,
   `.id-year`, `.id-make-chip`, `.who`, `.strip-chip`, `.toc-row`, `.book-acts .bar-btn` all
   carry `var(--hair) solid var(--edge)`. Non-interactive text carries none: `.confirm-prompt`,
   `.confirm-note`, `.id-make` / `.id-model` / `.id-span`, `.hit-n`, `.pv-tag` (its 2 px inset
   ring is gone; it is now a quiet pill). Surfaces that are neither — `.sheet`, `.ov-sheet`,
   image frames — use the weaker `--edge-soft`, so "bordered" keeps meaning "tappable".
5. **Mic + camera flush.** `.ask .btn` lost its per-button right border; mic sits hard against
   the bar's left edge and the camera is divided from it by one `--edge-soft` hairline.
6. **A chat + voice pair at the bottom.** Superseded mid-pass: *"in the bottom there should be
   both a chat and a voice button (just icons) so that the voice is easier accessible."* The
   floating `.chat-pill` is gone and chat did **not** end up in the search bar. Instead
   `js/dock.js` builds one body-level fixed pair — chat bubble, microphone, 48 px each, the
   same radius/hairline/token system — shown on Pick, Book and the Parts sheet
   (`body[data-here="pick"|"book"] .dock`).

   It is **bottom left**, not bottom right: the voice orb docks bottom right
   (`voice-orb.css`, `--dock-gap`), and the pair may never sit under it. On Book it lifts to
   `108px` to clear the page strip and the thumb row, and the Parts sheet's body gained
   bottom padding so its last row is never behind it. `z-index: 46` — over the Parts sheet
   (45), under the chat view (60) and the orb (70).

   No voice code is imported into a screen: the mic dispatches
   `window.dispatchEvent(new CustomEvent("mechanica:voice", { detail: { action: "start" } }))`
   and `voice-session.js` owns it from there. Chat is a callback the live screen claims with
   `setChat()`; Book's handler fires `mechanica:chat`, which Pick answers with its own
   `chat.toggle()` — one conversation per manual, openable from either screen.
   `syncFoot()` no longer consults a pill, and Pick's `.foot` gained `padding-left: 112px`
   so the MANUAL button never runs under the pair.
7. **"COND" → "Conditions".** It only ever appeared in the reader's bottom row, where it was
   removed earlier the same day. The newest instruction wins, so it is **restored there,
   spelled out** (`book.js`, `climateBtn`, `text: "Conditions"`, → `openConditions()`). The
   row's height is unchanged (48 px min, same padding) so the voice orb still docks 16 px above
   it; the two icon buttons went `flex: 0 0 52px` to buy the words their room, and `.bar-word`
   ellipsises rather than wraps.
8. **Parts offers, sentence case.** `sentence()` in `invoice.js` repairs retailer, title,
   variant, condition and shipping. It only touches strings that arrive with **no lowercase at
   all** — a mixed-case name from a retailer is left exactly as written ("RevZilla" stays
   "RevZilla"). Tokens with a digit keep their shape (`10W40`), a list of real acronyms stays
   capital (`OEM`, `HP`, `NGK`…), and a list of generic descriptors goes lowercase unless it
   opens the string. `"YAMAHA OEM YAMALUBE 10W40 FULL SYNTHETIC HP, QUART"` →
   `"Yamaha OEM Yamalube 10W40 full synthetic HP, quart"`. `In stock` / `Out` are ours already.
9. **One price button.** `SORTS` is now *Price · Retailer · Condition*. Price carries an SVG
   arrow that rotates 180° over 200 ms; a tap on it when it is already active turns the
   direction over. **Descending is the default**, as asked — note this reverses the old
   `price-asc` default, so the first offer shown is now the dearest.

---

## Not done / for someone else

- **`css/voice-orb.css`** still holds 4 `text-transform: uppercase` and 2 `border-radius: 0`.
  It was on this pass's do-not-touch list (voice agent). It is the last uppercase in the app —
  whoever owns it should run the same two substitutions.
- **`docs/UI.md` and `DESIGN.md`** describe the 3 px ink rule and square corners as the look.
  Both are now stale in their Visual sections. Not mine to rewrite.
- **`docs/qa/ui-polish/pick-book.patch` / `book-desktop.css`** were planned as hand-off files
  while `pick.js` / `book.js` / `book.css` belonged to the voice agent. That agent finished
  mid-pass and the files were released, so the changes were applied directly instead and the
  patches were never written.
- Book's new bike panel mounts a second `viewer3d` scene. Pick disposes its own on `leave()`
  and Book disposes on `leave()` and on the breakpoint, so at most one is ever live — worth
  keeping an eye on if a future screen mounts a third.

# UI

Product rules from DESIGN.md are unchanged: zero prose, the manual is the answer, three steps, allowed strings only, mobile first.
This file replaces only the **Visual** section of DESIGN.md.

## Direction A — Pit lane

Motorsport pit wall. Carbon-fibre ground, hazard orange, tachometer arc that sweeps as the answer loads.
Italic condensed numerals, lap-timing tabular columns, a start-light strip across the top instead of a progress bar.
Year chips read as grid slots; the page strip reads as sector times; Parts is a pit board.
Gamified by speed: everything is a time or a position, the arc snaps to full when the page lands.
Strengths: instantly "motorcycle", high energy, numbers get a job.
Risk 1: this is the default costume for every bike app on the store — orange, carbon, checkers. Templated on arrival.
Risk 2: a racing dashboard is a *live instrument*. Our screen is a static legal document. The costume argues with the content.
Risk 3: the PDF sheet — white, serif-ish, A4 — sits inside the dashboard like a form taped to a steering wheel.
Risk 4: sweeping arcs and diagonal cuts eat the 390 px width that the section titles need.
Verdict: the accent survives (warm, hazard-adjacent). The dashboard does not.

## Direction B — Workshop

Brushed-steel panels, embossed label-maker type, screwhead corners, toggles with real travel.
Section rows are Dymo strips; the page strip is a row of stamped tags; Parts opens like a drawer.
Buttons depress 1 px and the ground has a faint milled texture; the marker is a wax pencil scrawl.
Gamified by tactility: everything answers to the thumb, with a click you can almost hear.
Strengths: honest to where the app is used — a garage, gloves on, phone on the tank bag.
Risk 1: skeuomorphic metal is gradients and noise textures, both banned by the product's own economy and expensive on a PWA.
Risk 2: embossed type at 13 px on a phone is unreadable; label-maker faces have no tabular numerals.
Risk 3: a warm steel ground kills the one thing that must glow — the paper.
Risk 4: dated. It reads 2012.
Verdict: keep the tactility (44 px targets, real press states), drop the material impersonation.

## Direction C — Service run (chosen)

The job is a run of three levels: Bike → Task → Pages. A three-segment rail sits under the status bar on every screen and lights up as you clear levels.
Ground is cool graphite, the colour of a cast engine case. The document is warm paper. That material split is the whole thesis:
cold machine on the outside, warm authority in the middle. One accent, amber — the colour of a highlighter and of a dash warning lamp.
Structure comes from the manual's own numbering: "13 BRAKE SYSTEM", "13.4", "p. 84/143". Real data, used as the structural device, never invented.
The reward is the marker: when a page renders, the highlight **strokes itself in** left to right, 260 ms, staggered per line. That is the product's promise, animated once.
Pages tick off as you read them — the page strip runs quiet → paper → amber, so the strip is a checklist you fill by scrolling.
Numerals are set in Archivo at an expanded width, like a stamped type plate. Body text stays system font, so the chrome never competes with the page.
No badges, no points, no confetti, no streaks, no text of any kind added.

### Why C

1. The three steps are already a sequence, so a numbered rail encodes something true instead of decorating.
2. The reward the user actually wants is *the page*, so the reward animation must be the marker, not a trophy.
3. Cool chrome / warm paper makes the PDF the brightest object on screen — rule 2 of the product, expressed in colour.
4. The manual ships its own numbering system; borrowing it beats inventing chips and pills that mean nothing.
5. It costs one font file and a dozen transitions — it stays as fast as the current build.

## Tokens

| token | value | use |
| --- | --- | --- |
| `--ink` | `#0A0E10` | app ground |
| `--ink-1` | `#161C20` | raised surface: cards, rows, input, sheets |
| `--ink-2` | `#1F272B` | secondary fill: quiet chips, badges, pressed |
| `--line` | `#2B353A` | 1 px hairlines and dividers |
| `--fg` | `#E8EDEF` | primary text |
| `--muted` | `#7E8B92` | secondary text, meta, disabled |
| `--accent` | `#FFA51F` | active step, the marker, the one primary action |
| `--accent-ink` | `#14100A` | text on accent |
| `--paper` | `#F7F5F0` | the PDF sheet **and** every cleared / visited state |
| `--mark` | `rgba(255,165,31,0.34)` | highlighter over paper, `mix-blend-multiply` |
| `--shadow` | `0 18px 40px -14px rgba(0,0,0,.72)` | under the paper sheet only |

Secondary colour is `--paper`: "done" is the colour of the document. No third hue anywhere.

## Typography

Display: **Archivo** variable (wght 100–900, wdth 62–125), self-hosted `@font-face` from `/fonts/archivo-latin.woff2`
(+ `archivo-latin-ext.woff2`, `unicode-range` gated), `font-display: swap`. Used **only** for numerals, page badges, year chips,
chapter numbers and the three uppercase labels. Everything else is the system stack.

| role | size / line | font |
| --- | --- | --- |
| `d1` | 34 / 1.0, wght 700, wdth 112, tnum | Cost figures |
| `d2` | 22 / 1.05, wght 700, wdth 110, tnum | chapter number in a section-title chip |
| `d3` | 15–17 / 1.1, wght 650, wdth 106, tnum | year chips, page chips, page badges |
| `lab` | 12 / 1.0, wght 700, wdth 118, `0.09em`, uppercase | Photo · VIN · Parts, Cost labels |
| body | 17 / 1.35, wght 400–500 | titles, section titles, part names |
| sec | 15 / 1.35 | section rows, list rows |
| meta | 13 / 1.3 | bike line, spec line, trail |
| micro | 11 / 1.2, `0.08em`, uppercase | chapter words inside a chip |

## Scale

Spacing `4 8 12 16 20 24 32 40`. Screen gutter 16. Card padding `12 14`. Row gap 8. Bottom bar pad-top 12.
Radii: `3` paper sheet, `8` badges, `10` year chips, `12` page chips, `14` cards / inputs / big buttons, `20` sheets, `999` mic and send.
Hit targets: 44 minimum, 52 search field, 56 primary buttons.

## Motion

| token | value | drives |
| --- | --- | --- |
| `--t-fast` | `150ms cubic-bezier(.2,0,0,1)` | colour, opacity, press, focus ring |
| `--t-mid` | `220ms cubic-bezier(.2,.8,.2,1)` | rail fill, sheet slide, chip promote, strip scroll |
| `--t-mark` | `260ms cubic-bezier(.16,1,.3,1)` | the marker stroke, `60ms` stagger per rect |

Animates: the rail fill, the marker stroke, sheet enter/exit, chip state changes, the make-chip stagger on first paint (40 ms step, 150 ms each, once), the mic ring while listening.
Never animates: the PDF canvas, page numbers, any text, layout reflow, the header, the page strip contents, anything on an idle screen.
`prefers-reduced-motion`: all durations → 1 ms; the marker is painted at its final state.

## Components

**Step rail** — under the safe area, inset by the gutter, 14 px down. Three equal segments, h3, r2, gap 4.
Cleared `--paper`, current `--accent`, future `--line`, each crossfading over `--t-mid`.
While loading, the current segment carries the load: an `--accent` fill inside a `--line` segment sweeping to 92 % over 6 s, snapping to 100 % on settle. This replaces `Progress` entirely — there is no second bar.
Dots on a line were tried first and read as decoration at 390 px; three bars read as "1 of 3" at a glance.

**Bike card** — `--ink-1`, r14, pad `12 14`. Title 17/500 `--fg`, truncate. Photo confidence, when present, is a 5-segment 3 px meter on the right, filled in `--accent`, no number.

**Year chips** — h40, r10, `d3`, horizontal scroll, gap 8, gutter-bled. Has manual: solid `--accent` / `--accent-ink`, wght 700. Addable: `--ink-2` / `--fg`. Dead: `--ink-2` / `--muted`, opacity .45, disabled.

**Section-title chip** — sticky at the top of its group. `--ink-1`, r8, pad `5 10`, inline-flex gap 8: leading digits in `d2` `--accent`, the words in `micro` `--muted`. Split at the first space of the manual's own chapter string; nothing is rewritten. Manuals without numbered chapters (BMW R 12 G/S) have no leading digits — then the chip is the words alone, no accent slot. Groups are consecutive runs of the same `section.chapter`, so data order is never resorted.

**Section row** — `--ink-1`, r14, min-h 56, pad `12 14`. Title `sec` `--fg`. Right: page badge `--ink-2` r8, "p." in `meta` `--muted` + number in `d3` `--fg`. Press: 1 px `--accent`/35 % border, `--t-fast`.

**Question input** — bar `--ink-1`, r16, 1 px `--line`, pad 5. Mic 44 circle, stroke `--muted`; listening: stroke `--accent` plus a 1 px `--accent`/30 % ring at 2 s ease-in-out. Input 17 `--fg`, placeholder `--muted`. Send 44 circle: idle `--ink-2` / `--muted`, ready `--accent` / `--accent-ink`. Focus-within: border `--accent`/45 %.

**Reader header** — h44 row: back ← 44 circle, manual title in Archivo 14 / wght 650 / wdth 94 / `0.012em` (measured: the full KTM and BMW cover titles fit at 390 px without truncating; a wider setting clips them, which would break product rule 3), `p. N/M` right (`p.` and `/M` `--muted` `meta`, N in `d3` `--fg`). Second line: the outline trail joined with ` · `, `meta` `--muted`, truncate. 1 px `--line` under.

**Page sheet** — `--paper`, r3, `--shadow`, 1 px `rgba(255,255,255,.07)` top edge, centred, width `min(gutter-fit, height-fit, 720)`. Marks: absolute rects, `--mark`, r3, `mix-blend-multiply`, `transform: scaleX(0)` → `1`, origin left, `--t-mark`, 60 ms stagger, once per page, only after the canvas reports ready.

**Page strip** — chips 44×44, r12, `d3`, gap 8, horizontal scroll, auto-centres the current chip over `--t-mid`. Unvisited `--ink-1` / `--muted`. Visited `--ink-1` / `--paper`, 1 px `--paper`/28 %. Current solid `--accent` / `--accent-ink`. Left slot: Voice mic 44 circle when configured. Right slot: Parts, `--ink-1`, h44, r12, pad-x 14, `lab`.

**Parts sheet** — bottom sheet, r20 top, `--ink-1`, max-h 72 %, 36×4 `--line` grab handle, ✕ 44 circle. Each part: name 15/500, page badge as in the section row, spec `meta` `--muted`, shop links as h44 r12 `--ink-2` pills.

**Progress** — no separate bar. The rail is the progress bar (see above).

**Empty states** — carry no text, ever. Identify with an empty query is the make-chip grid (h44, r12, `--ink-1`, 15/500, staggered in). Result with no matched pages is the outline list: top level `body` `--fg` with the chapter number in `d3` `--accent`, children `sec` `--muted`, indent 14 per depth, 1 px `--line` between.

**App icon** — `--ink` rounded square, a `--paper` page, two `--line` text rules, one `--accent` marker stroke with the lifted tail of a real highlighter swipe. Maskable variant keeps the stroke inside the 80 % safe circle.

## Mock

`docs/ui/mock.html` — six frames at 390×844: the run (Identify → Ask → Result) and three states (Identify empty, Parts sheet, outline).
Screenshot: `docs/ui/mock.png`.

## Shipped (phase 2)

Deltas from the spec above, all made against real screens:

- **Rail** — capped at `max-w-[720px]`, centred. Full width at 390; on desktop it belongs to the app column instead of the window. It is the only progress indicator: `Progress` takes `step` (1 identify · 2 ask · 3 result) and, while `useBusy()` is true, runs `ttm-progress` inside the live segment.
- **Ask list** — grouped into consecutive runs of `section.chapter`, capped at the first 16 sections (auto-ingested manuals carry 150–330, already ordered rider-tasks-first by the backend). Group key is the first section id, not the chapter string: chapters recur non-consecutively in ingested manuals.
- **Section-title chip** — `/^([\d.]+)\s+(\S.*)$/` on the chapter. KTM gives `18` + `SERVICE WORK ON THE ENGINE`; BMW has no numbering, so the chip is the words alone.
- **Part photo** — a camera glyph next to the mic in the ask bar. Online: `track(identifyPart(file))`, then the top label through the phrase map into `onAsk`. Offline: focus returns to the input and nothing else happens.
- **Page strip** — `visited` is derived, not stored in an effect: `{ key: pages.join(','), list }` updated inside the IntersectionObserver, so it resets with the reading list and never reads a ref during render. Right edge masked so chips fade under `Parts`.
- **Marker** — verified mid-stroke (`docs/ui/shots/marker-stroke-mid.png` vs `-done.png`): rects draw left to right, 260 ms, 60 ms apart, once per page render.
- **Search field** — the value stays in the body font; only numerals, chips, badges and the three labels use Archivo.
- **Icon** — graphite square, paper page, one amber chisel-tip stroke over a darkened rule. 512 rendered from `icon.svg`, 192 and 180 downscaled from it (headless Chrome will not screenshot windows under ~200 px). Maskable variant keeps the page inside the safe circle.
- **Cost** — figures in Archivo 30/700/wdth 112 on `--ink-1` cards, labels in `lab`.

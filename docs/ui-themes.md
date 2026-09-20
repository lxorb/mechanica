# Themes

Five themes, one switch, no settings screen. A theme is a list of colours and nothing else:
`web/counter/css/themes.css` overrides tokens inside `[data-theme="<id>"]` and never names a
component. Adding a sixth theme is ~40 lines in that one file.

- Tokens: `web/counter/css/counter.css` (`:root` **is** the Workshop theme)
- Overrides: `web/counter/css/themes.css`
- Switch + persistence: `web/counter/js/theme.js` (+ the pre-paint script in `index.html`)
- Contact sheets: `docs/ui-themes/<id>.png` — ten screens × two viewports each

## The switch

A 44 px round swatch at the **right end of the orange ticket bar**, where the job number used to
sit. The disc is split down the middle and wears the **next** theme's ground and accent, so the
control shows what it does instead of saying it; one tap moves along the cycle and five taps come
home. No label, no menu, no settings screen — this app has none, and a theme is not a reason to
start one.

Workshop → Night → Blueprint → Track → Paper → Workshop

The swap fades over **180 ms**, on colour properties only (`background-color`, `border-color`,
`outline-color`, `color`, `fill`, `stroke`); nothing moves, and under `prefers-reduced-motion:
reduce` the fade is skipped entirely and the theme simply is the new one. The transition is armed
by `[data-swapping]` on `<html>` for the length of the swap and then removed, so it never slows a
hover or a press.

`<meta name="theme-color">` follows the new accent on every change. The choice is stored in
`localStorage["mechanica.theme"]` and applied by a six-line inline script in `<head>`, before the
first paint — a returning Night user never sees a frame of Workshop. `manifest.webmanifest` keeps
`theme_color: #e85d04`: the manifest is the installed app's identity and cannot follow a runtime
choice, so it stays the default.

`prefers-color-scheme` is consulted **once**, on a genuinely first visit with nothing stored: a
dark system lands on Night, anything else on Workshop. After the first tap the system never gets
another vote, in either direction.

The bar folds away inside Book (by design — the reader is fullscreen), so the switch is reachable
from Identify, Confirm and Pick. That is where anyone changes a theme.

### API

```js
window.mechanicaTheme.list       // [{ id, label, swatch: [ground, accent], color }, …] in cycle order
window.mechanicaTheme.current()  // "night"
window.mechanicaTheme.set(id)    // apply + remember
window.mechanicaTheme.next(id?)  // the next id in the cycle
window.mechanicaTheme.tokens()   // { bg, fg, accent, card, line, grid, gridBg } read live from CSS

window.addEventListener("mechanica:theme", (e) => e.detail);  // { id, previous, tokens }
```

## The five

**Workshop** — the shipped look, unchanged: warm paper ground with its 24 px ruling, hazard
orange across the top, the yellow on everything you press, and the 3 px ink rule that everything
in this app is cut from. It is the `:root` block itself, not an override, so the default costs no
extra bytes and a failure to load `themes.css` leaves the app exactly as built.

**Night** — the same shop at 23:00 with one lamp over the bench. A warm near-black ground and a
slightly hotter orange, so the white page is the brightest object on the screen by a distance
instead of competing with a lit ground. The rule goes light (`--line: #6e777d`) to keep the
graphic weight the black rule carries in daylight. The default for a first visit on a dark phone.

**Blueprint** — the drawing the part came from. Deep drafting blue, white technical lines, cyan
for whatever is live. The only theme that replaces the ground texture: `--ground` becomes a real
24 px two-axis grid rather than the paper ruling, which is a token override, not a rule. Buttons
are white plates with a blue rule, the way a callout box is drawn.

**Track** — pit-lane livery. Asphalt ground raked with the hazard diagonal, hazard yellow across
the top bar, and marshal orange-red on everything you press. The one theme where the accent and
the press colour are different hues, which is exactly what makes a livery read as a livery.

**Paper** — midday on the forecourt, phone at arm's length, screen losing to the sun. Pure white
ground with no texture at all (texture scatters glare), black type, black rules, one red for the
live thing and one green for "you already have this manual". Every pair on this theme clears 5:1
and most clear 15:1. The search-match highlight inverts to black-on-white rather than tinting,
because a tint is the first thing sunlight eats.

**Dropped: Hi-Vis** — safety-vest lime ground, black rule, orange marker. It photographs well and
fails in use: a saturated lime ground under a white PDF sheet makes the page edge vibrate, and
lime sits close enough to the marker orange that the one thing the product exists to show stops
being the loudest thing on screen. The idea it was reaching for — maximum legibility outdoors —
is what Paper does without fighting the page.

## Tokens

`:root` in `counter.css` is the full list. A theme may override anything in **chrome** and
**stage**; nothing ever overrides **paper**.

### chrome — every theme replaces all of it

| token | Workshop | where |
| --- | --- | --- |
| `--bg` | `#ece7dc` | the app ground |
| `--ground` | ruled-paper gradient | the ground's full `background` value, so a theme can change the texture |
| `--card` | `#fff` | cards, inputs, tiles — anything raised off the ground |
| `--slab` | `#141414` | solid blocks: the reader bar, the primary button, the reader's surround |
| `--slab-fg` | `#fff` | text and glyphs on `--slab` |
| `--slab-off` | `#5c5c5c` | a slab that is disabled |
| `--slab-line` | `rgba(255,255,255,.55)` | a hairline drawn on a slab |
| `--fg` | `#141414` | primary text |
| `--muted` | `#8a8375` | labels, specs, placeholders |
| `--muted-2` | `#6c665a` | stronger meta: years, spans |
| `--faint` | `#a49d8d` | ghost art, dead borders |
| `--line` | `#141414` | the 3 px structural border |
| `--rule` | `#e4dfd2` | hairline / tint divider, and the ruling in `--ground` |
| `--accent` | `#e85d04` | the ticket bar, stamps, the live row |
| `--accent-ink` | `#fff` | text on `--accent` |
| `--accent-2` | `#ffe600` | the livery second colour: buttons, tags, chips |
| `--accent-2-ink` | `#141414` | text on `--accent-2` |
| `--match` | `#ffe600` | the letters a query matched, inside a title |
| `--match-ink` | `#141414` | text on `--match` |
| `--danger` | `#e85d04` | a breached condition, a failed model, a miss |
| `--danger-ink` | `#fff` | text on `--danger` |
| `--ok` | `#ffe600` | a year whose manual is ready, a part in stock |
| `--ok-ink` | `#141414` | text on `--ok` |
| `--shim` / `--shim-hi` | `#f1ece1` / `#e2dccd` | a skeleton row and the band crossing it |
| `--sweep` / `--sweep-page` | `color-mix` of `--accent` at 16 % / 10 % | the loading sweeps; they follow the accent on their own |
| `--shadow` | `rgba(20,20,20,.5)` | the veil under a sheet |
| `--glass` | `rgba(20,20,20,.42)` | the blurred chip over the 3D stage |
| `--focus` | `#e85d04` | the focus ring |
| `--theme-swap` | `180ms` | the crossfade |

### paper — never themed

| token | value | where |
| --- | --- | --- |
| `--page` | `#fff` | the PDF sheet, and any manual diagram behind it |
| `--page-ink` | `#141414` | line art printed on paper |
| `--page-tint` | `#f6f2e9` | the frame behind part photography |
| `--page-wait` | `#ece7dc` | a page-shaped hole that has not painted yet |
| `--highlight` | `rgba(232,93,4,.34)` | the marker, `mix-blend-mode: multiply` over the page |

A printed page is white in a garage and white at night. Product rule 2 says the manual **is** the
answer, so themes dress the app around the page and never touch it — including the marker, which
has to stay legible orange on white in all five. `css/particons.css` keeps `--part-icon-tile` /
`--part-icon-edge` light for the same reason: part icons are line art and vanish on a dark tile.

### stage — read by `js/viewer3d.js`, not by CSS

| token | Workshop | where |
| --- | --- | --- |
| `--stage` | radial paper gradient | the 3D panel's ground (CSS) |
| `--stage-fg` | `#141414` | the loading percentage printed on it (CSS) |
| `--stage-track` | `rgba(20,20,20,.16)` | the loading ring's unfilled track (CSS) |
| `--grid` | `#b6bcc4` | exploded-view grid lines (**JS**) |
| `--grid-bg` | `#1a1f24` | exploded-view backdrop (**JS**) |

### legacy aliases

`--ink`, `--paper`, `--orange` and `--yellow` still resolve (`--ink: var(--fg)` and so on) so that
files outside `css/` — `css/voice-orb.css`, and anything another agent writes — keep working. New
rules should use the semantic names: `--ink` was doing three different jobs (text, border, dark
slab) that a dark theme has to be able to tell apart, which is why it is now `--fg`, `--line` and
`--slab`.

## Contrast

`node web/tools/theme-contrast.mjs` reads the values straight out of the two stylesheets and
fails the build if any pair outside Workshop misses its target (4.5:1 for text, 3:1 for large or
structural). Workshop is reported but not enforced — the brief pins it pixel-identical.

| text on ground | need | workshop | night | blueprint | track | paper |
| --- | --- | --- | --- | --- | --- | --- |
| `--fg` on `--bg` — body text on the ground | 4.5 | 14.94 | 15.14 | 13.49 | 17.45 | 21.00 |
| `--fg` on `--card` — row and card text | 4.5 | 18.42 | 12.97 | 11.09 | 15.58 | 21.00 |
| `--muted` on `--card` — labels, specs, placeholders | 4.5 | 3.76 ⚠ | 6.72 | 6.57 | 6.65 | 8.72 |
| `--muted` on `--bg` — meta on the ground | 4.5 | 3.05 ⚠ | 7.85 | 7.99 | 7.45 | 8.72 |
| `--muted-2` on `--card` — years, spans | 4.5 | 5.70 | 9.14 | 8.82 | 10.14 | 15.13 |
| `--faint` on `--card` — placeholder and ghost art | 3 | 2.70 ⚠ | 4.02 | 3.89 | 3.85 | 5.02 |
| `--slab-fg` on `--slab` — the reader bar, primary button | 4.5 | 18.42 | 17.08 | 15.81 | 21.00 | 21.00 |
| `--accent-ink` on `--accent` — MECHANICA on the ticket bar | 4.5 | 3.50 ⚠ | 7.41 | 9.17 | 13.02 | 5.89 |
| `--accent-2-ink` on `--accent-2` — every `.btn` label | 4.5 | 14.54 | 13.06 | 15.13 | 6.38 | 18.76 |
| `--match-ink` on `--match` — the letters a query matched | 4.5 | 14.54 | 13.06 | 15.13 | 13.02 | 21.00 |
| `--ok-ink` on `--ok` — a year whose manual is ready | 4.5 | 14.54 | 13.06 | 15.13 | 13.02 | 5.47 |
| `--danger-ink` on `--danger` — the 3D retry stamp | 4.5 | 3.50 ⚠ | 7.41 | 7.90 | 6.38 | 5.89 |
| `--accent` on `--card` — chapter numbers, shop names | 3 | 3.50 | 5.86 | 6.86 | 11.54 | 5.89 |
| `--accent-2` on `--slab` — the page count on MANUAL | 3 | 14.54 | 13.69 | 17.58 | 6.75 | 18.76 |
| `--line` on `--bg` — the 3 px rule on the ground | 3 | 14.94 | 3.90 | 4.65 | 3.90 | 21.00 |
| `--line` on `--card` — the 3 px rule on a card | 3 | 18.42 | 3.35 | 3.83 | 3.48 | 21.00 |
| `--page-ink` on `--page` — the manual itself | 4.5 | 18.42 | 18.42 | 18.42 | 18.42 | 18.42 |

**The four ⚠ are pre-existing Workshop values, not regressions**, and every one of them is fixed
in the other four themes. White on `#e85d04` is 3.50:1 (`MECHANICA`, the stamps, the retry badge)
and the warm greys run 2.7–3.8:1 against paper. Changing them would change the shipped look, which
this pass was told not to do. If the founder wants Workshop to reach AA, the whole fix is four
token values in `counter.css`: `--accent-ink: #1a0a00`, `--muted: #6f6857`, `--faint: #8a8375`,
`--danger-ink: #1a0a00`.

## Verification

Both tools are headless Chrome against the local `web/` tree with `/api/*` proxied to the live
worker, so the walk runs on real manuals with local CSS.

- `node web/tools/theme-shots.mjs` — walks **landing · cards · chooser · confirm · pick · book ·
  parts · chat · conditions · #cost** at **390×844** and **1280×800** for each theme, asserts the
  theme actually applied and that the console is silent, and writes `docs/ui-themes/<id>.png`.
  **Result: 5 themes × 2 viewports × 10 stops = 100 screens, 0 console errors.**
  `--base <dir>` pixel-diffs every stop against a saved run.
- `node web/tools/theme-switch-test.mjs` — 29 assertions on the switch: cycle order, the disc
  previewing the next theme, the 44 px target, `theme-color`, storage, survival across a reload
  with no Workshop frame, the dark-system first visit and a stored choice beating it, the 180 ms
  arm/disarm, reduced motion skipping it, the `mechanica:theme` event and its tokens, and that
  `--page` / `--highlight` never move. **Result: all green.**
- `node web/tools/theme-contrast.mjs` — the table above. **Result: every non-Workshop pair passes.**
- `node --check web/counter/js/theme.js` — clean.

### Workshop is still Workshop

The token pass was diffed pixel-by-pixel against a screenshot run taken before the first edit.
The only systematic differences across all twenty screens are:

1. the new theme disc in the ticket bar (~420 px, intended);
2. four accidental greys folded onto the three-step ramp — `#9d9788` and `#b5ae9e` → `--faint`
   `#a49d8d`, `#8d8778` → `--muted` `#8a8375`, `#7a7468` → `--muted-2` `#6c665a`. Each is a
   sub-3 % shift on a placeholder, a ghost outline or a dead year chip. They were four different
   agents' idea of the same grey; they are now one.

Everything else that moved between runs was the live API returning different bike photos and
different `#cost` figures.

## Follow-ups, with owner

1. **`js/viewer3d.js` — 3d agent.** The exploded-view backdrop is a `ShaderMaterial` and cannot
   read CSS, so four colours there still stay Workshop-orange in every theme. Read them from the
   tokens instead (`getComputedStyle(document.documentElement).getPropertyValue(...)`), and
   re-read them on `window.addEventListener("mechanica:theme", …)` — `e.detail.tokens` already
   carries `accent`, `grid` and `gridBg`:

   | line | now | token |
   | --- | --- | --- |
   | `const ORANGE = 0xe85d04` (~72) | hard-coded | `--accent` |
   | `uInk: new THREE.Color(0x1a1f24)` (~1023) | the grid backdrop | `--grid-bg` |
   | `uLine: new THREE.Color(0xb6bcc4)` (~1024) | the grid lines | `--grid` |
   | `uAccent: new THREE.Color(ORANGE)` (~1025) | the horizon tint | `--accent` |
   | `hl.color.lerp(new THREE.Color(ORANGE), 0.18)` (~1843) | the highlight tint | `--accent` |

   Optional, lower value: `color: 0x9fa2a6` (~1120, the concrete env material) → `--muted`, and
   `color: 0x6f7885` (~1878, the x-ray material) → `--grid`. The HDRI environments, the lights
   and the generated sky gradient (~1199) must **not** follow a theme — they light the model, and
   tinting them would recolour the vehicle.

2. **`js/chat-ui.js` — chat-ui agent.** `INK/PAPER/ORANGE/YELLOW/CARD` are five hard-coded hex
   constants (~lines 53–57) handed to `<deep-chat>` as `auxiliaryStyle` / `messageStyles`, so the
   transcript inside its shadow root stays Workshop-coloured in every theme — visible as the pale
   panel in the `chat` cell of all five contact sheets. Custom properties **do** cross a shadow
   boundary, so the whole fix is `const INK = "var(--fg)"` etc., except for the handful of places
   deep-chat needs a real value. The chrome around it (`css/chat-ui.css`) is already tokenised.

3. **`counter/sw.js` — sw agent.** `css/themes.css` and `js/theme.js` are not in `PRECACHE`.
   Both are shell files and are network-first with runtime caching, so they are cached after one
   online visit and nothing is broken today; adding the two lines just makes the first offline
   load match the rest of the shell.

4. **`css/voice-orb.css` — voice agent.** The five names that file was told to build on —
   `--accent`, `--fg`, `--bg`, `--card`, `--rule` — all exist and are themed; the orb needs no
   change to follow a theme. What it actually uses today is the legacy `--ink` / `--orange` /
   `--paper` aliases, which resolve correctly in all five themes, so nothing is broken. Worth
   moving to `--fg` / `--accent` / `--bg` next time that file is open, since `--ink` on a dark
   theme means "light text", which is not what the name suggests.

5. **`css/screens/cost.css` — cost agent.** `.cost-lab` is a plain `--accent-2` fill with no rule
   around it, so in Paper (where `--accent-2` is near-white on a white card) the labels read as
   small caps rather than as chips. Nothing is illegible; it is simply quieter than elsewhere.
   One `box-shadow: inset 0 0 0 2px var(--line)` would fix it, at the cost of changing Workshop.

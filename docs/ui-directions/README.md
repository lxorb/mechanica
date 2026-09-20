# Mechanica — five UI directions

Five static previews, one file each. Every file shows the **same four screens** at 390×844 plus a 1280 desktop frame of
the landing, so they compare fairly: 1 find the bike (search → photos → year, or camera → "is this it?"), 2 find the part
(sticky 3D + search over chapters), 3 the manual (relevant pages, marker, toggle to all 143), 4 ask (the manual answers,
with page citations).

All strings, pages and specs are real: `api/manuals/ktm-390-duke-2024-om-en` — *OWNER'S MANUAL 2024 390 DUKE*, 143 pp.,
`13 BRAKE SYSTEM · 13.4 Checking the front brake fluid level · p. 84`. Photos are `web/store/img/bikes/*.webp`, the
exploded model is the real viewer render, the page is the real rendered PDF page (greyscaled so each direction can put
its own marker on the real highlight coordinates from the manual JSON).

| # | file | shot |
| --- | --- | --- |
| 01 Torque | [01-torque.html](01-torque.html) | [shots/01-torque.png](shots/01-torque.png) |
| 02 Shop Ticket | [02-shop-ticket.html](02-shop-ticket.html) | [shots/02-shop-ticket.png](shots/02-shop-ticket.png) |
| 03 Plate | [03-plate.html](03-plate.html) | [shots/03-plate.png](shots/03-plate.png) |
| 04 Grip | [04-grip.html](04-grip.html) | [shots/04-grip.png](shots/04-grip.png) |
| 05 Index | [05-index.html](05-index.html) | [shots/05-index.png](shots/05-index.png) |

## Comparison

| direction | mood | one line that makes it different | best for | risk |
| --- | --- | --- | --- | --- |
| **01 Torque** — carbon / amber / redline, Saira Condensed italic | pit wall, 06:00, engine warm | the chrome is an instrument and the page is the readout it points at | riders who already read tachometers; looks instantly "motorcycle" in a store listing | carbon + amber is the default costume of every bike app; an instrument is a live gauge, a manual page is not |
| **02 Shop Ticket** — warm stock / black label strips / blueprint grid, Courier data | job card on the bench | interface and document are made of the same material, so the PDF never looks pasted in | workshops, printouts, anything that ends up on paper | closest to what already ships, so it reads as a refinement not a change; light UI at night |
| **03 Plate** — black / ivory / one ultramarine, Archivo plates + Instrument Serif | a magazine about your machine | the page number is the biggest object on screen because the page number *is* the answer | the demo, the store, screenshots; photography does the selling | editorial restraint at 390 px is unforgiving, and it is the coldest of the five |
| **04 Grip** — deep green / cream tiles / lime + tangerine, Bricolage Grotesque | a tool, gloves on | the only direction where motion explains the product: a lime pill leaves the 3D part and lands on the list row | one-handed use, gloves, sunlight, first-time users | friendly reads as unserious beside an official document; most colour spent of the five |
| **05 Index** — white / 1px black rules / Swiss red, Inter Tight only | a specification sheet | the manual's table of contents is not styled into the app, it *is* the app | shipping fast; scales to 300-section ingested manuals without layout work | no personality by design; pure white is hostile in a dark garage — needs a dark mode the others get free |

## Recommendation

1. **03 Plate** — ship it: the only direction whose structural device *is* the promise. The page number set at 46–112 px
   explains the product before a word is read; dark for the garage, photography-led, and it costs one font file.
2. **02 Shop Ticket** — strongest idea (interface and document, same material) and the best marker: wax yellow, red
   margin bars, relevant pages as index tabs off the sheet. Fallback if Plate tests cold; needs a dark variant.
3. **04 Grip** — don't ship whole, steal one thing: the lime chip that travels from the 3D part onto its list row, which
   is what makes step 2 feel caused. Its 54–62 px targets are the right floor for whichever direction wins.
4. **05 Index** — the cheap, correct answer if time runs out. Scales to 300-section manuals for free. Unmemorable.
5. **01 Torque** — most "motorcycle", most templated. One idea survives: the redline tick on the last marked line.

Build order if Plate wins: Plate's grid and page plates + Shop Ticket's index tabs + Grip's part-to-row chip and target
floor. Nothing else crosses over.

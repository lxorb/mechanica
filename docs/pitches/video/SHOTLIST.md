# Demo video — shot list

Two takes, recorded on the live site (https://mechanica.emilvinu.ch/counter/) in headless Chrome
at 1280×720, 24 fps. **No narration and no captions** — the presenter talks over it, and
every beat below is a timestamp to talk to or to seek to. Re-record with
`node web/tools/demo-video.mjs` (`--dry` drives the path without recording;
`TTM_TRACE=1` prints how long each wait really took).

Each take ships three files plus its table below: `<take>.mp4` (H.264), `<take>.webm` (VP9) and
`<take>-sheet.png` — twelve labelled frames, 4×3, so a judge can see the whole take without
playing it.

**Which file to hand over: the `.mp4`.** It is encoded at a true 6.5 Mbps CBR, which is the
high-bitrate master the submission asks for, and it plays everywhere. The `.webm` is the same
pictures at VP9 CRF 8 — visually the same, a fifth of the size, and its *measured* bitrate is
around 1 Mbps rather than 6, because a mostly-still UI simply does not need more and libvpx,
unlike x264's `nal-hrd=cbr`, has no mode that pads a frame up to a rate. Quoting 6 Mbps for the
WebM would be quoting a setting, not a file.

## How to use it in a 5-minute pitch

`general.md` is the script. Take 1 is the demo it describes, in the same order, minus the
voice turn. Take 2 is the 0:20 beat — the manual that does not exist yet — played in full
instead of left running in the background. If you only have one screen, play take 1 and cut to
take 2 at the "So the catalogue isn't the limit" line.

## Beats that are not in these takes, and why

| beat | why not |
|---|---|
| **Voice mode** (tap the mic, speak, it reads the manual back) | It needs microphone permission and a live audio input. Headless Chrome has neither: `stt.supported` is false, so the mic button hides itself and there is nothing on screen to film. The Deepgram turn has to be demoed live, or captured on a real phone. |
| **Photo identify** (snap the bike, /api/identify/photo) | The file input opens the OS camera/file picker, which is outside the page and cannot be recorded from inside it. `identifyPhoto` itself is exercised in the QA harness, not here. |
| **VIN scan** | Same picker problem for the camera path. Typing a VIN into the same field does work and could be added as a third take if a judge asks. |
| **Offline** (aeroplane mode, the pages already opened still open) | Nothing moves on screen, so a video is the worst way to show it. Demo it live by killing wifi. |

Everything else in `general.md` is in take 1, in the same order. Neither take is edited: both ran
straight through on the live site and the timestamps below are wall-clock. Two things in the
recorder are synthetic and worth knowing if anyone asks: the smooth scrolls are animated inside
the page (a synthetic wheel event scrolls in jerky notches and looks wrong on camera), and the
book's zoom arrives as the ctrl+wheel event its pinch handler already listens for. Every click,
every keystroke and every answer is the real UI against the deployed API.

<!-- takes -->

## Take 1 — the product path

**01:26** · 1280×720, 24 fps, no audio.
`take-1-product.webm` (VP9, 1.2 Mbps, 13.0 MB) · `take-1-product.mp4` (H.264, 6.5 Mbps, 69.9 MB) · `take-1-product-sheet.png` (12 frames).

| time | beat | what is on screen |
|---|---|---|
| **00:00** | Landing | one search field, 29,890 vehicles behind it |
| **00:05** | Model cards | photo cards while the query is still ambiguous |
| **00:09** | Confirm | KTM 390 DUKE 2024 — the hero photo and the manual it carries |
| **00:13** | Pick | the manual's own twenty sections, while the bike loads onto the stage |
| **00:19** | The manual's own headings | 12.12 p.77–78 and 12.13 p.78 — KTM's section numbers, not ours |
| **00:22** | Exploded view, chain lit | the bike explodes and the drive chain lights under the top heading |
| **00:30** | Page 77 of KTM's manual | the printed page, orange markers on the two answering lines |
| **00:34** | The marked lines | measure the chain tension · Chain tension 7 … 10 mm (0.28 … 0.39 in) |
| **00:40** | All pages | 143 sheets — the whole book, when he wants it |
| **00:45** | Parts | 135 parts, each one on the list because the manual prints a spec for it |
| **00:52** | Drive chain | Chain · 5/8 x 1/4" (520) X-ring · p.126 · live USD offers |
| **01:01** | Chat | the one place it may write a sentence — and only with page numbers in it |
| **01:09** | The answer, with its page | Rear wheel spindle nut: 100 Nm (73.8 lbf ft) [p. 130] + the p.130 chip |
| **01:14** | Theme · night | a theme is colours and nothing else; every screen keeps working |
| **01:16** | Theme · blueprint | a theme is colours and nothing else; every screen keeps working |
| **01:23** | Back to the search field | one field, and the next bike |

## Take 2 — a manual nobody had indexed

**01:35** · 1280×720, 24 fps, no audio.
`take-2-ondemand.webm` (VP9, 0.7 Mbps, 8.5 MB) · `take-2-ondemand.mp4` (H.264, 6.5 Mbps, 77.1 MB) · `take-2-ondemand-sheet.png` (12 frames).

| time | beat | what is on screen |
|---|---|---|
| **00:00** | Landing | a bike the app has never fetched a manual for |
| **00:04** | Cards, cold and warm | the flag on each card says whether a manual is already indexed |
| **00:08** | Every year Yamaha built it | orange chips are indexed, outlined chips are not |
| **00:11** | Confirm · Yamaha MT07 2018 | no manual on our servers, four minutes ago or ever |
| **00:13** | The fetch starts | Yamaha's own PDF, pulled and read for the first time |
| **00:27** | Progress 25% | Yamaha MT-07 2018 — 15 s in |
| **00:29** | Progress 50% | Yamaha MT-07 2018 — 17 s in |
| **00:46** | Progress 75% | Yamaha MT-07 2018 — 33 s in |
| **01:16** | Progress 95% | OWNER’S MANUAL MT07J MT07JC — 64 s in |
| **01:20** | Searchable | 63.8 s from tap to a manual with an index |
| **01:25** | A question against a manual that was cold | Yamaha's own headings, on a book nobody had indexed |
| **01:32** | The page | the same printed page, out of a PDF that was not on our servers a minute ago |

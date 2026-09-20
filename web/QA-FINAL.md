# QA-FINAL — Mechanica, live, 2026-09-20

Headless Chrome on https://mechanica.emilvinu.ch/counter/, 390×844 and 1280×800. Shots: `docs-shots/final-*.png`.
**Zero console errors and zero failed requests on every online step of every run below.**

## Passed
- **Landing** `390` → 60 model cards with photos · `2024 390 duke` jumps to Confirm · `2023 yamaha yzf` → 15 cards, stays · `corvette` → one CHEVROLET CORVETTE 1999–2027 card · VIN `VBKJSA40XXXXXXXXX` → KTM 390 Duke 2024, `1G1YA2D40P5100001` → Chevrolet Corvette 2023 · photo → Confirm in 5.0 s with 8 alternatives · Back pops photo → query → landing · API blocked: roster still finds 390 Duke, Corvette and Camry.
- **Confirm** hero 360×237 on the phone · a hand-tapped *ready* year goes straight to Pick (by design) · on-demand KTM 390 Duke 2015 → real bar 0 → 96 % under the printed cover title, Pick in **66 s** (2016: 55 s) · a *none* year (Kawasaki ELEKTRODE) → Manual → PDF upload fallback in 0.7 s.
- **Pick** sticky stage, canvas 720×702 @dpr 2, no placeholder ever · model map right: 390 Duke → `generic/naked` tinted `#ff6600`, YZF-R7 → `yzf-2021`, CBR650R → `honda-cbr650r`, Corvette → `corvette-c8`, BMW C 400 GT → `generic/scooter`, 450 SX-F → `generic/motocross` · typing explodes · search repaints in **10–27 ms**, `sproket` → *Checking the chain, rear sprocket…* · topic→part: brake fluid → front-brake, chain → chain, tyre → front-wheel, oil → engine · MANUAL → Book p.118 · mic + part-camera present.
- **Book** KTM p.84 markers (84:1, 85:4, strip 84·85) · BMW F 900 R *Chain* p.189–192 · immersive tap folds the bar to 0 px · All-pages 128/128 drawn (BMW 288) · Contents 238 rows · Parts = 143 parts in 10 system groups with illustrations, search `oil`/`pads`/`sproket` · offers in USD, **0.5 s warm** · Back closes parts → book → pick.
- **Chat** full-screen 844/844 · "how do I change the brake fluid" → general steps + DOT 4 / DOT 5.1 **[p. 118]** + chips, no dealer language · "how much oil" → 1.7 l (1.8 qt.) **[p. 111]** · "how do I wheelie" → *Not in this manual.* · chips open Book · **Voice** beside send → `wss://…/ws/deepgram/agent`, Welcome → SettingsApplied → greeting, **96 binary frames / 92 KB in 2.1 s**, level meter, stop.
- **#cost** 8.9279 total · 0.0687 per ask · 12.4000 naive · 1633 calls · manifest standalone, `#e85d04`, 5 icons, sw active and controlling.
- **Fast 4G + 4× CPU, cold cache:** landing **237 KB / 55 requests**, FCP 0.9 s, field usable 10.2 s; Pick ready **+1.6 s**, 102 requests total.

## Fixed (deployed)
- `counter/js/screens/cost.js` — every `#cost` cell showed `—`. The paint was gated on a generation counter that `close()` also bumps, so one stray route event dropped the only answer. It now paints whenever the meter is on screen. Verified live after one reload.
- Diagnosed the chat regression: `css/climate.css` reused chat-ui's `.cv-*` names and, loading later, forced `.cv-sheet{max-height:min(86dvh,860px)}` and `.cv-title{flex-direction:column}` — the drawer was 726 of 844 px with Pick showing underneath. The climate agent's `cv-*` → `cf-*` rename landed mid-fix, so I reverted my scoping and shipped theirs. Live is 844/844, header back in one row.

## Open, with owner
1. **3D part groups — 3d/vehicle-models.** Measured live: yzf-2021 16 groups, honda-cbr650r 14, corvette-c8 12, generic/sportbike 16, motocross 13, **naked 7**, supermoto 5, and **scooter · car · adventure · classic · enduro · touring · cruiser = 1 catch-all**. So on `generic/naked` — the KTM 390 Duke, the demo bike — there is no `chain` or `front-brake` group: tapping a chain/brake heading lights nothing and does not refit the camera (mean pixel change after focus: 3.3/255). On the seven single-group models nothing explodes at all: every non-Corvette car and every scooter. *Repro: Pick `ktm-390-duke-2023`, type `brake fluid`, tap row 1.*
2. **Photo ID — identify-backend.** `POST /identify/photo` with `store/img/bikes/ktm-390-duke-hero.webp` returns 8 candidates, all **KTM 690 Duke** years at 0.98. The flow is right; the model names the wrong model and every alternative is a year of that same one.
3. **Voice needs a microphone — voice.** `voice-deepgram.js::run()` awaits `getUserMedia` *before* opening the socket, so with no mic (or a denied prompt) nothing connects and the drawer only says "Voice unavailable." With `--use-fake-device-for-media-stream` it is perfect. *Repro: launch Chrome without a fake device, tap VOICE.*
4. **Offline reload after a manual — sw/adapter.** Shell, fonts and the search field come back offline, but the reload lands on **Identify with 0 sheets**: `state.bikeId` is not persisted, so `firstGo()` bounces. *Repro: open a marked page, go offline, reload.*
5. **Cold parts offers 15.4 s** (BMW F 900 R engine oil) against the ≤ 8 s target; warm is 0.5 s — offers.
6. **Conditions overlay is top-anchored** (top 0, 202 px, over the Book bar) because its `<aside>` is still `class="ov cv"` and chat-ui's `.cv{justify-content:stretch}` reaches it. One word: `"ov cf"` — climate.
7. **BMW p.189 has no markers** when opened from the outline row *Chain p.189–192*; the indexed rows do (*Chain deflection* p.191, *Check the chain tension* p.190) and rank above it. Chapter rows open marker-free by design — step-3/ask, if outline rows should rank below marked sections.
8. **No Vespa in the roster** — scooter typing verified on BMW C 400 GT instead — registry.

Book (`screens/book.js`, `book.css`, `pdf.js`) was under another agent during this pass and was tested, not edited; nothing blocking found there.

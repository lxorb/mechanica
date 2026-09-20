# Demo — 3 minutes

**https://mechanica.emilvinu.ch** · four steps: **1 Identify → 2 Confirm → 3 Pick → 4 Book.**
Every page number below was returned by the live API on 2026-09-20. Do not improvise a question.

## The bikes

| role | bike | manual id | pages · sections | state |
|---|---|---|---|---|
| main | **KTM 390 Duke 2024** | `ktm-390-duke-2024-om-en` | 143 · 20 | warm — the demo bike, a hand-curated 20-section index, so every scripted question lands |
| second brand | **BMW R 12 G/S 2026** | `bmw-r-12-g-s-2026-eu-om` | 270 · 237 | warm |
| the 3D one | **Honda CBR650R 2023** | `honda-cbr650r-2023-us-om` | 143 · 142 | warm — the only bike whose 3D model *is* that bike |
| on-demand | **Yamaha MT-07 2018** (any chip with no manual yet) | — | — | **cold on purpose** |
| on-demand fallback | Yamaha MT-07 **2019** / **2020** | `yamaha-mt07-2019-eu-om` | 100 · 91 | warm, fetched on demand in 44 s at 05:40 |

**Measured on-demand against the live API, timed 2026-09-20** (KTM 390 Duke 2014, 182 p): the manual is
**readable in 1.3 s** (PDF + contents) and **fully searchable in 40.4 s**. That run cost **$0.089**; the mean
over 648 real ingests is **$0.095**.

**Traps.** The BMW R 12 G/S is **shaft drive** — "chain is loose" returns *BATTERY GUARD* p.150, which is
correct and looks broken. Chain questions go to the KTM. Avoid **Honda US years before 2023**: the PDF
opens but structuring returns 0 sections (measured on `honda-cbr650r-2022`). KTM, BMW and Yamaha EU are the
verified on-demand portals. The KTM and BMW headers show the **printed cover title**; the Yamaha shows a
derived one.

## Before you walk up

1. `curl https://mechanica.emilvinu.ch/api/health` → `{"ok":true}`.
2. Open the site once on the demo phone: that caches the shell, fonts, roster and pdf.js (service worker v7).
3. Run every scripted question once. A repeat is served from the answer cache in **0.2–0.4 s at $0** instead
   of 1.5–3.5 s.
4. Open the KTM and the BMW to page 1 so both PDFs are in the cache.
5. `#cost` ready in a second tab. Phone in portrait, screen mirrored.

## The script

Start the slow thing first and talk over it.

| clock | you do | on screen | you say |
|---|---|---|---|
| 0:00–0:15 | type `mt-07`, tap the model card, tap a **year with no manual yet**, Confirm → **Yes** | progress bar starts | "A friend runs a motorcycle shop. He won't let AI near it — it's right 95% of the time, and the 5% is where a liable mechanic gets burned." |
| 0:15–0:25 | Back to the landing, type `390 duke`, tap the card, tap **2024** | model cards with photos, year chips, then Confirm | "So we never let it answer. Pick your exact bike — 30,409 of them: 24,026 motorcycles and 6,383 cars." |
| 0:25–0:45 | **Pick.** Type `chain` | the 3D bike explodes, the chain lights orange, and the manual's own headings rank under it: *Checking the chain tension* p.77–78, *Adjusting the chain tension* p.78 | "Those aren't our words. That's KTM's table of contents, and the part it's talking about." |
| 0:45–1:05 | tap the first heading → **Open** | p.77, orange markers on the tension lines, page strip 77 · 78 · 79 | "Page 77 of KTM's own manual. The marker is on the lines that answer him — and it's only there because we found that exact text in the PDF." |
| 1:05–1:15 | tap the **all-pages** toggle, then the cover glyph | 143 sheets, then the Contents outline | "The whole manual is here when he wants it. By default he only gets the pages that answer." |
| 1:15–1:25 | tap **Parts** | icon, part name, the grade the manual prints, the page, OEM number, RevZilla / Partzilla / Amazon | "Every part is on that sheet because the manual prints a spec for it. Not because a model guessed what fits." |
| 1:25–1:50 | close, tap **Chat**, ask `chain is loose, what do I do` | numbered steps, every sentence ending in a `[p. 77]` / `[p. 78]` chip; footer shows tokens saved | "This is the one place it writes a sentence — and it can only write page numbers. The quotes are sliced out of the page by the server, so they're verbatim by construction." |
| 1:50–1:55 | tap a `[p. 78]` chip | Book jumps to p.78 | "Every claim is one tap from the ink." |
| 1:55–2:15 | Back to the landing → the MT-07 is **ready** → Pick → type `oil` → Open | p.58–60 *Engine oil and oil filter cartridge* | "That manual did not exist on our servers two minutes ago. Any of 14,865 free official manuals, fetched, parsed and searchable in under a minute, for ten cents." |
| 2:15–2:35 | open `#cost` | total · per ask · naive per ask · calls | "Four hundredths of a cent an ask. Pasting the whole manual into the prompt is twelve dollars forty." (Don't quote a running total off this screen — it moves every hour.) |
| 2:35–3:00 | back to the marked page | the page | "There is no AI-written sentence on this screen. The manual is the answer. We just get you to the page." |

**Spare questions, all verified live**

| bike | question | lands on |
|---|---|---|
| KTM 390 Duke 2024 | `chain is loose` | p.77–78 *Checking the chain tension*, p.78 *Adjusting the chain tension* |
| KTM 390 Duke 2024 | `what torque for the rear axle` | p.128–130 *Chassis tightening torques*, p.78 *Adjusting the chain tension* |
| KTM 390 Duke 2024 | `front axle nut torque` | p.128–130 *Chassis tightening torques* — the printed figure is **45 Nm** |
| KTM 390 Duke 2024 | `how much oil does it take` | p.114–116 *Changing the engine oil and oil filter* |
| KTM 390 Duke 2024 | `how do I check the engine oil level` | p.114 *Checking the engine oil level* |
| KTM 390 Duke 2024 | `what pressure should the tyres be` | p.95 *Checking tire pressure* |
| KTM 390 Duke 2024 | `how do I check the brake pads` | p.86 *…front brake…*, p.88–89 *…rear brake are secured* |
| BMW R 12 G/S 2026 | `how do I check the engine oil level` | p.164 *Checking engine oil level*, p.165 *Topping up engine oil* |
| BMW R 12 G/S 2026 (chat) | `what tyre pressure two up with luggage` | "2.5 front, 2.7 rear, cold **[p. 216]**" |
| Honda CBR650R 2023 | `chain is loose` | p.95 *Inspecting the Drive Chain* |
| Honda CBR650R 2023 | `how do I check the brake pads` | p.92 *Inspecting the Brake Pads* |
| Yamaha MT-07 2019 | `chain is loose` | p.71 *Drive chain slack* |

## If it goes wrong

| what breaks | what you do |
|---|---|
| **No network** | Keep going. The service worker serves the shell, fonts, roster, chapters and any PDF page you opened before. Steps 1–4 still work on the cached bikes; the 3D model, chat and `#cost` do not. Say "and this is the part he actually cares about — it's on the phone." |
| **API slow** | Every scripted question was pre-run, so it comes back from the answer cache in 0.2–0.4 s. Never type a question that is not in a table above. |
| **On-demand stalls past ~60 s** | Back out and use the MT-07 **2019** or **2020** — both warm. Say "we already have 543 of these cached; that one was a cold fetch." |
| **The 3D model doesn't load** | It never blocks: the Pick screen paints a schematic assembly first and explodes and highlights the same way. Carry on; the GLB swaps in when it lands. |
| **Judge asks "is that the real bike?"** | Honest answer: three Sketchfab models (Yamaha YZF as the generic bike, Honda CBR650R, a Corvette), Draco-compressed, credited in `web/store/models/CREDITS.md`. Pick the **CBR650R 2023** and it is that bike. It is a part *locator*, not a manufacturer parts catalogue. |
| **Judge asks about voice / Dropbox** | `GET /api/voice/config` returns `{"elevenlabsAgentId": null, "deepgram": true}`. **Deepgram voice is live** — the VOICE button works, median 2.08 s from end of speech to first audio. **ElevenLabs is built but needs a key**, so its button does not render; never claim it is live. The Dropbox **chooser** needs `TTM_DROPBOX_APP_KEY` and the folder **sync** is built and deploying (`/api/dropbox/*` is not in the live OpenAPI yet); the upload path `POST /api/ingest/upload` is live. |

## Part photo → part (only if asked)

Not wired into any screen. Demo it from a terminal:

    curl -F file=@chain.jpg https://mechanica.emilvinu.ch/api/identify/part
    # -> [{"label":"chain","confidence":0.9},{"label":"chain_sprocket",...}]

30 labels, zero-shot, $0.00024 a photo. Each label maps to the manual query it answers.

---

# Video — 2 minutes

| # | shot | on screen | voice-over |
|---|---|---|---|
| 1 | Dirty hands thumbing a thick paper manual, close, shallow | pages flipping, none of them right | "Every answer he needs is already printed. It just takes five minutes to find." |
| 2 | One-handed typing on the landing | `390 duke` → model cards with photos | "Pick your exact bike." |
| 3 | Pick screen fills the frame | the 3D bike explodes, the chain lights orange as `chain` is typed | "Say what's wrong. It shows you the part — and the manual's own heading for it." |
| 4 | Screen fills the frame as the page renders | KTM p.77, marker sliding over the tension lines. Hold. | "That's page 77 of KTM's manual. Nothing rewritten." |
| 5 | Chat drawer, answer streaming | numbered steps, `[p. 77]` chips, tap one, the page appears | "When it does write a sentence, it may only write page numbers." |
| 6 | Back to the landing, a bike with no manual, progress bar, then the page | MT-07, 0 → 100%, p.58 | "Nearly fifteen thousand free official manuals. Any of them, on demand, in under a minute." |
| 7 | Cost screen | `0.0004` next to `12.40` | "Four hundredths of a cent a question. Reading the whole manual to a model is twelve dollars forty." |
| 8 | Pull out to the bike and the hands | the page, no UI chrome | "Don't trust the AI. Trust the manual — we just get you to the page." |

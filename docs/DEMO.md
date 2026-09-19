# Demo — 3 minutes

Two bikes, both indexed and bundled. Never demo anything else.

| bike | manual id | title on the cover | pages |
|---|---|---|---|
| **KTM 390 Duke 2024** | `ktm-390-duke-2024-om-en` | OWNER'S MANUAL 2024 390 DUKE | 143 |
| **BMW R 12 G/S 2025** | `bmw-r12gs-2025-rm-en` | RIDER'S MANUAL R 12 G/S | 268 |

**Trap: the R 12 G/S is shaft drive.** "chain is loose" on the BMW returns front-wheel removal and spring
preload — it is the one question that looks broken. Chain questions go to the KTM only. Everything below
was run against the live API and these are the pages it actually returned.

## Before you walk up

1. API up: `curl localhost:8010/health` → `{"ok":true}`.
2. Open the PWA, select **both** bikes and open one page of each manual — that puts both PDFs in the
   service-worker cache, which is what makes the offline fallback work on stage.
3. Ask each of the four scripted questions once. A repeated question is served from the answer cache in
   **0.23 s** instead of 2.5 s, and costs $0.
4. Phone in portrait, screen mirrored. Have `#cost` ready in a second tab.

## The script

| clock | you do | on screen | you say |
|---|---|---|---|
| 0:00–0:15 | hold the phone up | Identify screen | "A friend runs a motorcycle shop. He won't let AI near it — it's right 95% of the time, and the 5% is where a liable mechanic gets burned." |
| 0:15–0:30 | tap **Photo**, shoot the KTM (or a photo of one) | rows come back, KTM 390 Duke top, confidence bar | "So we never let it answer. It only finds the page." |
| 0:30–0:40 | tap **2024** | Ask screen, header reads *OWNER'S MANUAL 2024 390 DUKE* | "That's his exact bike and its exact manual — 143 pages." |
| 0:40–1:00 | type **`chain is loose`**, send | p. 77 *Checking the chain tension*, then p. 78 *Adjusting the chain tension*, orange marker on the lines | "Not a summary. That is KTM's page 77, and the marker is on the lines that answer him." |
| 1:00–1:20 | scroll one page, then type **`what torque for the rear axle`** | p. 128–130 *Chassis tightening torques* | "A number question skips the ranking model entirely and gets answered off the parsed spec table — that ask cost a hundredth of a cent." |
| 1:20–1:35 | back twice, pick **BMW R 12 G/S 2025** | Ask screen, *RIDER'S MANUAL R 12 G/S* | "Different brand, 268 pages, completely different vocabulary — BMW prints 'brake pad thickness', KTM prints 'brake linings'." |
| 1:35–1:55 | type **`I need to replace the front brake pads`** | p. 166 *Checking brake pad thickness, front brakes*, then p. 211 *THREADED FASTENERS* | "It found the check procedure and the torque table he'd need next. Nobody wrote either sentence — BMW did." |
| 1:55–2:10 | type **`how much oil`** | p. 213 *ENGINE OIL* (Technical data), then p. 165 *Topping up engine oil* | "The printed number first, the procedure second." |
| 2:10–2:25 | tap **Parts** | sheet: the consumables that page needs, each with the manual's printed grade, links to RevZilla / Partzilla / Amazon | "Every part is here because the manual prints a grade for it — not because a model guessed what fits." |
| 2:25–2:45 | open `#cost` | total · per ask · naive per ask · calls | "Four hundredths of a cent an ask. Putting the whole manual in the prompt would be $2.14. That's 1,500×, and our answer is a PDF page." |
| 2:45–3:00 | hold on the result screen | the marked page | "There is no AI-written sentence anywhere in this app. The manual is the answer. We just get you to the page." |

## If the network dies

Keep going — say "and this is the part he actually cares about" and carry on.

The PWA falls back automatically, per call, in `src/lib/source.ts`: `ask` → the client matcher over the
two bundled manuals (`src/data/manuals/*.json`, 20 sections and ~80 grounded highlights each), `loadManual`
→ the bundled JSON, `identifyVin`/`identifyPhoto` → the local catalog. The PDFs are served from
`public/manuals/` and cached `CacheFirst` by the service worker. What you lose: the router and picker (the
client matcher is keyword-only, so phrase it closer to the manual — `chain tension`, `brake pad`,
`engine oil`), the photo model, and the cost screen. What still works: both bikes, both manuals, every
page, every highlight, the Parts sheet. Type **`chain tension`** on the KTM and it lands on p. 77 anyway.

If the API is up but slow, the answer cache makes any question you pre-ran instant — this is why step 3
above exists.

## Part photo → chain (only if asked)

Not wired into the UI. Demo it from a terminal or `localhost:8010/docs`:

    curl -F file=@chain.jpg localhost:8010/identify/part
    # -> [{"label":"chain","confidence":0.9}, {"label":"chain_sprocket", ...}]

30 labels, zero-shot on `gpt-5.6-luna`, $0.00023 a photo. Each label maps to the manual query it answers
(`chain_sprocket` → "sprocket wear"), so the next step is the same page flow.

---

# Video — 2 minutes

Nine shots. No music over the voice. Every voice-over line below is the whole line.

| # | length | shot | on screen | voice-over |
|---|---|---|---|---|
| 1 | 0:00–0:12 | Hands, dirty, thumbing a thick paper manual in a workshop. Close, shallow. | Pages flipping past, none of them the right one. | "Every answer he needs is already printed. It just takes five minutes to find." |
| 2 | 0:12–0:22 | Phone raised to the bike, shutter. | Camera view of the 390 Duke, then the catalog row with the confidence bar filling. | "Point it at the bike." |
| 3 | 0:22–0:32 | Thumb types one sentence, one-handed. | Ask screen, *OWNER'S MANUAL 2024 390 DUKE*, the words `chain is loose` appearing. | "Ask it the way you'd say it out loud." |
| 4 | 0:32–0:47 | Screen fills the frame as the page renders. | KTM p. 77, the orange marker sliding over the tension lines. Hold. | "That's page 77 of KTM's own manual. Nothing rewritten." |
| 5 | 0:47–1:00 | Swipe to the BMW, type, page lands. | *RIDER'S MANUAL R 12 G/S*, `I need to replace the front brake pads`, p. 166. | "Different bike, different words, same promise." |
| 6 | 1:00–1:10 | Tap Parts, sheet slides up. | Part names with the manual's printed grades, three shop chips. | "The parts come from the page, not from a guess." |
| 7 | 1:10–1:22 | Airplane mode toggled on, question typed anyway. | Offline indicator, page still renders. | "It works with no signal, because the manual is on the phone." |
| 8 | 1:22–1:40 | Cost screen. | `0.0014` per ask next to `2.1440` naive. Hold on the two numbers. | "Reading the whole manual into a model costs two dollars a question. This costs a fiftieth of a cent." |
| 9 | 1:40–2:00 | Back to the marked page, pull out to the bike and the hands. | The page, the bike, no UI chrome. | "Don't trust the AI. Trust the manual — we just get you to the page." |

# Devpost submission — Mechanica

**Tagline**
Don't trust the AI. Trust the manual.

Live: https://mechanica.emilvinu.ch

Every number below is generated into [`docs/pitches/numbers.md`](pitches/numbers.md). Re-run
`cd api && .venv/Scripts/python tools/pitch_numbers.py --live --md ../docs/pitches/numbers.md`
before submitting and fix anything it flags — do not type a number that is not in that file.

## Inspiration
A friend who runs a motorcycle shop in Germany refuses to use AI: it is right 95% of the time, and the 5%
is where a liable mechanic gets burned. He says about 20% of his working time goes to looking for the right
page in a manual — roughly 400 hours a year — and when he tried an LLM, one question cost him about $4,
because the model had to read a 500-page manual, so he hit usage limits constantly. Those are his numbers,
not ours. The fix is not a better model: everything he needs is already printed in the manual. So we built
the thing that never answers.

## What it does
Pick your exact vehicle from **27,751** — 23,140 motorcycles and 4,611 cars — by typing it, photographing
it, or scanning the VIN. **13,537** of them already carry a free official manual. Never seen that bike? We
fetch its manual from the manufacturer: **readable in 1.3 seconds, fully searchable in 40 seconds, for nine
and a half cents.** **14,770** distinct free English PDFs are reachable; **535** are already indexed —
95,914 printed pages, 91,388 grounded sections.

Then say what is wrong, in the words a mechanic actually uses. A 3D model explodes and lights the part you
typed, next to the manual's own headings. Open one and you get the manufacturer's page, rendered as
printed, an orange marker on the lines that answer you — plus the whole manual, its real contents, and a
Parts sheet built only from specs the manual prints. Chat and voice are the one place words are generated,
and both are fenced: the model may only emit page numbers, and the server slices every quote out of the
original page, so citations are verbatim by construction.

## How we built it
A no-build vanilla PWA over FastAPI. PyMuPDF extracts the text layer with per-block coordinates; one cheap
LLM pass over 5-page windows turns a PDF into sections, specs and parts, and every quote is searched back
into that layer — a highlight can only sit on ink the manufacturer printed. At ask time a router rewrites
rider slang into manual vocabulary, BM25 ranks, and a picker returns validated ids only; spec questions skip
the picker entirely. bear-2 compresses each retrieved page before it is billed. Azure Blob is the system of
record, the API runs on Azure Container Apps, and a Cloudflare Worker serves the app, proxies `/api` and
holds the Deepgram key so no credential ever reaches the tab.

## Challenges
Making a model that cannot lie: ids only, validated; quotes grounded or dropped. Eighty-four publisher
portals, all different — one 401s if you send `Accept: application/json`, one is Akamai-fingerprinted and
needs a real browser over CDP. And compression that eats printed torque figures at 0.5 aggressiveness, so we
ship 0.3 and take 31% by deleting dealer boilerplate first instead.

## Accomplishments
Top-1 **100%** over the 130 in-scope queries of a 150-query eval, **0 of 20** off-topic questions answered,
p95 **3.33 s**, **$0.00038** an ask against **$12.40** to read the largest deployed manual naively.
**43 of 43** chat quotes verbatim on the page they name, **100%** of 48 claim sentences cited, **0** invented
numbers. 14,770 manuals reachable, none copied.

## What we learned
Constraining a model is cheaper than trusting it, in tokens and in liability. The hard part was never the
model — it was the portals and the PDF text layer.

## What's next
Service manuals: a rider's manual is free, a shop's is metered by the hour (182 service rows in our registry,
15 of them paid, subscription or dealer-login only, and we index none) — so we point at the shop's own
folder. Then parts checkout, and ten real workshops for a month.

## Built with
python · fastapi · pymupdf · openai · the-token-company · deepgram · elevenlabs · elasticsearch · three.js ·
pdf.js · deep-chat · dropbox · azure-blob-storage · azure-container-apps · cloudflare-workers

---

# Tracks we enter

One paragraph each. The full 5-minute pitch, the demo script and the Q&A for each live in its own file.

**General / main track** — [`docs/pitches/general.md`](pitches/general.md). Five minutes, one live phone, no
tech words. Opens on the friend's workshop, runs the KTM 390 Duke 2024 end to end — `chain is loose` →
KTM's own headings → page 77 with the answering lines marked → Parts → Chat with `[p. 77]` chips — and
starts a cold Yamaha MT-07 ingest in the background at 0:20 to land at 3:50. The demo moment is page 77: the
marker is only there because we found that exact text in KTM's PDF.

**OpenAI — build something ambitious with the API, with Codex as your teammate** —
[`docs/pitches/openai.md`](pitches/openai.md). Ten OpenAI capabilities carry the product and every one of
them is followed by a line of our code that can throw its answer away: structured outputs everywhere, model
tiering, prompt caching at 99.5% on the router, Responses streaming, built-in `web_search`, vision for
vehicle and part id, image generation, vision as a judge. Codex wrote three of our sixteen test modules and
found a live retrieval bug by pinning where the confidence floor sat ([`docs/CODEX.md`](CODEX.md)). The demo
moment is the architecture flowchart: orange is an API call, green is the guardrail that can discard it.

**The Token Company — cost is the product** —
[`docs/pitches/token-company.md`](pitches/token-company.md). The AI was never not-good-enough for this
mechanic; it was too expensive to use. A savings ladder that re-prices the same measured token counts rung
by rung, from $1.37 naive on the median manual down to $0.00038 an ask, with bear-2 removing **31.2%** of
the prompt before it is billed. The demo moment is `/api/cost/ttc` moving live while a citation stays
verbatim — compression is a cost lever, never a correctness lever.

**Voloridge — signal in the noise** — [`docs/pitches/voloridge.md`](pitches/voloridge.md). Climate Fit: the
manual's own printed rules resolved against 600 GB of NOAA hourly weather reduced in-stream to a 4 MB
climatology. 206 manuals print an antifreeze floor and every single one prints −25 °C — and 22.9% of
actively reporting stations went below it in 2024. The demo moment is switching the location from Zurich to
International Falls and watching the coolant row flip to *breached*, then tapping it and landing on the page
KTM printed. Status: built, deploying — the routes are live, the climatology is not in the replica yet.

**ElevenLabs — the agent that refuses to paraphrase** —
[`docs/pitches/elevenlabs.md`](pitches/elevenlabs.md). An Agents Platform agent whose four server tools are
our grounded manual tools and whose fifth, `show_page`, turns the page on the mechanic's screen while it is
still speaking. One grounding policy shared with the Deepgram engine by import, with a test that fails if
they drift. **It is built and needs a key** — `GET /api/voice/config` returns `elevenlabsAgentId: null`, so
the button does not render, and we never claim it is live. The demo moment is the agent saying "this manual
doesn't print a valve clearance" instead of supplying one.

**Ramp — time and money saved** — [`docs/pitches/ramp.md`](pitches/ramp.md). A one-man workshop loses
**EUR 24,640 a year** to looking for a page — 400 hours, cut down honestly for recovery and utilisation on
stage before anyone else cuts it — and the tool that gives it back costs cents a month to run. Every input
is regenerable: `docs/pitches/ramp/numbers.py` carries the formula for every cell and a judge can change one
and re-run. The demo moment is cutting our own headline number in half in public.

**Dropbox — the shop's own folder** — [`docs/pitches/dropbox.md`](pitches/dropbox.md). Owner's manuals are
free; the service manual a shop actually needs is metered — BMW charges EUR 9/hour — so we index the copy
the shop already bought, out of its own Dropbox folder, page-exact next to the OEM manual. A file whose path
does not parse to a make, model and year is never guessed at; it comes back as `unmatched`. Upload is live;
the folder sync is built and deploying. The demo moment is a bike with no free manual answering a question
sixty seconds after a PDF appeared in a folder.

**Deepgram — Flux and the Voice Agent, primed with the manual's vocabulary** —
[`docs/pitches/deepgram.md`](pitches/deepgram.md). **Live**: `GET /api/voice/config` returns
`deepgram: true`. Four grounded tools are the agent's entire vocabulary, and Deepgram calls our API
server-to-server, so the manual's text never passes through the tab. Measured through the Cloudflare Worker
proxy: greeting at 724 ms, end of speech → first audio a median **2.08 s** over 5 spec turns, 9.9 s on a
procedure question. The demo moment is asking "and the front one?" and getting 45 Nm with page 130 turning
itself.

**Long Lake — AI into an unglamorous service business** —
[`docs/pitches/long-lake.md`](pitches/long-lake.md). Independent vehicle repair is the American services
sector, and the workflow we removed is document lookup. Cycle time, error rate and unit cost against a named
baseline: five minutes of thumbing a PDF becomes two seconds, $12.40 becomes $0.0006, and a second
deployment costs $0.095 and 40 seconds of machine time with zero engineering. The demo moment is the page
itself; the honest deduction — one design partner, zero installs — is named in minute 4 rather than found in
Q&A.

**Not entered as their own tracks:** Elastic (`api/app/search/elastic.py` is written against the same `Index`
protocol but has never run against a live cluster), Visa (the parts sheet is live, there is no checkout) and
Runpod (the part classifier is zero-shot on OpenAI today, not hosted). All three have a block in
[`docs/PITCH.md`](PITCH.md) with an honest status line; none has a pitch file, and none should be demoed as
if it were live.

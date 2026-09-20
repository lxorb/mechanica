# Pitch — one block per track

**Mechanica.** You pick your exact bike, and you get that bike's official manual — the page, the printed
lines marked, the part lit on a 3D model. Any of 14,770 free official manuals, fetched on demand in under a
minute. Nothing is rewritten.

Live: **https://mechanica.emilvinu.ch** · API proxied at `/api`.

Every number below is **measured** (live endpoint, eval file, or a run logged in the repo) or **from code**
(a constant you can read). Nothing is estimated. Measured 2026-09-20.

Every figure here is generated into [`docs/pitches/numbers.md`](pitches/numbers.md) — re-run
`cd api && .venv/Scripts/python tools/pitch_numbers.py --live --md ../docs/pitches/numbers.md` before you
present, and do not type a number that is not in that file.

| measured | value | where |
|---|---|---|
| free official manuals we can fetch | **14,770 distinct PDFs** (24,210 free English owner's-manual rows) | `registry.json`, `_ingestable()` |
| registry | 53,557 rows, 80 makes, 84 portals, 182 service rows (15 not free) | `GET /api/registry` |
| catalog | **27,751 vehicles** — 23,140 motorcycles, 4,611 cars — **13,537** with a free manual | `GET /api/catalog` |
| warm cache | **535 manuals**, 95,914 pages, 91,388 sections, 662 vehicles | `GET /api/manuals` |
| cold bike → readable manual | **1.3 s to open, 40.4 s fully searchable** | timed live run, KTM 390 Duke 2014, 182 p, 2026-09-20 |
| ingest cost | **$0.095** per manual (mean over 648 real ingests, mean 177 pages) | `api/data/mass_report.jsonl` |
| ask | top-1 **100%** of 130 in-scope queries, 20/20 off-topic refused, p95 3.33 s, **$0.00038** | `api/eval/report.md` |
| ask, repeated | 0.2 s, **$0** (answer cache) | live, 2026-09-20 |
| chat | **100% of 48 claim sentences cited**, 43/43 quotes verbatim, 0 invented numbers, $0.0041/answer | `api/eval/chat-report.md` |
| chat, first token | **p50 2.64 s** / p95 5.87 s | `chat-report.md` |
| token compression | **31.2% saved** (eval, 23 bear-2 calls) · 29.1% over 10 calls on the live replica | `chat-report.md`, `GET /api/cost/ttc` |
| all OpenAI spend on the live API | **$8.93**, 1,633 calls — 2026-09-20 09:55, and it moves every hour | `GET /api/cost` |
| naive baseline | **$12.40** per ask (largest deployed manual) · **$1.37** (median manual) | `GET /api/cost` → `naivePerAsk` |

Naive = the largest manual we hold (775 pages × 800 tok/page, from code, past the 272k long-context line so
billed 2×) pasted into `gpt-6-astra` at $10/M. Our ask is **32,632× cheaper** — 3,600× against the median
manual, say which — and the answer is a PDF page, not a paragraph.

---

## OpenAI — the 5th teammate

| | |
|---|---|
| Judge sees | A bike nobody has ever asked for → its manual opens in 1.3 s and is fully searchable in 40 s; ask a question, land on the printed page |
| Say | **Nine and a half cents turns a 177-page PDF into a searchable manual, once. Every ask after that is four hundredths of a cent.** |
| Status | Live. Five routes, one file |

`api/app/llm.py` is the only door to OpenAI and logs tokens and USD per route: **vision bike id**, **query
router**, **page picker**, the one-time **manual structurer**, and **grounded chat**. Structured outputs via
`responses.parse` with Pydantic schemas everywhere — the picker returns *ids only*, and `ask.py` drops any id
that was not in the candidate list, so a hallucinated section cannot reach the UI. The whole app runs on the
cheap tier (`gpt-5.6-luna`, $0.20/M) except the picker and chat (`gpt-5.6-terra`, $2/M): **$75.96 of the
$83.05 build ledger is luna, and $71.52 of that is one-time ingest** — 86% of everything we have ever spent
is paid once per manual, never per question. Codex usage, including the live search bug it found:
[docs/CODEX.md](CODEX.md).

## Elastic — Find the Signal

| | |
|---|---|
| Judge sees | Typing `chain` on the Pick screen: the 3D bike explodes, the chain lights up, and the manual's own headings rank underneath — *Checking the chain tension*, then *Adjusting the chain tension* |
| Say | **Two retrievers fused by RRF, and the spec path answers with no ranking model at all — a torque question costs $0.00013** |
| Status | **Written, not live.** `ES_URL` is unset, so `get_index()` returns `LocalIndex`. Pending an Elastic trial key |

`api/app/search/elastic.py` (221 lines) targets Elasticsearch 9: `retriever.rrf` fusing a BM25 `bool`
(`title^3`, `keywords^2`, `text`, plus a `components` terms boost) with a `semantic` query over a
`semantic_text` field on the `.elser-2-elastic` inference endpoint, `rank_constant` 20. `title` is mapped
`search_as_you_type`; specs live in a `nested` field queried with `inner_hits`, which is why a spec question
never pays for a picker call. `search/local.py` (310 lines) is the reference implementation running today,
and both satisfy the same `Index` protocol — it is one env var to switch, and honestly, it has never been
run against a live cluster.

## The Token Company — cost is the product

| | |
|---|---|
| Judge sees | The chat drawer footer: tokens saved on that answer, live; `#cost` → `GET /api/cost/ttc` |
| Say | **We compress every page before the model reads it — 31.2% of the prompt gone, and not one printed torque figure lost** |
| Status | **Live**, with the real key, on chat and the ask picker |

`api/app/ttc.py` posts the whole retrieved context to `api.thetokencompany.com/v1/compress` with `bear-2` at
aggressiveness 0.3. Measured on six real contexts: **0.5 saves 32.2% but damages a page fence in 2 of 6 and
eats 20% of printed figures; 0.3 saves 19–25% and keeps every fence.** We miss the 30% target on purpose —
a lost fence reattributes one page's text to another page's number, which is the one thing this app exists
not to do. Also measured, not documented: **60 requests/minute**, which is why a chat compresses its entire
prompt in one call instead of one per page. It is a cost lever, never a correctness lever: no key, a 5xx, a
timeout or a missing fence all return the original text unchanged. Eval: **31.2% over 23 bear-2 calls**,
0 failures — quote this one. The live `/cost/ttc` counter (29.1% over 10 calls) is in-memory per replica and
zeroes on restart, so a low number means a fresh replica, not a worse compressor. Findings written up in `api/docs/CHAT-RESEARCH.md`.

## Long Lake — the skeptic mechanic

| | |
|---|---|
| Judge sees | A result screen that is the manufacturer's PDF page with an orange marker on the lines — and a chat where every single sentence carries a `[p. N]` chip that jumps to that page |
| Say | **A friend who runs a motorcycle shop won't touch AI: it's right 95% of the time, and the 5% is where a liable mechanic gets burned. So the model never gets to be the answer — it only gets to point.** |
| Status | Live, and enforced in code |

Three enforcements, all readable: (1) `ask.py` returns `Match[]` — section ids, titles, page ranges, nothing
else; no backend prose reaches the four main screens. (2) `ingest/ground.py` searches the PDF text layer for
every quote and **drops any it cannot find**, so a marker can only sit on ink the manufacturer printed.
(3) Chat is the one place words are generated, and it is fenced: the model may only emit page numbers, and
**the server slices each quote out of the original page text** — citations are verbatim by construction, not
by trusting the model. Measured: 43 of 43 citations verbatim, 100% of 48 claim sentences carry a page, 0 invented numbers and 0 dealer referrals across 25 questions.
Ask the BMW R 12 G/S about a loose chain and it says so — it is shaft drive.

## Ramp — time and money saved

| | |
|---|---|
| Judge sees | Two taps and one word, and the mechanic is on the printed page of a manual that did not exist on our servers a minute ago |
| Say | **$0.095 per manual, once. $0.0004 per ask. 535 manuals are warm; the deployed app has spent $8.93 over 1,633 calls (2026-09-20 09:55, and it moves).** |
| Status | Every figure logged per route, served by `GET /api/cost` |

Measured: cold procedure ask 3.4 s, cold spec ask 1.5 s, repeat 0.2–0.4 s at $0, chat first token 2.2–2.6 s.
The interesting arithmetic is the service writer's: a technician at $100/h spending five minutes thumbing a
268-page PDF for a torque figure costs $8.33. This costs $0.0004, answers in under two seconds, and hands
them the page they were liable for anyway. The AI line item stops being a line item.

## Dropbox — bring your own manual folder

| | |
|---|---|
| Judge sees | A bike with no free manual → **Dropbox** → pick the workshop PDF → progress bar → that bike answers questions |
| Say | **Owner's manuals are free for 9,424 of our 23,140 motorcycles and 4,113 of our 4,611 cars. The service manual a shop actually needs is metered — BMW charges EUR 9 an hour. So we point at the copy the shop already bought.** |
| Status | Upload path **live** (`POST /ingest/upload` → the same ingest). **Chooser pending `TTM_DROPBOX_APP_KEY`** — the button hides itself without it. Folder sync (`api/app/dropbox_sync.py`, 32 tests) is **built, deploying**: the router is in `main.py` but `/api/dropbox/*` is not in the live OpenAPI yet |

`web/counter/js/screens/confirm.js` loads the Chooser drop-in, which returns a `linkType: 'direct'` URL that
`/ingest` fetches and indexes exactly like an OEM URL; nothing is uploaded anywhere but the user's own index. This is the answer to the hard half of the
problem, quantified in [MANUALS.md](MANUALS.md): 182 service-manual rows across every brand, 15 of them paid,
subscription or dealer-login only — and we index none of them.

## Visa — parts basket

| | |
|---|---|
| Judge sees | **Parts** on the manual screen → an icon, the part name, the grade the manual prints, the page it is printed on, the OEM number, and chips out to RevZilla, Partzilla and Amazon |
| Say | **Every part is on that sheet because the manual prints a spec for it — not because a model guessed what fits** |
| Status | Sheet is live with 36 hand-drawn part icons. **No Visa API, no checkout** — do not claim otherwise |

`ingest/assemble.py` extracts a part only when the manual prints a grade, size or number for it, keeps the
printed designation verbatim, pulls OEM part numbers with four regexes, and emits search deep links built
from that string. `web/store/icons-parts/` is 36 SVGs (chain, brake pads, fork, fuse…), matched to parts by
`js/particons.js`. One-click checkout across three retailers is exactly where a Visa flow goes, and it is a
next-step slide, not a demo step.

## ElevenLabs — the agent that refuses to paraphrase

| | |
|---|---|
| Judge sees | Hands-free: you talk, the page turns itself, the voice reads the manual's own words with "page 114" before each |
| Say | **The agent has no permission to speak a sentence the manual does not print — four webhook tools are its entire vocabulary** |
| Status | **Pending a key.** `GET /api/voice/config` returns `elevenlabsAgentId: null`, so the mic button does not render |

`api/tools/elevenlabs_agent.py` creates the agent and four webhook tools: `find_procedure` (the same
router+index path the UI uses), `read_page` (verbatim page text in 1,200-char chunks), `get_spec` (printed
value + verbatim quote + page), `list_parts`. The fifth is the client tool `show_page`, handled in
`web/counter/js/voice.js` and called before reading, so the phone shows the page while the voice reads it. Temperature 0, `eleven_flash_v2_5`, webhooks
guarded by `X-Voice-Secret`. Needs the key plus the public `PUBLIC_BASE` we now have.

## Deepgram — the voice agent that reads the manual out loud

| | |
|---|---|
| Judge sees | Tap **VOICE** on the manual, say "what's the torque on the rear axle nut?", and the agent answers *"page 78 says one hundred newton metres"* — while page 78 turns itself on screen |
| Say | **Four grounded tools are the agent's entire vocabulary, and Deepgram calls our API directly — the manual's text never passes through the browser, so the tab cannot forge a tool result** |
| Status | **Live.** `GET /api/voice/config` returns `deepgram: true`. The key lives in a Cloudflare Worker, never in the tab |

`GET /voice/agent-settings` builds the whole `Settings` message server-side — prompt, models, greeting, a
≤1,500-char digest of the manual's chapters, this bike's keyterms, and the four tools as **server-side**
functions whose `endpoint.url` points at our API. `web/counter/js/voice-deepgram.js` opens
`wss://mechanica.emilvinu.ch/ws/deepgram/agent`, the Worker's proxy: a browser WebSocket cannot send
headers, and this account's key cannot mint short-lived ones, so `worker/index.js` adds the real
`Authorization: Token` header on the way out and pipes frames verbatim. Listen `flux-general-en` v2, think
`open_ai` `gpt-4.1`, speak `aura-2-asteria-en`. **Measured live through the proxy** (KTM 390 Duke 2024,
2026-09-20): greeting audio 724 ms after the socket opens; end of speech → first audio **median 2.08 s** over
5 spec turns (1.73–4.01 s), and **9.9 s** on a procedure question that walks `find_procedure` + four
`read_page` calls — say both. Barge-in stops scheduled audio in <3 ms. **$0.075 per connected minute**, and
the socket exists only between the two taps on VOICE. Keyterms: 100 terms / 1,413 chars accepted with zero
errors, but A/B'd against shop noise the WER difference is **11.4% vs 13.6% at 3 dB and 14.1% vs 13.3% at
0 dB** — that is noise, not a win, and we say so. Full write-up: [`web/docs/VOICE.md`](../web/docs/VOICE.md)
and [`docs/pitches/deepgram.md`](pitches/deepgram.md).

## Runpod — part classifier hosting

| | |
|---|---|
| Judge sees | `POST /api/identify/part` with a photo of a chain → `chain`, `chain_sprocket` with confidences, each mapping to a manual query |
| Say | **$0.00023 a photo zero-shot, 30 classes, and the checkpoint path is one env var away** |
| Status | **Not hosted.** Zero-shot on OpenAI today; the YOLO path loads locally. Not wired into any screen — demo with curl |

`api/app/parts/` classifies into the 30 labels of `AswinG5/moto-parts-30cls` and maps each to the query a
manual answers (`chain_sprocket` → "sprocket wear"). `PART_MODEL=yolo` lazily loads `motopartscls.pt`;
torch and ultralytics are deliberately out of `requirements.txt`. That checkpoint is what would live on a
Runpod endpoint — per-photo cost to roughly zero, and it works in a shop with no signal.

# Pitch — one block per track

One line for the whole thing: **you pick your exact bike, ask in your own words, and get the official
manual's own pages with the relevant lines marked. No AI prose, ever.**

Every number below was measured on this machine from `api/data/costs.jsonl` (242 logged OpenAI calls,
`GET /cost` total **$0.4331**) and `api/data-test/costs.jsonl` (one full ingest run). Anything not
measured is marked *unverified* or *not built*.

| measured | value | where |
|---|---|---|
| per ask, all 132 logged asks | **$0.00143** | `costs.jsonl`, `ask.router` + `ask.picker` |
| per ask, spec questions (50 of 132, no picker call) | **$0.00011** | router only |
| per ask, procedure questions (82 of 132) | **$0.00223** | router + picker |
| naive: whole manual into the prompt, per ask | **$2.144** (268 p) / $1.144 (143 p) | `GET /cost` → `naivePerAsk` |
| router prompt-cache hit rate | **98.9%** (271,510 / 274,487 input tokens) | `costs.jsonl` |
| bike photo → catalog row | **$0.00044** on `gpt-5.6-luna`, $0.02466 on `gpt-6-astra` | 9 + 8 calls |
| indexing a whole 268-page manual | **$0.1334**, 85 structured calls (~$0.0005/page) | `api/data-test/costs.jsonl` |
| time to page | 1.5 s spec · 2.5–5.8 s procedure · 0.23 s repeat | `curl -w` against `:8010` |
| manuals indexed by the registry | **7,511 entries** (7,496 free owner PDFs, 15 service) | `api/data/registry.json` |
| bikes in the catalog | **17,800** | `api/data/bikes.json` |

Could not verify: the "98% top-1 on 60 rider queries" figure (no eval set or result file exists in the
repo) and "$0.00115 mean per ask" (the log gives $0.00143 over all 132 asks, $0.00125 over the last 60).
Use **$0.0014** on stage — it is the one the cost log will show if a judge asks to see it.

---

## OpenAI — the 5th teammate

| | |
|---|---|
| Judge sees | Photo of a bike → the right catalog row; one sentence typed → the manual's printed page, no prose; `#cost` screen showing every call |
| Say | **$0.0014 an ask against $2.14 for reading the manual naively — 1,500× cheaper, and the answer is a PDF page, not a paragraph** |
| Status | Real, running on the key in `agent-secrets/openai.txt` |

Five jobs, all through one file (`api/app/llm.py`, which logs tokens and USD per route): vision bike id,
query router, page picker, the one-time manual structurer, and the part classifier. Structured outputs
everywhere via `client.responses.parse` with Pydantic schemas — the picker returns *ids only*, and
`ask.py` drops any id that was not in the candidate list, so a hallucinated section cannot reach the UI.
The router's ~2,000-token system prompt is prompt-cached at 98.9%, which is why a router call costs
$0.00011. **Honest:** there is no OpenAI Batch API call in the repo — ingest "batching" is 3-page windows
fanned out 8-wide with a thread pool (`ingest/structure.py`). Codex usage: [docs/CODEX.md](CODEX.md).

## Elastic — Find the Signal

| | |
|---|---|
| Judge sees | "chain is loose" on the KTM → p. 77 *Checking the chain tension* and p. 78 *Adjusting the chain tension*, in that order; typing "kt" lists KTM models instantly |
| Say | **Two retrievers fused by RRF over 20 sections a manual, and the spec path answers with zero ranking model at all** |
| Status | **Local BM25 index is what runs today.** `ES_URL` is unset on this machine, so `get_index()` returns `LocalIndex` |

`api/app/search/elastic.py` is written against Elasticsearch 9: a `retriever.rrf` fusing a BM25 `bool`
(`title^3`, `keywords^2`, `text`, plus a `components` terms boost) with a `semantic` query over a
`semantic_text` field backed by the `.elser-2-elastic` inference endpoint, `rank_constant` 20. Specs live
in a `nested` field and are queried with `inner_hits` — a torque or capacity question is answered by that
nested query and never pays for a picker call ($0.00011 vs $0.00223). Typeahead: `title` is mapped
`search_as_you_type`; today `/catalog/suggest` is a pure substring scan over 17,800 bikes, zero LLM.
**Pending an Elastic Cloud key:** the file has never been run against a live cluster. `LocalIndex`
(`search/local.py`) is the reference implementation and both satisfy the same `Index` protocol, so it is
one env var to switch.

## ElevenLabs — the agent that refuses to paraphrase

| | |
|---|---|
| Judge sees | Hands-free: you talk, the page turns itself, and the voice reads the manual's own words with "page 114" before each one |
| Say | **The agent has no permission to speak a sentence the manual does not print — four webhook tools and one client tool are its entire vocabulary** |
| Status | **Pending a key.** No `ELEVENLABS_API_KEY` on this machine, so `/voice/config` returns `null` and the mic button does not render |

`api/tools/elevenlabs_agent.py` creates or patches the agent and four webhook tools against
`/v1/convai/tools` and `/v1/convai/agents`: `find_procedure` (the same router+index path the UI uses),
`read_page` (verbatim page text, 1,200-char chunks with `hasMore`/`nextOffset`), `get_spec` (printed value
+ verbatim quote + page), `list_parts`. The fifth is the client tool **`show_page`**, handled in
`src/components/Voice.tsx` via `@elevenlabs/react` `clientTools` — the agent calls it before reading, so
the phone shows the page while the voice reads it. Prompt temperature 0, `eleven_flash_v2_5`, webhooks
guarded by `X-Voice-Secret`. Needs the key plus a public https `PUBLIC_BASE` for the webhooks.

## The Token Company — cost is the product

| | |
|---|---|
| Judge sees | The `#cost` screen: total, per ask, naive per ask, call count — live, from the real log |
| Say | **$0.43 has been spent on this entire project across 242 calls; one naive ask would have cost $2.14** |
| Status | Real cost accounting. **bear-2 compression pending a key** (`TTC_API_KEY` unset → pass-through) |

| | naive | ours |
|---|---|---|
| per ask (268-page manual) | $2.144 | **$0.00143** |
| model | `gpt-6-astra` @ $10/M in | `gpt-5.6-luna` router ($0.2/M) → `gpt-5.6-terra` picker ($2/M) |
| tokens in per ask | 214,400 | ~2,080 router + ~1,100 picker |

Four levers, in order of size: **tiering** (a 2,000-token router on the cheapest model decides everything;
the expensive model never sees more than 8 snippets of 300 chars), **caching** (98.9% router hit, plus an
in-process answer cache that makes a repeated question cost exactly $0), **the deterministic spec path**
(38% of asks skip the picker entirely — $0.00011), and **ingest once, ask forever** ($0.13 to index a
268-page manual; every ask after that is four-hundredths of a cent). `ask.py::_compress` posts the
candidate list to `api.thetokencompany.com/v1/compress` with `bear-2` at aggressiveness 0.3; any failure
or missing key returns the original text unchanged, so it cannot break the demo.

## Long Lake — the skeptic mechanic

| | |
|---|---|
| Judge sees | A result screen with no AI text on it anywhere — just the manufacturer's page and an orange marker over the lines |
| Say | **A friend who runs a motorcycle shop won't touch AI: it's right 95% of the time, and the 5% is where a liable mechanic gets burned. So we never let it answer — it only finds the page.** |
| Status | Real, and enforced in code |

It is a product rule with teeth. `DESIGN.md` rule 2: the result screen *is* the official PDF. The backend
contract forbids prose (`ask.py` returns `Match[]` — section ids, titles, page ranges, nothing else).
Highlights are grounded: `ingest/ground.py` searches the PDF text layer for each quote and **drops any
quote it cannot find**, so a marker can only ever sit on ink the manufacturer printed. The voice agent
gets the same treatment — it reads `read_page` output and is told never to add a warning of its own.
When the manual doesn't cover a job, you see that: ask the KTM for front pad replacement and it gives you
p. 86 *Checking that the brake linings of the front brake are secured*, because that is all KTM prints.

## Ramp — time and money saved

| | |
|---|---|
| Judge sees | Two taps and one sentence, 2.5 seconds, and the mechanic is on the printed page — no scrolling a 268-page PDF |
| Say | **$0.0014 and 2.5 seconds per question, against $2.14 of tokens or five minutes of thumbing a PDF** |
| Status | Cost real and logged; the minutes-saved figure is an estimate, say it as one |

Measured: 1.5 s for a spec question, 2.5–5.8 s for a procedure, 0.23 s for a repeat. $0.4331 of OpenAI
spend has built and tested the whole thing. Per shop, the interesting arithmetic is the one a service
writer does: a technician at $100/h who spends five minutes per lookup finding the torque figure costs
$8.33; this costs $0.0014 and answers in seconds, and the answer is the page they would have been
liable for anyway. At 1,500× the naive per-ask cost, the AI line item stops being a line item.

## Dropbox — bring your own manual folder

| | |
|---|---|
| Judge sees | A bike with no manual → **Dropbox** → pick the workshop PDF → a progress bar → that bike now answers questions |
| Say | **Any PDF you legally hold becomes a searchable manual in about a minute; you never upload it anywhere but your own index** |
| Status | Upload path real and tested. **Chooser pending `VITE_DROPBOX_APP_KEY`** — the button hides itself without it |

`src/components/AddManual.tsx` loads the Dropbox Chooser drop-in (`dropins.js`) with `linkType: 'direct'`
and `extensions: ['.pdf']`, then hands the direct link to `POST /ingest`, which fetches and indexes it
exactly like an OEM URL. The same sheet's **PDF** button posts a local file to `/ingest/upload` — that
path has run end to end. This is the answer to the hard half of the problem: the *owner's* manual is free
for 7,496 models, but the *service* manual that a shop actually needs is paid or subscription for every
brand (see [MANUALS.md](MANUALS.md)). A shop already owns those PDFs. This points at their folder.

## Deepgram — Flux, primed with the manual's vocabulary

| | |
|---|---|
| Judge sees | Tapping the mic and saying "what torque for the rear axle" with the engine running, and the words coming out right |
| Say | **The manual primes its own transcriber — up to 40 keyterms pulled from the section titles and part names of the bike you just selected** |
| Status | **Pending a key.** No `DEEPGRAM_API_KEY`, so `/voice/config` reports `deepgram: false` and `Ask.tsx` falls back to the browser's Web Speech API |

`src/lib/deepgram.ts` streams 16 kHz PCM from an AudioWorklet to `wss://api.deepgram.com/v2/listen` on
`flux-general-en`, appending one `keyterm` parameter per term from `prime(manual)` (section titles + part
names, ≥4 chars, stopword-filtered, capped at 40) — so "preload", "spindle", "Duke" and "telltale" are
expected words rather than guesses. Auth is the honest part: the browser cannot use the JWT from
`/v1/auth/grant` in a WebSocket subprotocol, so `POST /voice/deepgram-token` mints a project key scoped
to `usage:write` with a 600-second TTL and hands that to the browser. The key never ships in the bundle.

## Visa — parts basket

| | |
|---|---|
| Judge sees | **Parts** on the result screen → the consumables that page needs, each with the grade the manual prints, each linking out to RevZilla, Partzilla and Amazon |
| Say | **The basket is built from the manual's own printed specification, not from a guess about what fits** |
| Status | **Not built.** No Visa API, no basket, no checkout anywhere in the repo — do not claim otherwise |

What is real is the half that is hard: `ingest/assemble.py` extracts parts only when the manual prints a
grade, size or number for them, keeps the printed designation verbatim, pulls OEM part numbers with four
regexes, and emits search deep links (`SHOPS`) built from that string. 14 parts on the KTM, 12 on the
BMW. Turning that into one-click checkout across three retailers is exactly where a Visa flow would go,
and is a next-step slide, not a demo step.

## Runpod — part classifier hosting

| | |
|---|---|
| Judge sees | `POST /identify/part` with a photo of a chain → `chain`, `chain_sprocket` with confidences, which maps to a manual query |
| Say | **$0.00023 a photo zero-shot, 30 classes, and the checkpoint path is one env var away** |
| Status | **Not built on Runpod.** The classifier runs zero-shot on OpenAI; the YOLO path runs locally, nothing is hosted anywhere |

`api/app/parts/` classifies into the 30 labels of `AswinG5/moto-parts-30cls` and maps each to the query a
manual would answer ("chain_sprocket" → "sprocket wear"). Default path is zero-shot on `gpt-5.6-luna`
constrained to a `Literal` of the 30 labels — $0.00023 per photo over 7 logged calls. `PART_MODEL=yolo`
lazily loads `motopartscls.pt` via ultralytics, downloading it from HuggingFace on first use; torch and
ultralytics are deliberately out of `requirements.txt`. That checkpoint is what would live on a Runpod
endpoint, and it is the honest reason to want one: it takes the per-photo cost to roughly zero and works
in a shop with no signal. **Also honest:** `/identify/part` is not wired into any screen — demo it with
curl or `/docs`, not with a tap.

# Architecture — Mechanica

https://mechanica.emilvinu.ch · API at `/api` (same origin). Measured 2026-09-20 unless marked *code*.

## Components

| piece | what | where |
|---|---|---|
| `web/` | vanilla ES-module PWA, **no build**: 4 screens, pdf.js, three.js viewer, vendored deep-chat | Cloudflare Worker assets, custom domain |
| `worker/index.js` | serves the static app; `run_worker_first: ["/api/*"]` strips `/api` and proxies (Range included, `redirect: manual`) | Cloudflare |
| `api/` | FastAPI: catalog, identify, ensure/ingest, ask, chat, cost | Azure Container Apps, 1 CPU / 2 GiB, 1–3 replicas *(code)* |
| Azure Blob | `pdf` container public-read (browser range-fetches pages), `data` private (manuals, pages, specs, jobs, costs, registry, bikes) | system of record; the image ships **no** manual data |
| OpenAI | 5 routes through `app/llm.py`: vision id · router · picker · structurer · chat | `gpt-5.6-luna` $0.20/M, `gpt-5.6-terra` $2/M *(code)* |
| The Token Company | `bear-2` compression before chat and picker prompts | `app/ttc.py`, aggressiveness 0.3 *(code)* |

## Data flow

1. **Identify** — `GET /catalog` (22,300 bikes, 9,421 with a free manual) drives typeahead and model cards;
   `POST /identify/photo` or `/identify/vin` short-circuit to one bike.
2. **Confirm** — `POST /manuals/ensure` → `ready` if warm (332 manuals), else a job: registry lookup → OEM
   PDF → PyMuPDF text layer with per-block coords → LLM structure pass over 5-page windows (32 workers) →
   quotes grounded against the text layer, ungrounded ones dropped → blob. `early=true` publishes the PDF
   and contents first, so the manual is readable long before it is searchable.
3. **Pick** — `GET /manuals/{id}` gives sections; typing runs `POST /ask` (router rewrites slang → BM25 →
   picker returns validated ids only; spec questions skip the picker) and drives the 3D explode + highlight.
4. **Book** — `GET /manuals/{id}/file` 307s to the blob URL; pdf.js renders, highlights are normalised
   rects over the page. Parts sheet reads the manual's own parts.
5. **Chat** — `POST /chat` SSE: router → BM25 → ≤6 printed pages → one TTC call for the whole prompt →
   streamed answer that may only emit `[p. N]`; the server slices each quote out of the **original** page.

## Cost and latency per operation

| operation | cost | latency | source |
|---|---|---|---|
| ingest one manual (median 177 p) | **$0.10** | 44–50 s to searchable, **6–7 s to readable** | 319 runs + 2 live |
| ask, cold spec | $0.00013 | 1.5 s | live |
| ask, cold procedure | $0.0018–0.0038 | 3.1–3.5 s | live |
| ask, repeated | **$0** | 0.2–0.4 s | answer cache, live |
| ask, mean over 150-query eval | $0.00038 | p95 3.33 s | `api/eval/report.md` |
| chat answer | $0.0045–0.0054 | first token 2.2–2.6 s | live + `chat-report.md` |
| photo → bike | $0.0054 over all logged calls | — | `GET /api/cost` |
| naive baseline (whole manual in the prompt) | **$6.096** | — | `GET /api/cost` |
| everything spent on the live API so far | **$1.172** / 569 calls | — | `GET /api/cost` |

## What is cached where

| layer | holds | invalidation |
|---|---|---|
| browser service worker (`v7`) | shell, fonts, bike roster, pdf.js + worker, **manual PDFs sliced for Range** | version bump |
| browser localStorage | relevant-vs-all page mode per manual | — |
| Cloudflare Worker | `Cache-Control: public, max-age=60` on `/api/catalog`, `/api/manuals*` | 60 s |
| API process | answer cache 500 entries · manuals LRU 200 · pages LRU 50 (300 s TTL) · listings 60 s · costs 30 s · TTC LRU 2000 · registry index by file mtime | per replica, *(code)* |
| Azure Blob | every PDF, manual, page, spec, job and cost event — the only durable store | never |
| OpenAI | router system prompt (prompt cache) | provider |

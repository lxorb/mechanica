# Devpost submission — Mechanica

**Tagline**
Don't trust the AI. Trust the manual.

Live: https://mechanica.emilvinu.ch

## Inspiration
A friend who runs a motorcycle shop refuses to use AI: it is right 95% of the time, and the 5% is where a
liable mechanic gets burned. The fix is not a better model — everything he needs is already printed in the
manual. So we built the thing that never answers.

## What it does
Search 22,300 bikes and pick yours from a photo card, a snapshot, or a VIN. Never seen that bike? We fetch
its official manual from the manufacturer — **openable in 6 seconds, fully searchable in under a minute,
for ten cents.** 8,319 free official PDFs are reachable; 332 are already warm.

Then say what is wrong. A 3D model explodes and lights the part you typed, next to the manual's own
headings. Open one and you get the manufacturer's page, rendered as printed, an orange marker on the lines
that answer you — plus the whole manual, its real contents, and a Parts sheet built only from specs the
manual prints. The chat may only emit page numbers: the server slices every quote out of the original
page, so citations are verbatim by construction.

## How we built it
A no-build vanilla PWA over FastAPI. PyMuPDF extracts the text layer with per-block coordinates; one cheap
LLM pass over 5-page windows turns a PDF into sections, specs and parts, and every quote is searched back
into that layer — a highlight can only sit on ink the manufacturer printed. At ask time a router rewrites
rider slang into manual vocabulary, BM25 ranks, and a picker returns validated ids only; spec questions
skip the picker. bear-2 compresses each retrieved page first. Azure Blob is the system of record, the API
runs on Azure Container Apps, and a Cloudflare Worker serves the app and proxies `/api`.

## Challenges
Making a model that cannot lie: ids only, validated; quotes grounded or dropped. Eleven OEM portals, all
different — one 401s if you send `Accept: application/json`. And compression that eats printed torque
figures at 0.5 aggressiveness, so we take 0.3 and 22% instead of 32%.

## Accomplishments
Top-1 100% over 150 rider queries, p95 3.33 s, $0.00038 an ask against $6.10 to read the manual naively.
100% of chat citations verbatim on the page they name. 8,319 manuals reachable, none copied. The whole
project has cost $1.17 in model calls.

## What we learned
Constraining a model is cheaper than trusting it, in tokens and in liability. The hard part was never the
model — it was the portals and the PDF text layer.

## What's next
Service manuals: a rider's manual is free, a shop's is metered by the hour, so we point at the shop's own
folder. Then voice and parts checkout.

## Built with
python · fastapi · pymupdf · openai · the-token-company · elasticsearch · three.js · pdf.js · deep-chat ·
azure-blob-storage · azure-container-apps · cloudflare-workers

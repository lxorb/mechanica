# Devpost submission

**Tagline** (37 chars)
Don't trust the AI. Trust the manual.

## Inspiration
A friend who runs a motorcycle shop refuses to use AI — not because it is bad, but because it is right
95% of the time, and the 5% is where a liable mechanic gets burned. He is correct, and the fix is not a
better model. Everything he needs is already printed in the manufacturer's manual; it just takes five
minutes of scrolling a 268-page PDF. So we built the thing that never answers.

## What it does
Pick your exact bike — photo, VIN, or typeahead over 17,800 models. Ask in your own words: "chain is
loose", "what torque for the rear axle". You get the official manual's own pages, rendered as printed,
with a marker over the lines that answer you and the page number to quote. No summary, no chat bubble,
no AI prose. If the manual doesn't cover it, you see that too.

## How we built it
A Vite/React PWA (installable, offline) over FastAPI. PyMuPDF extracts the text layer with per-block
coordinates. One LLM pass over 3-page windows turns the PDF into sections, specs and parts, and every
quote is searched back into that text layer — so a highlight can only sit on ink the manufacturer
printed. At ask time a cheap router rewrites rider slang into manual vocabulary, BM25 (Elasticsearch 9,
RRF hybrid with ELSER when a cluster is configured) returns candidates, and a picker returns ids only,
validated server-side, so a hallucinated section cannot reach the UI. Spec questions skip the picker
entirely. An ElevenLabs agent reads pages verbatim through four webhook tools and turns the page with a
`show_page` client tool; Deepgram Flux is primed with keyterms from the manual's headings. API on Azure
Container Apps, web on a Cloudflare Worker.

## Challenges
Making a model that cannot lie: ids only, validated; quotes grounded or dropped. Eleven OEM portals, all
different — one 401s if you send `Accept: application/json`. And Deepgram's browser auth: the documented
JWT isn't accepted in a WebSocket subprotocol, so we mint a scoped 600-second key server-side.

## Accomplishments
$0.0014 an ask against $2.14 to read the manual naively — 1,500×, measured from a per-route cost log,
with a cost screen in the app to prove it. 7,511 official manuals indexed across 15 brands, none copied.
Highlights provably made of the manufacturer's ink. An app whose whole vocabulary is nine UI strings.

## What we learned
Constraining a model is cheaper than trusting it, in tokens and in liability. A 2,000-token system prompt
cached at 99% costs less than a short uncached one. The hard part was never the model.

## What's next
Service manuals: owner's manuals are free for 7,496 models, but the manual a shop needs is paid at every
brand — so we point at the shop's own Dropbox folder. Then one-tap parts checkout, and a self-hosted
classifier for shops with no signal.

## Built with
python · fastapi · pymupdf · openai · elasticsearch · elevenlabs · deepgram · react · typescript · vite ·
tailwindcss · pdf.js · pydantic · rank-bm25 · mongodb · azure-container-apps · cloudflare-workers ·
dropbox · ultralytics · nhtsa-vpic

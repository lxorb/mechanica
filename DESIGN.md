# Trust the manual — prototype rules

Static PWA, mock data, no backend, no network calls except loading files from /public.
Purpose: validate the UX. "Don't trust the AI. Trust the manual. We just get you to the right page."

## Product rules (non-negotiable)
1. No prose. No onboarding, no explanations, no AI summaries, no chat bubbles, no "AI thinks…". If a string is not a label the user needs to act, delete it.
2. The manual is the answer. The result screen IS the official PDF, rendered page by page, with a translucent marker over the relevant lines. Its own page numbers, its own chapter titles, its own diagrams. Nothing rewritten.
3. It must be obvious it is the manual: header shows the manual title as printed on the cover + "p. N/M", body is the rendered PDF page on a light sheet inside the dark app.
4. Three steps only: bike → question → pages. Back is always one tap.
5. Mobile first (390×844), thumb-reachable controls at the bottom, 44px min tap targets, works one-handed with dirty hands. Also fine on desktop.
6. Fast. No spinners longer than a page render. No fake "thinking" delays.
7. Audience: professional mechanics. Nothing in the product ever says "see your dealer" or "have a workshop do it". When an owner's manual defers to a dealer, we say the manual does not include the procedure and still give every value it prints.

## Visual
- Dark app chrome (--bg), light PDF sheet, one accent (--accent, orange) for the marker and the primary action only.
- System font. Sizes: 17px base, 15px secondary, 13px meta. Weight 500 for labels, 400 body.
- Radius 12px. Borders 1px --line. No shadows, no gradients, no icon libraries: inline SVG paths or unicode only.
- Tailwind v4 utilities + the CSS variables in src/index.css. No other CSS files.

## Allowed UI strings (entire app)
Photo · VIN · search placeholder "Make, model" · question placeholder "What do you want to do?" · Parts · p. · ← · ✕ · ↑ (send) · mic glyph.
Section titles, chapter titles, part names, specs and shop names come from the data files verbatim.

## Code (since 2026-09-20 evening)
- Frontend = Handy Book counter app in web/ (vanilla ES modules, no build): screens in web/counter/js/screens, adapter web/counter/js/ttm.js (only module screens import), 3D viewer web/counter/js/viewer3d.js, part icons web/counter/js/particons.js. The old React app was removed.
- Backend = api/ (FastAPI). The UI contract stays Manual + jobs (sections); no backend prose ever reaches the UI.
- Steps: 1 Identify · 2 Confirm · 3 Pick (3D model + search over chapters/subchapters) · 4 Book (fullscreen manual). Parts is a sheet from Book.
- Deploy: `bash deploy/web.sh` (Cloudflare Worker, https://mechanica.emilvinu.ch, /api proxied to Azure), `bash deploy/azure.sh` (API).

## Phase 2: real backend (api/, FastAPI, Python 3.12)
Contracts owned by the integrator: api/app/models.py (camelCase, byte-compatible with src/types.ts), api/app/store.py (Store protocol + FileStore),
api/app/search/__init__.py (Index protocol), api/app/llm.py (the only door to OpenAI, logs cost per route), api/app/main.py (routes), src/lib/source.ts signature, src/App.tsx.
Rules: no backend ever returns prose to the UI. The UI contract stays `Manual` + `Match[]`. Every number shown comes from the PDF text layer.
Secrets: never in git. OPENAI_API_KEY from env or C:\Users\me\agent-secrets\openai.txt (see config.py). Run the API with `api/.venv/Scripts/python -m uvicorn app.main:app --port <your port>` from api/.
Deps: requirements.txt is pre-populated; append a line only if you truly need a new package, and install it into api/.venv yourself.

Ownership:
- ingest agent: api/app/ingest/** , api/tools/ingest.py
- search agent: api/app/search/local.py, api/app/search/elastic.py, api/app/ask.py
- identify-backend agent: api/app/identify.py, api/app/parts/** (optional yolo)
- registry agent: api/app/registry/**, api/tools/registry.py, api/data/seeds/**
- frontend-api agent: src/lib/source.ts, src/lib/api.ts, src/screens/Identify.tsx, src/screens/Cost.tsx, src/components/AddManual.tsx, .env.example (root)
- voice agent: api/app/voice.py, api/tools/elevenlabs_agent.py, src/components/Voice.tsx, src/lib/deepgram.ts, package.json (only agent allowed to `npm install`)
- store/deploy agent: api/app/store_mongo.py, api/Dockerfile, api/.dockerignore, deploy/**, wrangler.jsonc, README.md (root, keep it 10 lines)
- qa agent (after all): anything, to integrate and fix

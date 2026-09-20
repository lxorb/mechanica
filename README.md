# Mechanica

Official motorcycle manual, right page. Frontend: Mechanica app (Handy Book base) in `web/` (no build). Backend: FastAPI in `api/`.

    npx serve web -l 5000            # http://localhost:5000/counter/
    cd api && .venv/Scripts/python -m uvicorn app.main:app --port 8000

Deploy: `bash deploy/azure.sh` (API, Azure Container Apps + Blob), `bash deploy/web.sh` (Cloudflare Worker).
Live: https://mechanica.emilvinu.ch (workers.dev mirror: https://trustthemanual.cloudflare-disjoin783.workers.dev/counter/) · API https://ttm-api.victoriousground-5b684586.eastus.azurecontainerapps.io
Docs: docs/PITCH.md, docs/DEMO.md, docs/SUBMISSION.md, docs/MANUALS.md, docs/UI.md. Env names: api/.env.example.

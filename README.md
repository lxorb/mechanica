# Trust the manual
Don't trust the AI. Trust the manual. PWA (React/Vite) + API (FastAPI, `api/`).

    npm install && npm run dev                          # web, :5173
    cd api && .venv/Scripts/python -m uvicorn app.main:app --port 8000
    deploy/azure.sh              # API -> Azure Container Apps, prints the URL
    deploy/web.sh <api-url>      # web -> Cloudflare Worker `trustthemanual`
    deploy/redeploy.sh           # both, in order

Env: `VITE_API_URL` (web); `OPENAI_API_KEY` `PUBLIC_BASE` `CORS_ORIGINS` `DATA_DIR` `MONGODB_URI` `ES_URL` (api, see `api/.env.example`).

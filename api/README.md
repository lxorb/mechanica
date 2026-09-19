# api

    cd api
    python -m venv .venv && .venv/Scripts/activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Env: see .env.example. Without ES_URL / MONGODB_URI it runs on local files.

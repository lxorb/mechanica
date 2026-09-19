import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SECRETS_DIR = Path(os.getenv("SECRETS_DIR", r"C:\Users\me\agent-secrets"))


def _secret(env: str, file: str) -> str | None:
    value = os.getenv(env)
    if value:
        return value
    path = SECRETS_DIR / file
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


class Settings:
    data_dir = Path(os.getenv("DATA_DIR") or ROOT / "data")
    openai_api_key = _secret("OPENAI_API_KEY", "openai.txt")
    es_url = os.getenv("ES_URL") or None
    es_api_key = os.getenv("ES_API_KEY") or None
    mongodb_uri = os.getenv("MONGODB_URI") or None
    elevenlabs_api_key = _secret("ELEVENLABS_API_KEY", "elevenlabs.txt")
    elevenlabs_agent_id = os.getenv("ELEVENLABS_AGENT_ID") or None
    deepgram_api_key = _secret("DEEPGRAM_API_KEY", "deepgram.txt")
    model_router = os.getenv("MODEL_ROUTER", "gpt-5.6-luna")
    model_picker = os.getenv("MODEL_PICKER", "gpt-5.6-terra")
    model_struct = os.getenv("MODEL_STRUCT", "gpt-5.6-luna")
    model_vision = os.getenv("MODEL_VISION", "gpt-5.6-luna")
    public_base = os.getenv("PUBLIC_BASE", "http://localhost:8000").rstrip("/")
    cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

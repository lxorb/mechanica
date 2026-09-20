"""Test harness.

DATA_DIR is redirected to a throwaway copy of api/data BEFORE app.config is imported,
because Settings reads the env var once at class-body evaluation time. The seeded
api/data is therefore only ever read, never written.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = API_DIR / "data"

_tmp_root = Path(tempfile.mkdtemp(prefix="ttm-tests-"))
# pytest's own basetemp lives under the shared %TEMP%\pytest-of-<user>, which other tools on this
# box have left unreadable. Keep tmp_path inside our throwaway root so the suite is self-contained.
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_tmp_root))

DATA_DIR = _tmp_root / "data"

KTM = "ktm-390-duke-2024-om-en"
BMW = "bmw-r12gs-2025-rm-en"

# Four directories hold one file per manual, and seeding all 509 of them meant copying 4.5 GB
# (4.1 GB of it PDFs) before the first test ran and then parsing 62 MB of manual JSON on every
# call to store.manuals(). Nothing in the suite counts manuals or reaches for one it does not
# name, so the corpus is seeded down to these - every id the tests use, plus the two the ingest
# fixtures share a shape with, plus the longest manual in the corpus, which is what pins
# max_manual_pages() and therefore the /cost naive-per-ask figure the shape test compares against.
PER_MANUAL_DIRS = ("manuals", "pages", "specs", "pdf")
SEEDED_MANUALS = (
    KTM,
    BMW,
    "bmw-f-900-r-2025-eu-om",
    "ktm-1390-super-adventure-r-2026-us-om",
    "honda-africa-twin-adventure-sports-es-dct-2026-us-om",  # 381 pages: the corpus maximum
)


def _seed(src: Path, dst: Path) -> None:
    """api/data -> the throwaway copy, whole except for the four per-manual directories."""
    dst.mkdir(parents=True, exist_ok=True)
    skip = shutil.ignore_patterns("seeds", "uploads", "*.part*")  # bulky, and never read back
    for entry in src.iterdir():
        if skip(str(src), [entry.name]):
            continue
        if entry.name in PER_MANUAL_DIRS:
            (dst / entry.name).mkdir(exist_ok=True)
            for manual_id in SEEDED_MANUALS:
                for one in entry.glob(f"{manual_id}.*"):
                    shutil.copy2(one, dst / entry.name / one.name)
        elif entry.is_dir():
            shutil.copytree(entry, dst / entry.name, ignore=skip)
        else:
            shutil.copy2(entry, dst / entry.name)


_seed(SEED_DIR, DATA_DIR)

for _var in (
    "MONGODB_URI",
    "ES_URL",
    "ES_API_KEY",
    "VOICE_TOOL_SECRET",
    "TTC_API_KEY",
    "PART_MODEL",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_ACCOUNT",
):
    os.environ.pop(_var, None)
os.environ["DATA_DIR"] = str(DATA_DIR)
os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
os.environ["ELEVENLABS_AGENT_ID"] = "agent_test"
os.environ["PUBLIC_BASE"] = "http://testserver"

atexit.register(lambda: shutil.rmtree(_tmp_root, ignore_errors=True))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing in the suite may leave the machine. Starlette's TestClient rides on an
    ASGITransport, so only the real network transport and the module-level helpers die."""
    import httpx

    def blocked(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(httpx, "get", blocked)
    monkeypatch.setattr(httpx, "post", blocked)
    monkeypatch.setattr(httpx, "request", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)


@pytest.fixture(autouse=True)
def clean_caches():
    """ask/, search/ and store/ all memoise in module globals."""
    from app import ask as ask_mod
    from app import search as search_mod
    from app import store as store_mod

    def reset():
        ask_mod._cache.clear()
        ask_mod._pages.clear()
        search_mod._index = None
        store_mod._store = None

    reset()
    yield
    reset()


@pytest.fixture
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture
def store():
    from app.store import get_store

    return get_store()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fresh_store(tmp_path):
    """A FileStore over an empty directory: writes never touch the seeded data."""
    from app.store import FileStore

    return FileStore(tmp_path)

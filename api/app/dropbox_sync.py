"""The shop's own folder. A Dropbox folder -> the same ingest a free OEM manual goes through.

Why this exists: the registry indexes 53,557 rows across 84 OEM hosts and not one of them is the
document a professional actually needs. `docs/MANUALS.md` counts it: 182 service-manual rows, 15 of
them not free - BMW meters its at EUR 9 an hour, Triumph at GBP 5.99 a month per bike, Ducati and
Piaggio hand theirs to dealers only. We fetch none of those. The shop already bought a copy, and it
is sitting in its Dropbox next to the scanned bulletins and the PDFs the importer emailed over.
This module indexes THAT folder, page-exact, with the same grounding rules as an OEM manual.

The Dropbox side is four calls, all verified against dropbox/dropbox-api-spec (files.stone) and
docs.dropboxapi.com/dropbox-api/docs/webhooks on 2026-09-20:

  files/list_folder            host api      auth user   scope files.metadata.read
  files/list_folder/continue   host api      auth user   scope files.metadata.read   (cursor)
  files/list_folder/longpoll   host notify   auth NOAUTH scope files.metadata.read   (30-480 s)
  files/download               host content  auth user   scope files.content.read    (Dropbox-API-Arg)

longpoll is deliberately unauthenticated - the cursor is the credential - so the watcher thread never
puts the token on a 480-second socket. A webhook is offered too (GET echoes `challenge` as text/plain
with nosniff; POST carries an HMAC-SHA256 of the raw body under X-Dropbox-Signature and says only
WHICH ACCOUNT changed, never what), because a mechanic's phone hotspot drops long sockets.

Nothing here is a second ingest path. A file is downloaded, checked for the %PDF magic bytes, written
to disk and handed to ingest.run() exactly like the PDF a mechanic uploads through POST /ingest/upload.
Every rule that makes this product trustworthy - quotes searched back into the text layer, markers only
on ink that exists, chat allowed to emit page numbers and nothing else - applies unchanged.

Config, all optional, all no-ops until a token exists:
  DROPBOX_TOKEN / C:\\Users\\me\\agent-secrets\\dropbox.txt   line 1 access token, line 2 (optional) app secret
  DROPBOX_APP_SECRET   webhook signature key, if not line 2 of the file
  DROPBOX_FOLDER       folder to watch, default "" = the app folder root
  DROPBOX_AUTOSTART    "0" to keep the watcher thread from starting at import
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import ingest as ingest_mod
from .config import settings
from .models import Bike, IngestJob
from .store import get_store

try:  # app.registry owns the id scheme; this path must survive that package being edited under it
    from .registry._http import slug
except Exception:

    def slug(*parts: object) -> str:
        raw = "-".join(str(p) for p in parts if p not in (None, ""))
        raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
        return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", raw.lower())).strip("-")


log = logging.getLogger("dropbox")
router = APIRouter(prefix="/dropbox", tags=["dropbox"])

API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
NOTIFY = "https://notify.dropboxapi.com/2"

LONGPOLL = 480  # seconds; the spec allows 30-480
IDLE_POLL = 300  # fallback sweep when longpoll is unavailable or keeps erroring
BACKOFF = (5, 15, 60, 300)
PAGE = 2000  # list_folder limit ceiling
MAX_PDF = 120 * 1024 * 1024  # twice the /ingest/upload cap: a scanned service manual is a big file
TIMEOUT = httpx.Timeout(30.0, read=60.0)
LONGPOLL_TIMEOUT = httpx.Timeout(30.0, read=LONGPOLL + 90)
MAKES_TTL = 600

_lock = threading.RLock()
_thread: threading.Thread | None = None
_wake = threading.Event()
_makes: tuple[float, list[str]] = (0.0, [])


# ---------------------------------------------------------------- configuration


def _lines() -> list[str]:
    raw = settings.dropbox_token or ""
    return [l.strip() for l in raw.splitlines() if l.strip()]


def token() -> str | None:
    lines = _lines()
    return lines[0] if lines else None


def app_secret() -> str | None:
    env = os.getenv("DROPBOX_APP_SECRET")
    if env:
        return env.strip()
    lines = _lines()
    return lines[1] if len(lines) > 1 else None


def folder() -> str:
    """Dropbox wants "" for the root of the app folder, never "/"."""
    raw = (os.getenv("DROPBOX_FOLDER") or "").strip().rstrip("/")
    return raw if raw not in ("", "/") else ""


def enabled() -> bool:
    return bool(token())


# ---------------------------------------------------------------- state


def _dir() -> Path:
    path = settings.data_dir / "dropbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return _dir() / "state.json"


def state() -> dict[str, Any]:
    with _lock:
        path = _state_path()
        if not path.exists():
            return {"cursor": None, "files": {}, "lastPollAt": None, "lastError": None, "passes": 0}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # a half-written file must not stop the watcher forever
            log.warning("dropbox state unreadable (%s); starting clean", exc)
            return {"cursor": None, "files": {}, "lastPollAt": None, "lastError": None, "passes": 0}


def _save(data: dict[str, Any]) -> None:
    with _lock:
        path = _state_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


# ---------------------------------------------------------------- Dropbox HTTP


class DropboxError(RuntimeError):
    def __init__(self, status: int, body: str, retry_after: float = 0.0):
        super().__init__(f"dropbox {status}: {body[:300]}")
        self.status = status
        self.body = body
        self.retry_after = retry_after


def _client(longpoll: bool = False) -> httpx.Client:
    """One seam for the whole module: the tests swap this for an httpx.MockTransport client."""
    return httpx.Client(timeout=LONGPOLL_TIMEOUT if longpoll else TIMEOUT)


def _raise(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    after = 0.0
    if r.status_code == 429:
        try:  # Dropbox puts the wait in the error body, and sometimes in Retry-After
            after = float(r.json().get("error", {}).get("retry_after", 0) or 0)
        except Exception:
            after = 0.0
        after = after or float(r.headers.get("Retry-After") or 0)
    raise DropboxError(r.status_code, r.text, after)


def _rpc(route: str, arg: dict[str, Any], *, host: str = API, auth: bool = True) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {token()}"
    with _client(longpoll=host == NOTIFY) as c:
        r = c.post(f"{host}/{route}", headers=headers, content=json.dumps(arg).encode())
    _raise(r)
    return r.json()


def download(file_id: str) -> bytes:
    """files/download. The argument rides in a header, so the JSON must be ASCII-escaped."""
    headers = {
        "Authorization": f"Bearer {token()}",
        "Dropbox-API-Arg": json.dumps({"path": file_id}, ensure_ascii=True),
    }
    with _client() as c:
        r = c.post(f"{CONTENT}/files/download", headers=headers)
    _raise(r)
    return r.content


def changes(cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    """Every entry added or changed since `cursor`, plus the cursor to store for next time.

    No cursor means a first full listing. A cursor Dropbox has invalidated (`reset`) is thrown away
    and the folder listed again - re-listing is cheap, and a stuck cursor is a silent outage."""
    entries: list[dict[str, Any]] = []
    page: dict[str, Any] | None = None
    if cursor:
        try:
            page = _rpc("files/list_folder/continue", {"cursor": cursor})
        except DropboxError as exc:
            if "reset" not in exc.body:
                raise
            log.info("dropbox cursor reset; re-listing %r", folder() or "/")
            cursor, page = None, None
    if not cursor:
        page = _rpc(
            "files/list_folder",
            {"path": folder(), "recursive": True, "include_deleted": False, "limit": PAGE},
        )
    assert page is not None
    entries += page.get("entries") or []
    cursor = page.get("cursor")
    while page.get("has_more") and cursor:
        page = _rpc("files/list_folder/continue", {"cursor": cursor})
        entries += page.get("entries") or []
        cursor = page.get("cursor")
    return entries, cursor


def longpoll(cursor: str) -> bool:
    """Block on the notify host until the folder changes. Unauthenticated by design (files.stone:
    `auth = "noauth"`) - the cursor is the credential, so the token never sits on a long socket."""
    body = _rpc("files/list_folder/longpoll", {"cursor": cursor, "timeout": LONGPOLL}, host=NOTIFY, auth=False)
    if body.get("backoff"):
        time.sleep(float(body["backoff"]))
    return bool(body.get("changes"))


# ---------------------------------------------------------------- what bike is this PDF about


NOISE = {
    "manual", "manuals", "handbook", "handbuch", "bedienungsanleitung", "service", "workshop",
    "shop", "repair", "owner", "owners", "rider", "riders", "guide", "book", "booklet", "pdf",
    "scan", "scanned", "copy", "final", "en", "eng", "english", "de", "v1", "v2", "rev", "draft",
    "compressed", "ocr", "part", "vol", "edition", "bulletin", "tsb",
}
YEAR = re.compile(r"^(19[89]\d|20[0-4]\d)$")
ALIASES = {
    "harley": "Harley-Davidson",
    "hd": "Harley-Davidson",
    "gasgas": "GasGas",
    "gas gas": "GasGas",
    "husky": "Husqvarna",
    "re": "Royal Enfield",
    "mv": "MV Agusta",
    "brp": "Can-Am",
}


def makes() -> list[str]:
    """Every make the catalog knows, longest first, cached: 27k Bike rows is not a per-file read."""
    global _makes
    age, cached = _makes
    if cached and time.time() - age < MAKES_TTL:
        return cached
    try:
        found = sorted({b.make for b in get_store().bikes() if b.make}, key=lambda m: (-len(m.split()), -len(m)))
    except Exception as exc:
        log.warning("catalog unavailable for make matching: %s", exc)
        return cached
    _makes = (time.time(), found)
    return found


def parse_meta(path: str) -> tuple[str, str, int] | None:
    """`/Manuals/Yamaha/MT-07 2019 service manual.pdf` -> ("Yamaha", "MT-07", 2019).

    The shop's filing is the metadata, so read the whole path, not just the file name. A file we
    cannot place is reported as unmatched in /dropbox/status rather than guessed into the catalog:
    a manual filed under the wrong bike is exactly the failure this product exists to prevent."""
    stem = re.sub(r"\.pdf$", "", path, flags=re.I)
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", stem) if t]
    if not tokens:
        return None
    lower = [t.lower() for t in tokens]

    year_at = next((i for i in range(len(lower) - 1, -1, -1) if YEAR.match(lower[i])), None)
    if year_at is None:
        return None
    year = int(lower[year_at])

    make, make_at, make_len = None, None, 0
    for candidate in makes():
        words = [w for w in re.split(r"[^a-z0-9]+", candidate.lower()) if w]
        for i in range(len(lower) - len(words) + 1):
            if lower[i : i + len(words)] == words:
                make, make_at, make_len = candidate, i, len(words)
                break
        if make:
            break
    if make is None:
        for i, word in enumerate(lower):
            if word in ALIASES:
                make, make_at, make_len = ALIASES[word], i, 1
                break
    if make is None or make_at is None:
        return None

    after = make_at + make_len
    span = lower[after:year_at] if year_at > after else lower[after:] + lower[:make_at]
    model = " ".join(tokens[after:year_at] if year_at > after else tokens[after:] + tokens[:make_at])
    kept = [t for t, low in zip(model.split(), span) if low not in NOISE and not YEAR.match(low)]
    model = " ".join(kept)
    return (make, model, year) if model else None


# ---------------------------------------------------------------- ingest


def _run_ingest(path: Path, make: str, model: str, year: int) -> dict[str, Any]:
    """The shop's PDF, through the one ingest every manual goes through.

    The manual id ends `-shop`, never `-om`: a workshop's own service manual must not overwrite the
    free owner's manual another vehicle is pointing at. The bike is then pointed at the shop's copy,
    because for the person holding the spanner that is the better document."""
    store = get_store()
    bike_id = slug(make, model, year)
    manual_id = f"{bike_id}-shop"
    job = IngestJob(id=uuid.uuid4().hex[:12], manualId=manual_id, status="queued")
    store.put_job(job)
    bike = store.bike(bike_id) or Bike(id=bike_id, make=make, model=model, year=year, market="EU")
    previous = bike.manualId
    store.put_bikes([bike])
    ingest_mod.run(job.id, str(path), manual_id, [bike_id], make, model, year)
    done = store.job(job.id)
    if done and done.status == "done":
        store.put_bikes([bike.model_copy(update={"manualId": manual_id})])
    return {
        "jobId": job.id,
        "manualId": manual_id,
        "bikeId": bike_id,
        "replaced": previous,
        "state": (done.status if done else "error"),
        "error": done.error if done else "no job",
    }


def _handle(entry: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    path = entry.get("path_display") or entry.get("path_lower") or entry.get("name") or ""
    record: dict[str, Any] = {"name": entry.get("name"), "path": path, "at": time.time()}
    meta = parse_meta(path)
    if not meta:
        record |= {"state": "unmatched", "reason": "no make/model/year in the path"}
        return record
    make, model, year = meta
    record |= {"make": make, "model": model, "year": year}
    try:
        data = download(entry.get("id") or path)
    except DropboxError as exc:
        return record | {"state": "error", "reason": str(exc)}
    if len(data) > MAX_PDF:
        return record | {"state": "error", "reason": f"{len(data)} bytes over the {MAX_PDF} cap"}
    if not data.startswith(b"%PDF"):
        return record | {"state": "skipped", "reason": "not a PDF (magic bytes)"}
    digest = hashlib.sha256(data).hexdigest()
    twin = next((k for k, v in files.items() if v.get("sha256") == digest and v.get("state") == "done"), None)
    if twin:
        return record | {"state": "duplicate", "of": files[twin].get("manualId"), "sha256": digest}
    local = _dir() / f"{digest[:16]}.pdf"
    local.write_bytes(data)
    record |= {"sha256": digest, "bytes": len(data), "file": str(local)}
    try:
        return record | _run_ingest(local, make, model, year)
    except Exception as exc:  # one bad PDF must never stop the folder
        log.exception("dropbox ingest failed for %s", path)
        return record | {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}


def sync_once() -> dict[str, Any]:
    """One pass: ask Dropbox what changed, ingest every new PDF, store the cursor. Never raises."""
    if not enabled():
        return {"enabled": False, "queued": 0, "reason": "no token"}
    data = state()
    try:
        entries, cursor = changes(data.get("cursor"))
    except DropboxError as exc:
        data["lastError"] = str(exc)
        data["lastPollAt"] = time.time()
        _save(data)
        return {"enabled": True, "error": str(exc), "retryAfter": exc.retry_after, "queued": 0}
    files = data.setdefault("files", {})
    handled: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get(".tag") != "file" or not str(entry.get("name", "")).lower().endswith(".pdf"):
            continue
        key = entry.get("id") or entry.get("path_lower") or entry.get("name")
        known = files.get(key)
        if known and known.get("rev") == entry.get("rev") and known.get("state") in ("done", "duplicate", "unmatched"):
            continue  # same revision, already settled
        record = _handle(entry, files) | {"rev": entry.get("rev")}
        files[key] = record
        handled.append(record)
    data["cursor"] = cursor
    data["lastPollAt"] = time.time()
    data["lastError"] = None
    data["passes"] = int(data.get("passes") or 0) + 1
    _save(data)
    return {
        "enabled": True,
        "seen": len(entries),
        "queued": len(handled),
        "done": sum(1 for r in handled if r.get("state") == "done"),
        "unmatched": sum(1 for r in handled if r.get("state") == "unmatched"),
        "files": handled,
    }


# ---------------------------------------------------------------- the watcher


def _loop() -> None:
    misses = 0
    while enabled():
        _wake.clear()  # before the pass, so a wake raised during it is not swallowed
        try:
            result = sync_once()
            misses = 0 if not result.get("error") else misses + 1
            wait = float(result.get("retryAfter") or 0)
            cursor = state().get("cursor")
            if wait:
                _wake.wait(wait)
            elif cursor and not result.get("error"):
                if not longpoll(cursor):
                    continue  # timed out with no change: go straight round again
            else:
                _wake.wait(BACKOFF[min(misses, len(BACKOFF) - 1)] if misses else IDLE_POLL)
        except Exception as exc:
            misses += 1
            log.warning("dropbox watcher: %s: %s", type(exc).__name__, exc)
            _wake.wait(BACKOFF[min(misses, len(BACKOFF) - 1)])


def start() -> bool:
    """Idempotent. Returns True when a watcher thread is running after the call."""
    global _thread
    with _lock:
        if not enabled():
            return False
        if _thread and _thread.is_alive():
            return True
        _thread = threading.Thread(target=_loop, name="dropbox-watch", daemon=True)
        _thread.start()
        return True


def watching() -> bool:
    return bool(_thread and _thread.is_alive())


# ---------------------------------------------------------------- routes


@router.get("/config")
def config() -> dict[str, Any]:
    """What the UI may switch on. Mirrors GET /voice/config: no key, no button."""
    return {"enabled": enabled(), "folder": folder() or "/", "webhook": bool(app_secret()), "watching": watching()}


@router.get("/status")
def status(limit: int = 50) -> dict[str, Any]:
    data = state()
    files = list(data.get("files", {}).values())
    files.sort(key=lambda f: f.get("at") or 0, reverse=True)
    counts: dict[str, int] = {}
    for f in files:
        counts[f.get("state") or "?"] = counts.get(f.get("state") or "?", 0) + 1
    return {
        "enabled": enabled(),
        "watching": watching(),
        "folder": folder() or "/",
        "cursor": bool(data.get("cursor")),
        "lastPollAt": data.get("lastPollAt"),
        "lastError": data.get("lastError"),
        "passes": data.get("passes") or 0,
        "counts": counts,
        "files": files[: max(0, limit)],
    }


@router.post("/sync")
def sync(tasks: BackgroundTasks, wait: bool = False) -> dict[str, Any]:
    """Run a pass now. `wait=true` blocks until the folder is indexed - demo and test only."""
    if not enabled():
        raise HTTPException(503, "no Dropbox token")
    start()
    if wait:
        return sync_once()
    tasks.add_task(sync_once)
    _wake.set()
    return {"enabled": True, "started": True} | status(limit=0)


@router.get("/webhook")
def webhook_verify(challenge: str = "") -> PlainTextResponse:
    """Dropbox verifies a webhook URI by GETting it with ?challenge=; echo it back as text/plain
    with nosniff, per docs.dropboxapi.com/dropbox-api/docs/webhooks."""
    return PlainTextResponse(challenge, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/webhook")
async def webhook(request: Request, tasks: BackgroundTasks) -> dict[str, Any]:
    """A change notification. The body names accounts, never files, so the only sane response is to
    verify the HMAC and go ask list_folder/continue what actually moved."""
    secret = app_secret()
    if not secret:
        raise HTTPException(503, "no app secret")
    body = await request.body()
    want = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, request.headers.get("X-Dropbox-Signature", "")):
        raise HTTPException(403, "bad signature")
    tasks.add_task(sync_once)
    _wake.set()
    return {"ok": True}


if enabled() and os.getenv("DROPBOX_AUTOSTART", "1") != "0":
    start()

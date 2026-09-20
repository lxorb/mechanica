"""Ingest on demand and cache. A rider picks a bike we have never seen; the manual is on disk a minute later.

ensure(bike_id) is cheap to call and safe to hammer: one job per manual id, whoever asks second joins the first.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from typing import NamedTuple

from . import ingest
from .config import settings
from .models import Bike, IngestJob, Manual, RegistryEntry
from .store import get_store

try:  # app.registry owns the id scheme; on-demand must survive that package being edited under it
    from .registry._http import slug
except Exception:

    def slug(*parts: object) -> str:
        raw = "-".join(str(p) for p in parts if p not in (None, ""))
        raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
        return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", raw.lower())).strip("-")

log = logging.getLogger("ondemand")

def is_pdf(url: str) -> bool:
    """app.registry owns the host list. The suffix fallback only keeps this path alive while that package is edited."""
    try:
        from .registry import _is_pdf as upstream

        return bool(upstream(url))
    except Exception:
        return url.split("?", 1)[0].split("#", 1)[0].lower().endswith(".pdf")


_is_pdf = is_pdf

WORKERS = 32
BATCH = 5
YEAR_WINDOW = 6
MIN_SECTIONS = 10
# URLs that look like a manual but are not one: Kawasaki's ebook viewer (HTML) and its quick-reference supplements
NOT_A_MANUAL = ("_ebook",)
THIN = ("/99888-",)

FAIL_COOLDOWN = 6 * 3600

_jobs: dict[str, str] = {}
_fails: dict[str, dict] = {}
_lock = threading.Lock()


def _fail_path(manual_id: str):
    return settings.data_dir / "failed" / f"{manual_id}.json"


def forget_failure(manual_id: str) -> None:
    _fails.pop(manual_id, None)
    try:
        _fail_path(manual_id).unlink(missing_ok=True)
    except OSError:
        pass


def remember_failure(manual_id: str, url: str, error: str) -> dict:
    """A manual that cannot be built must stay broken for a while, or every poll starts the job again."""
    record = {"manualId": manual_id, "url": url, "error": error[:500], "at": time.time()}
    _fails[manual_id] = record
    try:
        path = _fail_path(manual_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    except OSError as exc:
        log.warning("%s: could not persist the failure marker: %s", manual_id, exc)
    return record


def recent_failure(manual_id: str) -> dict | None:
    record = _fails.get(manual_id)
    if record is None:
        path = _fail_path(manual_id)
        if path.exists():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                record = None
        if record:
            _fails[manual_id] = record
    if not record:
        return None
    if time.time() - float(record.get("at", 0)) > FAIL_COOLDOWN:
        forget_failure(manual_id)
        return None
    return record
_registry: dict[tuple[str, str], list[RegistryEntry]] = {}
_registry_at = 0.0
_registry_built = 0.0
_registry_lock = threading.Lock()
# On a blob deployment there is no registry.json on disk, so the mtime stamp is 0.0 forever and
# the index would be frozen for the life of the process: a manual the registry agent adds could
# never be found on demand until a redeploy. The store's own listing cache is 60 s, so re-reading
# it every few minutes costs nothing and is the only thing that lets new rows land.
REGISTRY_MAX_AGE = 300.0


def _index() -> dict[tuple[str, str], list[RegistryEntry]]:
    """The registry is 7k rows on disk; re-validating it per request would cost more than the ingest saves."""
    global _registry, _registry_at, _registry_built
    stamp = 0.0
    from .config import settings

    path = settings.data_dir / "registry.json"
    if path.exists():
        stamp = path.stat().st_mtime
    with _registry_lock:
        fresh = time.monotonic() - _registry_built < REGISTRY_MAX_AGE
        if _registry and stamp == _registry_at and fresh:
            return _registry
        built: dict[tuple[str, str], list[RegistryEntry]] = {}
        for e in get_store().registry():
            if e.type == "owner" and e.access == "free" and e.lang.lower().startswith("en") and e.url and _is_pdf(e.url):
                built.setdefault((e.make.lower(), e.model.lower()), []).append(e)
        _registry, _registry_at, _registry_built = built, stamp, time.monotonic()
        return _registry


def manual_id_for(make: str, model: str, year: int, market: str) -> str:
    return slug(make, model, year, market, "om")


def _rows(bike: Bike) -> list[RegistryEntry]:
    entries = [e for e in _index().get((bike.make.lower(), bike.model.lower()), []) if not any(b in e.url for b in NOT_A_MANUAL)]
    if not entries:
        return []
    exact = [e for e in entries if bike.year in (e.years or [])]
    if exact:
        entries = exact
    else:
        near = [e for e in entries if e.years and min(abs(y - bike.year) for y in e.years) <= YEAR_WINDOW]
        entries = near or entries
    entries.sort(
        key=lambda e: (
            1 if any(t in e.url for t in THIN) else 0,
            min((abs(y - bike.year) for y in (e.years or [])), default=99),
            0 if e.market == bike.market else 1,
            -(max(e.years) if e.years else 0),
        )
    )
    return entries


class Source(NamedTuple):
    url: str
    manualId: str
    needsUa: str | None


def _from_entry(entry: RegistryEntry, bike: Bike) -> Source:
    year = bike.year if bike.year in (entry.years or []) else (max(entry.years) if entry.years else bike.year)
    return Source(entry.url, manual_id_for(entry.make, entry.model, year, entry.market), getattr(entry, "needsUa", None))


def source_for(bike: Bike, vin: str | None = None) -> Source | None:
    """Where this bike's free official PDF lives: the bike's own url, then the static registry, then a live resolver."""
    url = getattr(bike, "manualUrl", None)
    if url and _is_pdf(url) and not any(b in url for b in NOT_A_MANUAL):
        known = next((e for e in _index().get((bike.make.lower(), bike.model.lower()), []) if e.url == url), None)
        return Source(url, manual_id_for(bike.make, bike.model, bike.year, bike.market), getattr(known, "needsUa", None))

    entries = _rows(bike)
    if entries:
        return _from_entry(entries[0], bike)

    try:
        from .registry import dynamic

        found = dynamic.resolve(bike, vin)
    except Exception as exc:  # the registry agents own those resolvers; a broken one must not break ensure()
        log.warning("dynamic resolver for %s failed: %s", bike.make, exc)
        found = None
    if found is not None and found.url and _is_pdf(found.url):
        return _from_entry(found, bike)
    return None


def _link(bike_id: str, manual_id: str) -> None:
    store = get_store()
    bike = store.bike(bike_id)
    if bike is not None and bike.manualId != manual_id:
        store.put_bikes([bike.model_copy(update={"manualId": manual_id})])


def _work(job_id: str, source: Source, bike: Bike) -> None:
    store = get_store()
    url, manual_id = source.url, source.manualId
    try:
        manual = ingest.run(
            job_id,
            url,
            manual_id,
            [bike.id],
            bike.make,
            bike.model,
            bike.year,
            batch=BATCH,
            workers=WORKERS,
            early=True,
            needs_ua=source.needsUa,
        )
        from .ingest import curate

        curate.apply(manual.model_copy(update={"source": url}))
        _link(bike.id, manual_id)
        forget_failure(manual_id)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:500]
        log.warning("%s: on-demand ingest failed: %s", manual_id, message)
        remember_failure(manual_id, url, message)
        job = store.job(job_id) or IngestJob(id=job_id, manualId=manual_id, status="error")
        store.put_job(job.model_copy(update={"status": "error", "error": message}))
    finally:
        with _lock:
            if _jobs.get(manual_id) == job_id:
                _jobs.pop(manual_id, None)


def ensure(bike_id: str, vin: str | None = None) -> dict:
    """"ready" when the manual is on disk, "running" with a jobId while it is being built, "none" when no free PDF is known.

    vin is passed through to the per-make dynamic resolvers, which is the only way some portals hand out a manual.
    """
    store = get_store()
    bike = store.bike(bike_id)
    if bike is None:
        return {"status": "none", "reason": "unknown bike"}

    if bike.manualId:
        manual = store.manual(bike.manualId)
        if manual is not None and len(manual.sections) >= MIN_SECTIONS:
            return {"status": "ready", "manualId": manual.id, "pages": manual.pages}

    source = source_for(bike, vin)
    if source is None:
        return {"status": "none", "reason": "no free manual known"}
    manual_id = source.manualId

    manual = store.manual(manual_id)
    if manual is not None and len(manual.sections) >= MIN_SECTIONS:
        _link(bike_id, manual_id)
        forget_failure(manual_id)
        return {"status": "ready", "manualId": manual_id, "pages": manual.pages}

    broken = recent_failure(manual_id)
    if broken:
        return {
            "status": "error",
            "manualId": manual_id,
            "error": broken.get("error", "ingest failed"),
            "retryAfter": float(broken.get("at", 0)) + FAIL_COOLDOWN,
        }

    with _lock:
        running = _jobs.get(manual_id)
        if running is None:
            job_id = uuid.uuid4().hex[:12]
            _jobs[manual_id] = job_id
            store.put_job(IngestJob(id=job_id, manualId=manual_id, status="queued"))
            threading.Thread(target=_work, args=(job_id, source, bike), daemon=True, name=f"ondemand-{manual_id}").start()
        else:
            job_id = running

    job = store.job(job_id)
    return {
        "status": "running",
        "manualId": manual_id,
        "jobId": job_id,
        "done": job.done if job else 0,
        "pages": job.pages if job else 0,
    }


def status(job_id: str) -> IngestJob | None:
    return get_store().job(job_id)


def cached(manual_id: str) -> Manual | None:
    return get_store().manual(manual_id)

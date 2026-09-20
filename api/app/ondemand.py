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
# A job nobody has written for this long is a job whose replica is gone: GET /ingest/{id} reports
# it as an error, and the next ensure() starts a fresh one. The worker beats every HEARTBEAT
# seconds, so this is twelve missed beats, not a slow stage.
STALE_AFTER = 60.0
HEARTBEAT = 5.0

_jobs: dict[str, str] = {}
_fails: dict[str, dict] = {}
_lock = threading.Lock()
_record_lock = threading.Lock()

# --- records every replica must agree on ----------------------------------------------------------
#
# The deployment is 1-3 replicas of the same container, so a dict in this process is not a lock and
# a file under DATA_DIR is not a record - DATA_DIR is the container's own ephemeral disk. Both the
# ingest lease (BUG-13) and the ingest-failure markers (BUG-16) are exactly that kind of state.
#
# BlobStore is the only store that spans replicas and its ETag compare-and-set is the only atomic
# primitive it has, so that is what a lease is built on. Its `_cas`/`_read_json`/`_write_json` are
# looked up by name on purpose, not imported: a store that does not have them - FileStore in dev and
# in the tests - falls back to a file under DATA_DIR, which is all a single-process deployment needs,
# and a store that grows them gets the cross-replica lease for free. A store we cannot reach at all
# never blocks an ingest: the lease simply stops being a lease and we are back to the old,
# duplicate-work behaviour.


def _shared():
    """The store when it can compare-and-set a shared JSON document, else None."""
    store = get_store()
    ok = all(callable(getattr(store, name, None)) for name in ("_cas", "_read_json", "_write_json"))
    return store if ok else None


def _read_record(name: str) -> dict | None:
    store = _shared()
    if store is not None:
        try:
            doc = store._read_json(name, None)
        except Exception as exc:
            log.warning("%s: shared read failed: %s", name, exc)
            return None
        return doc if isinstance(doc, dict) else None
    path = settings.data_dir / name
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _write_record(name: str, doc: dict) -> None:
    store = _shared()
    if store is not None:
        try:
            store._write_json(name, doc)
        except Exception as exc:
            log.warning("%s: shared write failed: %s", name, exc)
        return
    path = settings.data_dir / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
    except OSError as exc:
        log.warning("%s: could not write the record: %s", name, exc)


def _drop_record(name: str) -> None:
    store = _shared()
    if store is not None:
        _write_record(name, {})
        return
    try:
        (settings.data_dir / name).unlink(missing_ok=True)
    except OSError:
        pass


def _swap_record(name: str, decide) -> dict | None:
    """`decide(current) -> the document to put in force`, applied atomically.

    Returning `current` unchanged is how a caller says "somebody else won"; the write still happens
    (identical bytes) so the compare-and-set stays one round trip. None means the store could not be
    reached and nothing is in force.
    """
    store = _shared()
    if store is not None:
        chosen: dict | None = None

        def merge(current):
            nonlocal chosen
            chosen = decide(current if isinstance(current, dict) else None)
            return chosen

        try:
            store._cas(name, merge)
        except Exception as exc:
            log.warning("%s: shared compare-and-set failed: %s", name, exc)
            return None
        return chosen
    with _record_lock:
        chosen = decide(_read_record(name))
        _write_record(name, chosen)
        return chosen


# --- one ingest per manual, across replicas ---------------------------------------------------------
#
# `leases/{manualId}.json` holds {"jobId": ..., "at": <unix seconds>} and is only honoured for
# STALE_AFTER seconds after its last renewal. A replica may start an ingest only if its own job id
# came back from take_lease(): of two replicas reading the same free or expired lease exactly one
# wins the ETag race and the other is handed the winner's job id, which it joins instead of paying
# a second time for the same manual. The owner renews every HEARTBEAT seconds while it works, so a
# replica that is recycled mid-ingest releases the manual by simply going quiet - and never holds it
# for longer than STALE_AFTER. Renewal never steals a lease back once it has lapsed and somebody
# else has taken it, so there is at most one owner at any moment.


def _lease_name(manual_id: str) -> str:
    return f"leases/{manual_id}.json"


def _lease_live(doc: dict | None, now: float | None = None) -> bool:
    if not doc or not doc.get("jobId"):
        return False
    return (now or time.time()) - float(doc.get("at") or 0) <= STALE_AFTER


def lease_holder(manual_id: str) -> str | None:
    """The job id currently building this manual, as far as the shared record knows."""
    doc = _read_record(_lease_name(manual_id))
    return str(doc["jobId"]) if _lease_live(doc) else None


def take_lease(manual_id: str, job_id: str, force: bool = False) -> str | None:
    """Try to become the one replica building this manual.

    Returns the job id that owns it afterwards - `job_id` when we took it, somebody else's when
    they hold a live one - or None when the record could not be written at all.
    """

    def decide(current):
        if not force and _lease_live(current) and current.get("jobId") != job_id:
            return current
        return {"jobId": job_id, "at": time.time()}

    doc = _swap_record(_lease_name(manual_id), decide)
    if doc is None:
        return None
    holder = doc.get("jobId")
    return str(holder) if holder else None


def renew_lease(manual_id: str, job_id: str) -> bool:
    """Push the lease forward. False once somebody else owns it, which can only happen after ours
    has already lapsed - a beat that slept through STALE_AFTER must not steal the manual back."""

    def decide(current):
        if _lease_live(current) and current.get("jobId") != job_id:
            return current
        return {"jobId": job_id, "at": time.time()}

    doc = _swap_record(_lease_name(manual_id), decide)
    return bool(doc) and doc.get("jobId") == job_id


def release_lease(manual_id: str, job_id: str) -> None:
    def decide(current):
        if current and current.get("jobId") not in (None, job_id):
            return current
        return {"jobId": None, "at": 0.0}

    _swap_record(_lease_name(manual_id), decide)


def alive(job: IngestJob | None, now: float | None = None) -> bool:
    """Is somebody still working on this job?

    `updatedAt` is the cheap signal and answers without leaving the process on every poll of a
    healthy ingest. The lease is the authoritative one, because two stages are legitimately silent
    for minutes: waiting for one of the three ingest slots, and a single slow LLM batch.
    """
    if job is None or job.status not in ("queued", "running"):
        return False
    now = now or time.time()
    if now - float(job.updatedAt or 0) <= STALE_AFTER:
        return True
    doc = _read_record(_lease_name(job.manualId))
    return _lease_live(doc, now) and doc.get("jobId") == job.id


def stalled(job: IngestJob | None) -> bool:
    """A job that says it is being worked on and is not. See docs/qa/BUGS.md BUG-13."""
    return job is not None and job.status in ("queued", "running") and not alive(job)


def touch(job_id: str) -> bool:
    """Stamp the job so a watcher can see it is still being worked on. False once it has reached a
    terminal state, which is the beat's signal to stop."""
    store = get_store()
    job = store.job(job_id)
    if job is None or job.status not in ("queued", "running"):
        return False
    store.put_job(job.model_copy(update={"updatedAt": time.time()}))
    return True


def settle(job_id: str) -> None:
    """Called once the beat is stopped, so the terminal state is the last word.

    The beat writes back the job document it read a moment earlier; if ingest.run() wrote "done"
    inside that one round trip the beat would put "running" back and nothing would ever move it
    again. One re-read closes the window.
    """
    store = get_store()
    job = store.job(job_id)
    if job is not None and job.status in ("queued", "running"):
        store.put_job(
            job.model_copy(
                update={
                    "status": "done",
                    "done": max(job.done, job.pages),
                    "stage": "done",
                    "error": None,
                    "updatedAt": time.time(),
                }
            )
        )


class Beat:
    """Proof that this replica is still on this manual: it renews the lease and stamps the job
    every HEARTBEAT seconds. A recycled replica stops beating and STALE_AFTER seconds later its job
    reads as an error instead of leaving the Confirm screen polling a dead id for fifteen minutes."""

    def __init__(self, job_id: str, manual_id: str):
        self.job_id = job_id
        self.manual_id = manual_id
        self.beats = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"beat-{manual_id}")

    def start(self) -> "Beat":
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT):
            try:
                renew_lease(self.manual_id, self.job_id)
                if not touch(self.job_id):
                    return
                self.beats += 1
            except Exception as exc:  # a beat that throws must never take the ingest down with it
                log.warning("%s: heartbeat failed: %s", self.manual_id, exc)

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10.0)


def forget_failure(manual_id: str) -> None:
    _fails.pop(manual_id, None)
    _drop_record(f"failed/{manual_id}.json")


def remember_failure(manual_id: str, url: str, error: str) -> dict:
    """A manual that cannot be built must stay broken for a while, or every poll starts the job again.

    Shared, not per-replica: on the container's own disk replica A refused a broken manual for six
    hours while replica B cheerfully retried it every time (BUG-16).
    """
    record = {"manualId": manual_id, "url": url, "error": error[:500], "at": time.time()}
    _fails[manual_id] = record
    _write_record(f"failed/{manual_id}.json", record)
    return record


def recent_failure(manual_id: str) -> dict | None:
    record = _fails.get(manual_id)
    if record is None:
        record = _read_record(f"failed/{manual_id}.json")
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
    beat = Beat(job_id, manual_id).start()
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
        beat.stop()
        settle(job_id)
        from .ingest import curate

        curate.apply(manual.model_copy(update={"source": url}))
        _link(bike.id, manual_id)
        forget_failure(manual_id)
    except Exception as exc:
        beat.stop()
        message = f"{type(exc).__name__}: {exc}"[:500]
        log.warning("%s: on-demand ingest failed: %s", manual_id, message)
        remember_failure(manual_id, url, message)
        job = store.job(job_id) or IngestJob(id=job_id, manualId=manual_id, status="error")
        store.put_job(job.model_copy(update={"status": "error", "error": message, "updatedAt": time.time()}))
    finally:
        beat.stop()
        release_lease(manual_id, job_id)
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
    if running is not None:
        if alive(store.job(running)):
            return _running(manual_id, running)
        # this replica's own job died without unwinding (the thread is gone, the entry is not)
        with _lock:
            if _jobs.get(manual_id) == running:
                _jobs.pop(manual_id, None)

    # Nobody here is on it. Take the manual across replicas before spending a cent on it.
    job_id = uuid.uuid4().hex[:12]
    holder = take_lease(manual_id, job_id)
    if holder is not None and holder != job_id:
        other = store.job(holder)
        # `other is None` is the winner of a race a millisecond ago: it holds a live lease and is
        # about to write its job document. A live lease is enough - never race it for the manual.
        if other is None or alive(other):
            return _running(manual_id, holder, other)
        # the lease names a finished job nobody unwound (a crash between the last write and the
        # release): its replica is gone, so take the manual over rather than wait out the TTL
        holder = take_lease(manual_id, job_id, force=True)
        if holder is not None and holder != job_id:
            return _running(manual_id, holder)

    with _lock:
        _jobs[manual_id] = job_id
    store.put_job(IngestJob(id=job_id, manualId=manual_id, status="queued", updatedAt=time.time()))
    threading.Thread(target=_work, args=(job_id, source, bike), daemon=True, name=f"ondemand-{manual_id}").start()
    return _running(manual_id, job_id)


def _running(manual_id: str, job_id: str, job: IngestJob | None = None) -> dict:
    job = job or get_store().job(job_id)
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

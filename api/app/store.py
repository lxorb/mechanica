"""System of record. FileStore = JSON under DATA_DIR. MongoStore (app/store_mongo.py) implements the same Protocol."""

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .config import settings
from .models import Bike, CostEvent, IngestJob, Manual, Page, RegistryEntry, Spec


class Store(Protocol):
    def bikes(self) -> list[Bike]: ...
    def bike(self, bike_id: str) -> Bike | None: ...
    def put_bikes(self, bikes: list[Bike]) -> None: ...
    def manuals(self) -> list[Manual]: ...
    def manual(self, manual_id: str) -> Manual | None: ...
    def put_manual(self, manual: Manual) -> None: ...
    def pages(self, manual_id: str) -> list[Page]: ...
    def put_pages(self, manual_id: str, pages: list[Page]) -> None: ...
    def specs(self, manual_id: str) -> list[Spec]: ...
    def put_specs(self, manual_id: str, specs: list[Spec]) -> None: ...
    def registry(self, make: str | None = None, model: str | None = None, year: int | None = None) -> list[RegistryEntry]: ...
    def put_registry(self, entries: list[RegistryEntry]) -> None: ...
    def job(self, job_id: str) -> IngestJob | None: ...
    def put_job(self, job: IngestJob) -> None: ...
    def offers(self, manual_id: str, part_id: str) -> dict | None:
        """Last retailer lookup for one part, as written by put_offers, or None. Optional: a store that
        does not implement the pair just means every /parts/offers call is a cold fetch."""
        return None

    def put_offers(self, manual_id: str, part_id: str, result: dict) -> None: ...
    def log_cost(self, event: CostEvent) -> None: ...
    def costs(self) -> list[CostEvent]: ...
    def pdf_url(self, manual_id: str) -> str | None:
        """Public URL the browser can fetch the PDF from, or None when only the API can serve it."""
        return None


def _read(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ read cache
#
# A FileStore re-parses the same files on every call, and the four corpus-sized reads
# dominate everything else: manuals/ is 508 documents and 62 MB (~57 s), registry.json
# is 99k rows (~13 s), costs.jsonl 44k events (~17 s) and bikes.json 30k rows (~0.8 s).
# The API pays that per request and the test suite paid it per test, because each test
# drops the module-level store and builds a fresh FileStore over the same directory.
#
# So the cache lives here, not on the instance: (root, kind) -> (stamp, value), where the
# stamp is the filesystem fingerprint of the file(s) behind that read plus a write counter
# this module bumps on every write it makes. The stat half notices another process; the
# counter half notices our own writes, which Windows can stamp with the same mtime when two
# land inside one clock tick. Either half changing re-reads, so a caller only ever sees what
# is on disk - the cache is invisible, and nothing about the read path's contract moved.
#
# What is cached is the *parsed JSON*, never the models built from it. A store hands back objects
# the caller owns - put_bikes, mutate what bike() returned, read it back unchanged is a contract
# the suite states outright - so every call still validates its own, and holding the models would
# quietly make them shared. Validation copies every field out of the dict, so the cached JSON is
# only ever read. `_registry_rows` is the one documented exception and keeps its own rule below.

_cache_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[Any, Any]] = {}
_writes: dict[tuple[str, str], int] = {}


def _touch(root: Path, kind: str) -> None:
    """A write landed on `kind` under `root`: whatever is cached for it is now history."""
    key = (str(root), kind)
    with _cache_lock:
        _writes[key] = _writes.get(key, 0) + 1
        _cache.pop(key, None)


def _file_stamp(path: Path) -> tuple[int, int] | None:
    """(mtime, size), or None when the file is not there - which is itself a stamp."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _dir_stamp(folder: Path, suffix: str = ".json") -> tuple | None:
    """One (name, mtime, size) row per file, so a rewrite, a new file and a deleted one all show."""
    try:
        with os.scandir(folder) as entries:
            return tuple(sorted(
                (e.name, e.stat().st_mtime_ns, e.stat().st_size)
                for e in entries
                if e.name.endswith(suffix) and e.is_file()
            ))
    except OSError:
        return None


# Every entry is bounded, because the keys are open-ended in both directions: one manual is up to a
# megabyte once parsed and /ask, /chat and both /parts routes load one per request, and the corpus
# reads are keyed on the root, of which the test suite alone makes hundreds. Past the ceiling the
# oldest go first; a dropped entry only means the next read parses again. A deployment has one root,
# so these never bite in production.
_KEEP = {"bikes": 4, "costs": 4, "manuals": 4, "registry": 4, "manual:": 64}


def _prune(kind: str) -> None:
    family = "manual:" if kind.startswith("manual:") else kind
    ceiling = _KEEP.get(family)
    if ceiling is None:
        return
    with _cache_lock:
        keys = [k for k in _cache if (k[1].startswith("manual:") if family == "manual:" else k[1] == family)]
        for key in keys[: max(0, len(keys) - ceiling)]:  # dicts keep insertion order: oldest first
            _cache.pop(key, None)


def _cached(root: Path, kind: str, stamp: Any, build: Callable[[], Any]) -> Any:
    key = (str(root), kind)
    with _cache_lock:
        generation = _writes.get(key, 0)
        hit = _cache.get(key)
        if hit is not None and hit[0] == (generation, stamp):
            return hit[1]
    value = build()  # outside the lock: parsing 62 MB must not block every other reader
    with _cache_lock:
        if _writes.get(key, 0) == generation:  # a write that landed while we parsed wins
            _cache.pop(key, None)  # re-inserted below, so this root counts as the newest
            _cache[key] = ((generation, stamp), value)
    _prune(kind)
    return value


class FileStore:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()

    def _bikes_path(self) -> Path:
        return self.root / "bikes.json"

    def bikes(self) -> list[Bike]:
        with self.lock:
            path = self._bikes_path()
            return [Bike.model_validate(b) for b in _cached(self.root, "bikes", _file_stamp(path), lambda: _read(path, []))]

    def bike(self, bike_id: str) -> Bike | None:
        return next((b for b in self.bikes() if b.id == bike_id), None)

    def put_bikes(self, bikes: list[Bike]) -> None:
        with self.lock:
            merged = {b.id: b for b in self.bikes()}
            for b in bikes:
                merged[b.id] = b
            _write(self._bikes_path(), [b.model_dump(exclude_none=True) for b in merged.values()])
            _touch(self.root, "bikes")

    def _manuals_dir(self) -> Path:
        return self.root / "manuals"

    def manuals(self) -> list[Manual]:
        with self.lock:
            folder = self._manuals_dir()
            rows = _cached(
                self.root,
                "manuals",
                _dir_stamp(folder),
                lambda: [_read(p, {}) for p in sorted(folder.glob("*.json"))] if folder.exists() else [],
            )
            return [Manual.model_validate(row) for row in rows]

    def manual(self, manual_id: str) -> Manual | None:
        with self.lock:
            path = self._manuals_dir() / f"{manual_id}.json"
            stamp = _file_stamp(path)
            if stamp is None:
                return None
            return Manual.model_validate(_cached(self.root, f"manual:{manual_id}", stamp, lambda: _read(path, {})))

    def put_manual(self, manual: Manual) -> None:
        with self.lock:
            _write(self._manuals_dir() / f"{manual.id}.json", manual.model_dump(exclude_none=True))
            _touch(self.root, "manuals")
            _touch(self.root, f"manual:{manual.id}")

    def pages(self, manual_id: str) -> list[Page]:
        with self.lock:
            return [Page.model_validate(p) for p in _read(self.root / "pages" / f"{manual_id}.json", [])]

    def put_pages(self, manual_id: str, pages: list[Page]) -> None:
        with self.lock:
            _write(self.root / "pages" / f"{manual_id}.json", [p.model_dump() for p in pages])

    def specs(self, manual_id: str) -> list[Spec]:
        with self.lock:
            return [Spec.model_validate(s) for s in _read(self.root / "specs" / f"{manual_id}.json", [])]

    def put_specs(self, manual_id: str, specs: list[Spec]) -> None:
        with self.lock:
            _write(self.root / "specs" / f"{manual_id}.json", [s.model_dump(exclude_none=True) for s in specs])

    def _registry_path(self) -> Path:
        return self.root / "registry.json"

    def _registry_rows(self) -> list[RegistryEntry]:
        """Every row, validated once per version of the file.

        registry.json is 40 MB and 99k rows: `json.loads` costs ~3.7 s and validating them ~8.9 s,
        and the API and the test suite both call this many times per process. It rides the module
        cache above, keyed on the file's own (mtime_ns, size), so any writer - put_registry here,
        the merge tool's wholesale rewrite, another process - invalidates it without needing to know
        the cache exists. A file that vanishes or is unreadable falls back to an empty list, exactly
        as before.

        This is the one read that caches the *models*, not the JSON behind them, because validating
        99k rows is the expensive half and no caller owns a row.
        **The rows are therefore shared, and a caller must not mutate one in place.** Nothing does:
        the only two mutators (`registry.merge_ua`, which stamps docKind/needsUa, and the merge
        tool's `--restamp`) copy first. Mutating a row here would change what every later reader in
        the process sees, and would survive until the file changed.
        """
        path = self._registry_path()
        if not path.exists():
            return []
        return _cached(self.root, "registry", _file_stamp(path), lambda: [RegistryEntry.model_validate(e) for e in _read(path, [])])

    def registry(self, make: str | None = None, model: str | None = None, year: int | None = None) -> list[RegistryEntry]:
        with self.lock:
            entries = list(self._registry_rows())  # a fresh list; the rows themselves are shared
        if make:
            entries = [e for e in entries if e.make.lower() == make.lower()]
        if model:
            entries = [e for e in entries if e.model.lower() == model.lower()]
        if year:
            entries = [e for e in entries if year in e.years]
        return entries

    def put_registry(self, entries: list[RegistryEntry]) -> None:
        with self.lock:
            merged = {e.id: e for e in self.registry()}
            for e in entries:
                merged[e.id] = e
            _write(self.root / "registry.json", [e.model_dump(exclude_none=True) for e in merged.values()])
            _touch(self.root, "registry")

    def job(self, job_id: str) -> IngestJob | None:
        with self.lock:
            data = _read(self.root / "jobs.json", {})
            return IngestJob.model_validate(data[job_id]) if job_id in data else None

    def put_job(self, job: IngestJob) -> None:
        with self.lock:
            data = _read(self.root / "jobs.json", {})
            data[job.id] = job.model_dump(exclude_none=True)
            _write(self.root / "jobs.json", data)

    def _offers_path(self, manual_id: str, part_id: str) -> Path:
        return self.root / "offers" / manual_id / f"{part_id}.json"

    def offers(self, manual_id: str, part_id: str) -> dict | None:
        with self.lock:
            return _read(self._offers_path(manual_id, part_id), None)

    def put_offers(self, manual_id: str, part_id: str, result: dict) -> None:
        with self.lock:
            _write(self._offers_path(manual_id, part_id), result)

    def _costs_path(self) -> Path:
        return self.root / "costs.jsonl"

    def log_cost(self, event: CostEvent) -> None:
        with self.lock:
            path = self._costs_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump()) + "\n")
            _touch(self.root, "costs")

    def costs(self) -> list[CostEvent]:
        with self.lock:
            path = self._costs_path()
            if not path.exists():
                return []
            rows = _cached(
                self.root,
                "costs",
                _file_stamp(path),
                lambda: [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()],
            )
            return [CostEvent.model_validate(row) for row in rows]

    def pdf_url(self, manual_id: str) -> str | None:
        return None


DEFAULT_PAGES = 143


def max_manual_pages(store: "Store | None" = None) -> int:
    """The largest page count in the store, without downloading every Manual.

    /cost needs exactly this number and nothing else about a Manual. Reading it out of
    `manuals()` meant pulling all 535 documents (~72 MB of JSON, ~7.5 s measured live) on
    every cold call and holding them in the listings cache for a minute; the blob listing
    already carries the page count as metadata.
    """
    store = store or get_store()
    summaries = getattr(store, "manual_summaries", None)
    if summaries is not None:
        try:
            counts = [int(row.get("pages") or 0) for row in summaries()]
        except Exception:
            counts = []
    else:
        counts = [m.pages for m in store.manuals()]
    return max([n for n in counts if n > 0] or [DEFAULT_PAGES])


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        if settings.azure_storage_connection_string or settings.azure_storage_account:
            from .store_blob import BlobStore

            _store = BlobStore(
                settings.azure_storage_connection_string
                or f"https://{settings.azure_storage_account}.blob.core.windows.net",
                data_container=settings.azure_data_container,
                pdf_container=settings.azure_pdf_container,
                pdf_base=settings.azure_pdf_base,
            )
        elif settings.mongodb_uri:
            from .store_mongo import MongoStore

            _store = MongoStore(settings.mongodb_uri)
        else:
            _store = FileStore(settings.data_dir)
    return _store

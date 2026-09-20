"""System of record. FileStore = JSON under DATA_DIR. MongoStore (app/store_mongo.py) implements the same Protocol."""

import json
import threading
from pathlib import Path
from typing import Protocol

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


class FileStore:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()
        self._registry_cache: tuple[tuple[int, int], list[RegistryEntry]] | None = None

    def _bikes_path(self) -> Path:
        return self.root / "bikes.json"

    def bikes(self) -> list[Bike]:
        with self.lock:
            return [Bike.model_validate(b) for b in _read(self._bikes_path(), [])]

    def bike(self, bike_id: str) -> Bike | None:
        return next((b for b in self.bikes() if b.id == bike_id), None)

    def put_bikes(self, bikes: list[Bike]) -> None:
        with self.lock:
            merged = {b.id: b for b in self.bikes()}
            for b in bikes:
                merged[b.id] = b
            _write(self._bikes_path(), [b.model_dump(exclude_none=True) for b in merged.values()])

    def manuals(self) -> list[Manual]:
        with self.lock:
            folder = self.root / "manuals"
            return [Manual.model_validate(_read(p, {})) for p in sorted(folder.glob("*.json"))] if folder.exists() else []

    def manual(self, manual_id: str) -> Manual | None:
        with self.lock:
            path = self.root / "manuals" / f"{manual_id}.json"
            return Manual.model_validate(_read(path, {})) if path.exists() else None

    def put_manual(self, manual: Manual) -> None:
        with self.lock:
            _write(self.root / "manuals" / f"{manual.id}.json", manual.model_dump(exclude_none=True))

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

        registry.json is 40 MB and 99k rows: `json.loads` costs ~1.8 s and validating them ~3.0 s,
        and the API and the test suite both call this many times per process. The cache key is the
        file's own (mtime_ns, size), so any writer - put_registry here, the merge tool's wholesale
        rewrite, another process - invalidates it without needing to know the cache exists. A file
        that vanishes or is unreadable falls back to an empty list, exactly as before.

        **The rows are shared, so a caller must not mutate one in place.** Nothing in the tree does:
        the only two mutators (`registry.merge_ua`, which stamps docKind/needsUa, and the merge
        tool's `--restamp`) copy first. Mutating a row here would change what every later reader in
        the process sees, and would survive until the file changed.
        """
        path = self._registry_path()
        try:
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._registry_cache = None
            return []
        cached = self._registry_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        rows = [RegistryEntry.model_validate(e) for e in _read(path, [])]
        self._registry_cache = (key, rows)
        return rows

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

    def log_cost(self, event: CostEvent) -> None:
        with self.lock:
            path = self.root / "costs.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.model_dump()) + "\n")

    def costs(self) -> list[CostEvent]:
        with self.lock:
            path = self.root / "costs.jsonl"
            if not path.exists():
                return []
            return [CostEvent.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

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

"""BlobStore: the Store protocol on Azure Blob Storage. Enabled by AZURE_STORAGE_CONNECTION_STRING
or AZURE_STORAGE_ACCOUNT (see config.py). Built for thousands of manuals and many parallel ingest workers.

Two containers:
  pdf   public blob read  -> manual PDFs, fetched straight by the browser (range requests, no API hop)
  data  private           -> everything else

Layout in `data`:
  manuals/{id}.json   the Manual, plus blob metadata (title/pagecount/sections/bikeids) so a listing
                      can answer /manuals without downloading every document
  pages/{id}.json     the page text layer (big; LRU + TTL in memory)
  specs/{id}.json
  links/{bikeId}.json one tiny blob per bike an ingest worker touched, merged over bikes.json on read
  bikes.json          the bulk catalogue
  registry.json       the manual registry
  jobs/{id}.json      one blob per ingest job, never cached
  offers/{manualId}/{partId}.json  the last retailer lookup for one part, re-fetched when a day old
  costs/{yyyymmdd}.jsonl  append blobs; concurrent appends are atomic server side

Concurrency: nothing does read-modify-write on a shared blob without an ETag. Single-bike writes do not
touch a shared blob at all - they drop a link blob, and bikes() merges. compact_bikes() folds the links
back into bikes.json when there are too many of them.
"""

import json
import logging
import random
import threading
import time
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

from .models import Bike, CostEvent, IngestJob, Manual, Page, RegistryEntry, Spec

logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

log = logging.getLogger("store.blob")

JSON = ContentSettings(content_type="application/json")
NDJSON = ContentSettings(content_type="application/x-ndjson")
PDF = ContentSettings(content_type="application/pdf")

MANUAL_CACHE = 200
PAGE_CACHE = 50
OFFER_CACHE = 500
DOC_TTL = 300.0
LIST_TTL = 60.0
COST_TTL = 30.0
WORKERS = 16
# above this many bikes in one call it is a bulk catalogue write, not an ingest worker linking one bike
BULK_BIKES = 8
CAS_RETRIES = 10

_MISS = object()


class _Cache:
    """LRU with a TTL. Values are whole parsed documents, so size is bounded by count, not bytes."""

    def __init__(self, maxsize: int, ttl: float):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return _MISS
            born, value = hit
            if time.monotonic() - born > self.ttl:
                self._data.pop(key, None)
                return _MISS
            self._data.move_to_end(key)
            return value

    def put(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def drop(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def _is_connection_string(value: str) -> bool:
    return "=" in value and not value.lower().startswith(("http://", "https://"))


class BlobStore:
    def __init__(
        self,
        account_url_or_conn: str,
        data_container: str = "data",
        pdf_container: str = "pdf",
        credential=None,
        pdf_base: str | None = None,
        create: bool = True,
    ):
        if _is_connection_string(account_url_or_conn):
            self.service = BlobServiceClient.from_connection_string(account_url_or_conn)
        else:
            if credential is None:
                from azure.identity import DefaultAzureCredential

                credential = DefaultAzureCredential()
            self.service = BlobServiceClient(account_url=account_url_or_conn, credential=credential)

        self.data = data_container
        self.pdf = pdf_container
        self.pdf_base = (pdf_base or f"{self.service.url.rstrip('/')}/{pdf_container}").rstrip("/")
        self.workers = WORKERS

        self._manuals = _Cache(MANUAL_CACHE, DOC_TTL)
        self._pages = _Cache(PAGE_CACHE, DOC_TTL)
        self._specs = _Cache(MANUAL_CACHE, DOC_TTL)
        self._lists = _Cache(8, LIST_TTL)
        self._costs = _Cache(1, COST_TTL)
        self._offers = _Cache(OFFER_CACHE, DOC_TTL)
        self._create_lock = threading.Lock()

        if create:
            self._ensure_containers()

    # --- plumbing -------------------------------------------------------

    def _ensure_containers(self) -> None:
        for name, public in ((self.data, None), (self.pdf, "blob")):
            try:
                self.service.create_container(name, public_access=public)
            except ResourceExistsError:
                pass
            except Exception as exc:  # a reader-only credential is fine as long as the containers exist
                log.warning("container %s: %s", name, exc)

    def _blob(self, name: str, container: str | None = None):
        return self.service.get_blob_client(container or self.data, name)

    def _read_json(self, name: str, default):
        try:
            raw = self._blob(name).download_blob().readall()
        except ResourceNotFoundError:
            return default
        return json.loads(raw) if raw else default

    def _write_json(self, name: str, data, metadata: dict[str, str] | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._blob(name).upload_blob(body, overwrite=True, content_settings=JSON, metadata=metadata)

    def _cas(self, name: str, merge, retries: int = CAS_RETRIES):
        """Read-modify-write a shared blob under If-Match / If-None-Match. `merge(current) -> new`."""
        for attempt in range(retries):
            etag = None
            current = None
            try:
                stream = self._blob(name).download_blob()
                raw = stream.readall()
                current = json.loads(raw) if raw else None
                etag = stream.properties.etag
            except ResourceNotFoundError:
                pass
            body = json.dumps(merge(current), ensure_ascii=False).encode("utf-8")
            try:
                if etag is None:
                    self._blob(name).upload_blob(body, overwrite=False, content_settings=JSON)
                else:
                    self._blob(name).upload_blob(
                        body,
                        overwrite=True,
                        content_settings=JSON,
                        etag=etag,
                        match_condition=MatchConditions.IfNotModified,
                    )
                return
            except (ResourceModifiedError, ResourceExistsError):
                time.sleep(min(0.05 * 2**attempt, 1.5) * (0.5 + random.random()))
        raise RuntimeError(f"{name}: lost {retries} ETag races")

    def _names(self, prefix: str, container: str | None = None) -> list[str]:
        client = self.service.get_container_client(container or self.data)
        return [b.name for b in client.list_blobs(name_starts_with=prefix)]

    def _fanout(self, fn, items: list):
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=min(self.workers, len(items))) as pool:
            return list(pool.map(fn, items))

    # --- bikes ----------------------------------------------------------

    def bikes(self) -> list[Bike]:
        hit = self._lists.get("bikes")
        if hit is not _MISS:
            return hit
        base = self._read_json("bikes.json", [])
        merged: dict[str, dict] = {b["id"]: b for b in base if isinstance(b, dict) and b.get("id")}
        for link in self._links():
            merged[link["id"]] = {**merged.get(link["id"], {}), **link}
        out = [Bike.model_validate(b) for b in merged.values()]
        self._lists.put("bikes", out)
        return out

    def _links(self) -> list[dict]:
        names = self._names("links/")
        docs = self._fanout(lambda n: self._read_json(n, None), names)
        return [d for d in docs if isinstance(d, dict) and d.get("id")]

    def bike(self, bike_id: str) -> Bike | None:
        return next((b for b in self.bikes() if b.id == bike_id), None)

    def put_bikes(self, bikes: list[Bike]) -> None:
        if not bikes:
            return
        if len(bikes) > BULK_BIKES:
            incoming = {b.id: b.model_dump(exclude_none=True) for b in bikes}

            def merge(current):
                base = {b["id"]: b for b in (current or []) if isinstance(b, dict) and b.get("id")}
                base.update(incoming)
                return list(base.values())

            self._cas("bikes.json", merge)
        else:
            # one tiny blob per bike: parallel ingest workers never contend, bikes() merges on read
            self._fanout(
                lambda b: self._write_json(f"links/{b.id}.json", b.model_dump(exclude_none=True)),
                list(bikes),
            )
        self._lists.drop("bikes")

    def compact_bikes(self) -> int:
        """Fold links/* into bikes.json and drop them. Maintenance only - run it when idle."""
        links = self._links()
        if not links:
            return 0
        incoming = {d["id"]: d for d in links}

        def merge(current):
            base = {b["id"]: b for b in (current or []) if isinstance(b, dict) and b.get("id")}
            for bike_id, doc in incoming.items():
                base[bike_id] = {**base.get(bike_id, {}), **doc}
            return list(base.values())

        self._cas("bikes.json", merge)
        self._fanout(lambda i: self._delete(f"links/{i}.json"), list(incoming))
        self._lists.drop("bikes")
        return len(incoming)

    def _delete(self, name: str, container: str | None = None) -> None:
        try:
            self._blob(name, container).delete_blob()
        except ResourceNotFoundError:
            pass

    # --- manuals --------------------------------------------------------

    @staticmethod
    def _meta(manual: Manual) -> dict[str, str]:
        return {
            "title": urllib.parse.quote(manual.title, safe=""),
            "pagecount": str(manual.pages),
            "sections": str(len(manual.sections)),
            "bikeids": ",".join(manual.bikeIds),
        }

    def manuals(self) -> list[Manual]:
        hit = self._lists.get("manuals")
        if hit is not _MISS:
            return hit
        ids = [Path(n).stem for n in self._names("manuals/") if n.endswith(".json")]
        out = [m for m in self._fanout(self.manual, sorted(ids)) if m is not None]
        self._lists.put("manuals", out)
        return out

    def manual_summaries(self) -> list[dict]:
        """/manuals without downloading every Manual: blob metadata carries the four fields it shows."""
        hit = self._lists.get("summaries")
        if hit is not _MISS:
            return hit
        client = self.service.get_container_client(self.data)
        rows: list[dict] = []
        cold: list[str] = []
        for blob in client.list_blobs(name_starts_with="manuals/", include=["metadata"]):
            if not blob.name.endswith(".json"):
                continue
            manual_id = Path(blob.name).stem
            meta = blob.metadata or {}
            if "title" in meta and "pagecount" in meta and "sections" in meta:
                rows.append(
                    {
                        "id": manual_id,
                        "title": urllib.parse.unquote(meta["title"]),
                        "bikeIds": [b for b in meta.get("bikeids", "").split(",") if b],
                        "pages": int(meta["pagecount"] or 0),
                        "sections": int(meta["sections"] or 0),
                    }
                )
            else:
                cold.append(manual_id)
        for manual in self._fanout(self.manual, cold):
            if manual is not None:
                rows.append(
                    {
                        "id": manual.id,
                        "title": manual.title,
                        "bikeIds": manual.bikeIds,
                        "pages": manual.pages,
                        "sections": len(manual.sections),
                    }
                )
        rows.sort(key=lambda r: r["id"])
        self._lists.put("summaries", rows)
        return rows

    def manual(self, manual_id: str) -> Manual | None:
        hit = self._manuals.get(manual_id)
        if hit is not _MISS:
            return hit
        data = self._read_json(f"manuals/{manual_id}.json", None)
        out = Manual.model_validate(data) if data else None
        self._manuals.put(manual_id, out)
        return out

    def put_manual(self, manual: Manual) -> None:
        self._write_json(
            f"manuals/{manual.id}.json", manual.model_dump(exclude_none=True), metadata=self._meta(manual)
        )
        self._manuals.put(manual.id, manual)
        self._lists.drop("manuals")
        self._lists.drop("summaries")

    # --- pages / specs --------------------------------------------------

    def pages(self, manual_id: str) -> list[Page]:
        hit = self._pages.get(manual_id)
        if hit is not _MISS:
            return hit
        out = [Page.model_validate(p) for p in self._read_json(f"pages/{manual_id}.json", [])]
        self._pages.put(manual_id, out)
        return out

    def put_pages(self, manual_id: str, pages: list[Page]) -> None:
        self._write_json(f"pages/{manual_id}.json", [p.model_dump() for p in pages])
        self._pages.put(manual_id, list(pages))

    def specs(self, manual_id: str) -> list[Spec]:
        hit = self._specs.get(manual_id)
        if hit is not _MISS:
            return hit
        out = [Spec.model_validate(s) for s in self._read_json(f"specs/{manual_id}.json", [])]
        self._specs.put(manual_id, out)
        return out

    def put_specs(self, manual_id: str, specs: list[Spec]) -> None:
        self._write_json(f"specs/{manual_id}.json", [s.model_dump(exclude_none=True) for s in specs])
        self._specs.put(manual_id, list(specs))

    # --- registry -------------------------------------------------------

    def registry(
        self, make: str | None = None, model: str | None = None, year: int | None = None
    ) -> list[RegistryEntry]:
        hit = self._lists.get("registry")
        if hit is _MISS:
            hit = [RegistryEntry.model_validate(e) for e in self._read_json("registry.json", [])]
            self._lists.put("registry", hit)
        entries = hit
        if make:
            entries = [e for e in entries if e.make.lower() == make.lower()]
        if model:
            entries = [e for e in entries if e.model.lower() == model.lower()]
        if year:
            entries = [e for e in entries if year in e.years]
        return entries

    def put_registry(self, entries: list[RegistryEntry]) -> None:
        if not entries:
            return
        incoming = {e.id: e.model_dump(exclude_none=True) for e in entries}

        def merge(current):
            base = {e["id"]: e for e in (current or []) if isinstance(e, dict) and e.get("id")}
            base.update(incoming)
            return list(base.values())

        self._cas("registry.json", merge)
        self._lists.drop("registry")

    # --- jobs -----------------------------------------------------------

    def job(self, job_id: str) -> IngestJob | None:
        data = self._read_json(f"jobs/{job_id}.json", None)
        return IngestJob.model_validate(data) if data else None

    def put_job(self, job: IngestJob) -> None:
        self._write_json(f"jobs/{job.id}.json", job.model_dump(exclude_none=True))

    # --- offers ---------------------------------------------------------

    def offers(self, manual_id: str, part_id: str) -> dict | None:
        """One blob per part, so a click on a part never contends with a click on another one."""
        key = f"{manual_id}/{part_id}"
        hit = self._offers.get(key)
        if hit is not _MISS:
            return hit
        out = self._read_json(f"offers/{key}.json", None)
        self._offers.put(key, out)
        return out

    def put_offers(self, manual_id: str, part_id: str, result: dict) -> None:
        key = f"{manual_id}/{part_id}"
        self._write_json(f"offers/{key}.json", result)
        self._offers.put(key, result)

    # --- costs ----------------------------------------------------------

    def log_cost(self, event: CostEvent) -> None:
        """Appends are atomic server side, so workers never serialise here. The one race is creating
        today's blob: an unconditional create_append_blob truncates whatever a racing worker already
        wrote, so the create is conditional on the blob still being missing."""
        name = f"costs/{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        client = self._blob(name)
        line = (json.dumps(event.model_dump()) + "\n").encode("utf-8")
        for _ in range(3):
            try:
                client.append_block(line)
                break
            except ResourceNotFoundError:
                with self._create_lock:
                    try:
                        client.create_append_blob(
                            content_settings=NDJSON, match_condition=MatchConditions.IfMissing
                        )
                    except (ResourceExistsError, ResourceModifiedError):
                        pass
        else:
            raise RuntimeError(f"{name}: could not append")
        self._costs.drop("costs")

    def costs(self) -> list[CostEvent]:
        hit = self._costs.get("costs")
        if hit is not _MISS:
            return hit
        names = sorted(n for n in self._names("costs/") if n.endswith(".jsonl"))
        out: list[CostEvent] = []
        for raw in self._fanout(lambda n: self._read_text(n), names):
            for line in raw.splitlines():
                if line.strip():
                    out.append(CostEvent.model_validate(json.loads(line)))
        self._costs.put("costs", out)
        return out

    def _read_text(self, name: str) -> str:
        try:
            return self._blob(name).download_blob().readall().decode("utf-8", "replace")
        except ResourceNotFoundError:
            return ""

    # --- pdf ------------------------------------------------------------

    def pdf_url(self, manual_id: str) -> str | None:
        hit = self._lists.get("pdfs")
        if hit is _MISS:
            hit = {Path(n).stem for n in self._names("", self.pdf) if n.endswith(".pdf")}
            self._lists.put("pdfs", hit)
        return f"{self.pdf_base}/{manual_id}.pdf" if manual_id in hit else None

    def put_pdf(self, manual_id: str, path: str | Path) -> str:
        with open(path, "rb") as fh:
            self._blob(f"{manual_id}.pdf", self.pdf).upload_blob(
                fh, overwrite=True, content_settings=PDF, max_concurrency=4
            )
        self._lists.drop("pdfs")
        return f"{self.pdf_base}/{manual_id}.pdf"

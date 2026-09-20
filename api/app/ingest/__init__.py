"""PDF in, Manual out. Sections with grounded highlights, specs and parts - never a word the manual does not print."""

import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf

from ..config import settings
from ..models import IngestJob, Manual
from ..search import get_index
from ..store import get_store
from . import assemble, pages as pagelib, structure
from .fetch import fetch

log = logging.getLogger("ingest")

MIN_PAGES = 8  # a rider's manual is never this short; anything shorter is a test file or a leaflet
MIN_READABLE_PAGES = 8  # a scan without a text layer: nothing to quote, so never pay an LLM for it

# One ingest is 32 parallel LLM calls and a whole PDF in memory. Three at once already saturates a
# 1 CPU / 2 GiB replica, and anything past that only makes every one of them slower - so a fourth
# waits its turn instead, which is exactly what its job status already says ("queued").
MAX_CONCURRENT = max(1, int(os.getenv("INGEST_MAX_CONCURRENT") or 3))
QUEUE_WAIT = 600.0
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)

# --- where an operator-supplied URL is allowed to point ------------------------------------------
# POST /ingest takes a URL from a human. Even behind the admin token it may only reach a host the
# registry already publishes manuals from: the fetcher will follow redirects and stream 180 s from
# whatever it is given, and that is not a capability to hand out on a hostname alone.
HOSTS_MAX_AGE = 300.0
_hosts: frozenset[str] = frozenset()
_hosts_at = 0.0
_hosts_lock = threading.Lock()


def _host_of(url: str) -> str:
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    return (parts.hostname or "").lower()


def known_pdf_hosts() -> frozenset[str]:
    """Every host the registry serves a manual from, plus app.registry's verified PDF_HOSTS."""
    global _hosts, _hosts_at
    with _hosts_lock:
        if _hosts and time.monotonic() - _hosts_at < HOSTS_MAX_AGE:
            return _hosts
        found: set[str] = set()
        try:
            from ..registry import PDF_HOSTS

            found.update(h.split("/", 1)[0].lower() for h in PDF_HOSTS)
        except Exception as exc:  # the registry agents own that package; a broken one is not fatal
            log.warning("PDF_HOSTS unavailable: %s", exc)
        try:
            for entry in get_store().registry():
                host = _host_of(entry.url)
                if host:
                    found.add(host)
        except Exception as exc:
            log.warning("registry hosts unavailable: %s", exc)
        _hosts, _hosts_at = frozenset(found), time.monotonic()
        return _hosts


def known_pdf_host(url: str) -> bool:
    host = _host_of(url)
    if not host:
        return False
    hosts = known_pdf_hosts()
    return host in hosts or any(host.endswith("." + known) for known in hosts)


def pdf_path(manual_id: str) -> Path:
    return settings.data_dir / "pdf" / f"{manual_id}.pdf"


def _job(job_id: str, manual_id: str) -> IngestJob:
    store = get_store()
    job = store.job(job_id) or IngestJob(id=job_id, manualId=manual_id, status="queued")
    return job


class Progress:
    """`done` out of `pages`, for a rider watching a bar. It only ever moves forward.

    The page count is unknown while the PDF is still downloading, so that stage is worth a fixed DOWNLOAD
    units - never more than the smallest manual we accept, so `done` can never overtake `pages`.
    """

    WRITE_EVERY = 1.0
    PROVISIONAL = 80.0
    DOWNLOAD_END = 0.10
    EXTRACT_END = 0.45
    STRUCT_END = 0.90

    def __init__(self, store, job: IngestJob):
        self.store = store
        self.job = job
        self.total = self.PROVISIONAL
        self.value = 0.0
        self.written = 0.0
        self.lock = threading.Lock()

    def _write(self, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self.written < self.WRITE_EVERY:
            return
        self.written = now
        self.job.done = int(self.value)
        self.job.pages = int(self.total)
        # Every write of the job is also its heartbeat: a job that has not been written for
        # ondemand.STALE_AFTER seconds belongs to a replica that is gone (docs/qa/BUGS.md BUG-13).
        self.job.updatedAt = time.time()
        self.store.put_job(self.job)

    def stage(self, name: str) -> None:
        self.job.stage = name
        self._write(True)

    def total_pages(self, pages: int) -> None:
        with self.lock:
            self.total = float(max(pages, 1))
        self._write(True)

    def at(self, value: float, force: bool = False) -> None:
        with self.lock:
            if value > self.value:
                self.value = min(value, self.total)
        self._write(force)

    def _span(self, start: float, end: float, fraction: float) -> float:
        return self.total * (start + (end - start) * min(max(fraction, 0.0), 1.0))

    def downloading(self, got: int, expected: int) -> None:
        self.at(self._span(0.0, self.DOWNLOAD_END, got / expected if expected > 0 else 0.5))

    def extracting(self, done_pages: int) -> None:
        self.at(self._span(self.DOWNLOAD_END, self.EXTRACT_END, done_pages / self.total))

    def structuring(self, done_batches: int, batches: int) -> None:
        self.at(self._span(self.EXTRACT_END, self.STRUCT_END, done_batches / max(1, batches)))

    def saving(self, fraction: float) -> None:
        self.at(self._span(self.STRUCT_END, 1.0, fraction), force=True)


def run(
    job_id: str,
    source: str,
    manual_id: str,
    bike_ids: list[str],
    make: str,
    model: str,
    year: int,
    *,
    struct_model: str | None = None,
    batch: int | None = None,
    workers: int | None = None,
    early: bool = False,
    needs_ua: str | None = None,
) -> Manual:
    """source = local path or http(s) URL of the official PDF.

    struct_model / batch are throughput knobs for the bulk tools: which LLM runs the structure pass and how
    many pages go into one call. Both default to app.config settings, so every other caller is unaffected.
    """
    store = get_store()
    job = _job(job_id, manual_id)
    # Acquired before the job says "running", so a queued ingest looks queued to whoever is watching.
    if not _slots.acquire(timeout=QUEUE_WAIT):
        job.status = "error"
        job.error = f"{MAX_CONCURRENT} ingests already running; waited {QUEUE_WAIT:.0f}s"
        job.updatedAt = time.time()
        store.put_job(job)
        raise RuntimeError(job.error)
    job.status = "running"
    job.error = None
    job.updatedAt = time.time()
    store.put_job(job)

    bar = Progress(store, job)
    doc = None
    try:
        bar.stage("download")
        path = fetch(source, pdf_path(manual_id), needs_ua, on_bytes=bar.downloading)
        bar.at(bar.total * bar.DOWNLOAD_END)
        doc = pymupdf.open(path)
        if doc.page_count < MIN_PAGES:
            raise ValueError(f"not a manual: {doc.page_count} page{'' if doc.page_count == 1 else 's'}")
        bar.total_pages(doc.page_count)
        bar.stage("pages")

        page_models = pagelib.extract_pages(doc, manual_id, progress=bar.extracting)
        readable = sum(1 for p in page_models if len(p.text.strip()) >= structure.MIN_CHARS)
        if readable < MIN_READABLE_PAGES:
            raise ValueError(f"no text layer: {readable} readable of {doc.page_count} pages")
        store.put_pages(manual_id, page_models)

        toc = pagelib.toc(doc)
        outline = pagelib.outline(toc)
        chaps = pagelib.chapters(toc, doc.page_count) or pagelib.text_chapters(doc)
        title = pagelib.cover_title(doc, make, model, year)
        bike = " ".join(str(p) for p in (make, model, year) if p).strip()

        # early=True: somebody is waiting. Publish the PDF and its outline now, overwrite with sections later.
        if early:
            existing = store.manual(manual_id)
            if existing is None or not existing.sections:
                store.put_manual(
                    Manual(
                        id=manual_id,
                        bikeIds=list(bike_ids),
                        file=f"/manuals/{manual_id}.pdf",
                        pages=doc.page_count,
                        title=title,
                        source=source,
                        outline=outline,
                        sections=[],
                        parts=[],
                    )
                )

        skip = pagelib.skip_pages(toc, chaps, doc.page_count)
        windows = structure.batches(page_models, skip, batch)
        prompts = [
            structure.prompt(
                window,
                title,
                bike,
                pagelib.chapter_of(chaps, window[0].page),
                pagelib.headings_for(toc, window[0].page, window[-1].page),
            )
            for window in windows
        ]
        bar.stage("structure")
        results = structure.run_batches(
            prompts,
            on_done=lambda n: bar.structuring(n, len(prompts)),
            model=struct_model,
            workers=workers,
        )
        units = [unit for group in results for unit in group]
        log.info("%s: %d batches -> %d units", manual_id, len(prompts), len(units))

        bar.stage("save")
        built = assemble.build(
            doc,
            units,
            chaps,
            lambda titles: structure.keywords(
                titles,
                model=struct_model,
                on_done=lambda n, total: bar.saving(0.45 + 0.45 * n / max(1, total)),
            ),
            progress=lambda n, total: bar.saving(0.45 * n / max(1, total)),
        )
        bar.saving(0.92)
        if not built.sections:
            # every structure call came back empty (rate limits, a scanned PDF): store nothing, let the caller retry
            (settings.data_dir / "manuals" / f"{manual_id}.json").unlink(missing_ok=True)
            raise ValueError(f"no sections from {len(prompts)} batches")
        manual = Manual(
            id=manual_id,
            bikeIds=list(bike_ids),
            file=f"/manuals/{manual_id}.pdf",
            pages=doc.page_count,
            title=title,
            source=source,
            outline=outline,
            sections=built.sections,
            parts=built.parts,
        )
        Manual.model_validate(manual.model_dump(exclude_none=True))
        store.put_manual(manual)
        store.put_specs(manual_id, built.specs)
        try:
            get_index().index(manual, page_models, built.specs)
        except NotImplementedError:
            log.warning("%s: search index not implemented yet", manual_id)
        except Exception as exc:  # the search agent owns that file; never fail ingest on it
            log.warning("%s: index failed: %s", manual_id, exc)

        job.status = "done"
        job.pages = doc.page_count
        job.done = doc.page_count
        job.error = None
        job.stage = "done"
        job.updatedAt = time.time()
        store.put_job(job)
        return manual
    except Exception as exc:
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"[:500]
        job.updatedAt = time.time()
        store.put_job(job)
        raise
    finally:
        _slots.release()
        # Every failure above used to leave the pymupdf Document open, and with it the mapped
        # PDF and the file handle. A replica that fails a few hundred ingests leaks both.
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass

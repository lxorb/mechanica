"""PDF in, Manual out. Sections with grounded highlights, specs and parts - never a word the manual does not print."""

import logging
from pathlib import Path

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


def pdf_path(manual_id: str) -> Path:
    return settings.data_dir / "pdf" / f"{manual_id}.pdf"


def _job(job_id: str, manual_id: str) -> IngestJob:
    store = get_store()
    job = store.job(job_id) or IngestJob(id=job_id, manualId=manual_id, status="queued")
    return job


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
    job.status = "running"
    job.error = None
    store.put_job(job)

    def progress(done: int, total: int | None = None) -> None:
        job.done = done
        if total is not None:
            job.pages = total
        store.put_job(job)

    try:
        path = fetch(source, pdf_path(manual_id), needs_ua)
        doc = pymupdf.open(path)
        if doc.page_count < MIN_PAGES:
            pages = doc.page_count
            doc.close()
            raise ValueError(f"not a manual: {pages} page{'' if pages == 1 else 's'}")
        progress(0, doc.page_count)

        page_models = pagelib.extract_pages(doc, manual_id, progress=lambda n: progress(n))
        readable = sum(1 for p in page_models if len(p.text.strip()) >= structure.MIN_CHARS)
        if readable < MIN_READABLE_PAGES:
            pages = doc.page_count
            doc.close()
            raise ValueError(f"no text layer: {readable} readable of {pages} pages")
        store.put_pages(manual_id, page_models)

        toc = pagelib.toc(doc)
        outline = pagelib.outline(toc)
        chaps = pagelib.chapters(toc, doc.page_count)
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
        progress(0, len(prompts) or doc.page_count)
        results = structure.run_batches(prompts, on_done=lambda n: progress(n), model=struct_model, workers=workers)
        units = [unit for group in results for unit in group]
        log.info("%s: %d batches -> %d units", manual_id, len(prompts), len(units))

        built = assemble.build(doc, units, chaps, lambda titles: structure.keywords(titles, model=struct_model))
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
        store.put_job(job)
        doc.close()
        return manual
    except Exception as exc:
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"[:500]
        store.put_job(job)
        raise

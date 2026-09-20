"""Regressions for the ingest / on-demand / parts-catalog bugs found in the 2026-09-20 bug hunt.

See docs/qa/BUGS.md for the repro of each one.
"""

import threading
import time

import pymupdf
import pytest

from app import ondemand, parts_catalog
from app import ingest as ingest_mod
from app.models import RegistryEntry


# ------------------------------------------------------------------ ingest: the document handle


def _fake_pdf(path, pages: int = 10):
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page(width=400, height=600)
        page.insert_text((40, 80), f"Checking the engine oil level, page {n + 1}", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def test_a_failed_ingest_closes_the_pdf(tmp_path, monkeypatch):
    """Every failure after pymupdf.open() used to leak the Document, and with it the mapped file.
    A replica that fails a few hundred on-demand ingests leaks both."""
    src = _fake_pdf(tmp_path / "manual.pdf")
    opened: list[pymupdf.Document] = []
    real_open = pymupdf.open

    def spy(*args, **kwargs):
        doc = real_open(*args, **kwargs)
        opened.append(doc)
        return doc

    monkeypatch.setattr(ingest_mod.pymupdf, "open", spy)

    def boom(*args, **kwargs):
        raise RuntimeError("extraction exploded")

    monkeypatch.setattr(ingest_mod.pagelib, "extract_pages", boom)

    with pytest.raises(RuntimeError):
        ingest_mod.run("job-leak", str(src), "leak-om", ["leak-bike"], "KTM", "390 Duke", 2024)

    assert opened, "pymupdf.open was never reached"
    assert all(doc.is_closed for doc in opened)


def test_a_short_pdf_still_closes_the_document(tmp_path, monkeypatch):
    src = _fake_pdf(tmp_path / "leaflet.pdf", pages=2)
    opened: list[pymupdf.Document] = []
    real_open = pymupdf.open
    monkeypatch.setattr(
        ingest_mod.pymupdf, "open", lambda *a, **k: (opened.append(real_open(*a, **k)) or opened[-1])
    )
    with pytest.raises(ValueError, match="not a manual"):
        ingest_mod.run("job-short", str(src), "short-om", ["short-bike"], "KTM", "390 Duke", 2024)
    assert opened and all(doc.is_closed for doc in opened)


def test_the_failing_job_is_still_marked_error(tmp_path, monkeypatch, store):
    src = _fake_pdf(tmp_path / "manual.pdf")
    monkeypatch.setattr(ingest_mod.pagelib, "extract_pages", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    with pytest.raises(RuntimeError):
        ingest_mod.run("job-err", str(src), "err-om", ["err-bike"], "KTM", "390 Duke", 2024)
    job = store.job("job-err")
    assert job is not None and job.status == "error" and "RuntimeError" in (job.error or "")


# --------------------------------------------------- on demand: the registry index must not freeze


@pytest.fixture
def cold_index():
    before = (ondemand._registry, ondemand._registry_at, ondemand._registry_built)
    ondemand._registry, ondemand._registry_at, ondemand._registry_built = {}, 0.0, 0.0
    yield
    ondemand._registry, ondemand._registry_at, ondemand._registry_built = before


class _CountingStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def registry(self, *args, **kwargs):
        self.calls += 1
        return list(self.rows)


ROW = RegistryEntry(
    id="ktm-390-duke-2024",
    make="KTM",
    model="390 Duke",
    years=[2024],
    market="EU",
    type="owner",
    lang="en",
    url="https://example.invalid/390-duke.pdf",
    access="free",
    site="ktm.com",
)


def test_the_ondemand_registry_index_refreshes(cold_index, monkeypatch):
    """On a blob deployment there is no registry.json on disk, so the mtime stamp is 0.0 for ever
    and the index was frozen for the life of the process: a row the registry agent added could
    never be found on demand until a redeploy."""
    fake = _CountingStore([ROW])
    monkeypatch.setattr(ondemand, "get_store", lambda: fake)

    assert ondemand._index()[("ktm", "390 duke")]
    assert fake.calls == 1
    ondemand._index()
    assert fake.calls == 1, "a warm index must not re-read the registry"

    fake.rows = [ROW, ROW.model_copy(update={"id": "new", "make": "BMW", "model": "R 1300 GS"})]
    ondemand._registry_built = time.monotonic() - ondemand.REGISTRY_MAX_AGE - 1
    index = ondemand._index()
    assert fake.calls == 2
    assert ("bmw", "r 1300 gs") in index


# --------------------------------------------------------- parts taxonomy: no torn publish


class _SlowDict(dict):
    def update(self, *args, **kwargs):  # type: ignore[override]
        time.sleep(0.25)
        return super().update(*args, **kwargs)


def test_taxonomy_is_never_visible_with_a_half_built_id_map(monkeypatch):
    """/parts/catalog and the warm prefetch land on different threads. Publishing `_taxonomy`
    before `_by_id` was refilled let the second thread read an empty map, which silently dropped
    every standard part from that one answer."""
    real = parts_catalog.taxonomy()
    some_id = real.parts[0].id

    monkeypatch.setattr(parts_catalog, "_taxonomy", None)
    monkeypatch.setattr(parts_catalog, "_by_id", _SlowDict())

    started = threading.Event()

    def load():
        started.set()
        parts_catalog.taxonomy()

    worker = threading.Thread(target=load)
    worker.start()
    started.wait(1.0)
    time.sleep(0.05)  # right inside the window the old code left open
    assert parts_catalog.entry(some_id) is not None
    worker.join(5.0)
    assert parts_catalog.entry(some_id) is not None
    assert parts_catalog.fingerprint()


def test_parts_catalog_route_still_answers(client, store):
    manual_id = next(iter(m.id for m in store.manuals()), None)
    assert manual_id, "the seeded data must carry at least one manual"
    body = client.get("/parts/catalog", params={"manualId": manual_id}).json()
    assert body["parts"] and body["groups"]

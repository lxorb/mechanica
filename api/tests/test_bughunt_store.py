"""Regressions for the store bugs found in the 2026-09-20 bug hunt (docs/qa/BUGS.md).

No Azure needed: the two things under test are the cache's own TTL bookkeeping and the fact that
BlobStore only holds a provisional document briefly, both of which sit above the blob calls.
"""

import time

import pytest

from app.models import Manual
from app.store import DEFAULT_PAGES, FileStore, max_manual_pages
from app.store_blob import _MISS, MISS_TTL, BlobStore, _Cache


def _manual(manual_id: str, sections: list | None = None, pages: int = 143) -> Manual:
    return Manual(
        id=manual_id,
        bikeIds=["bike-1"],
        file=f"/manuals/{manual_id}.pdf",
        pages=pages,
        title="Owner's Manual",
        source="https://example.invalid/m.pdf",
        outline=[],
        sections=sections or [],
        parts=[],
    )


SECTION = {
    "id": "oil",
    "title": "Oil change",
    "chapter": "Maintenance",
    "pageStart": 12,
    "pageEnd": 13,
    "keywords": ["oil"],
    "highlights": [{"page": 12, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}],
}


class _FakeBlobStore(BlobStore):
    """BlobStore with the blob layer replaced by a dict, so the caching rules are testable alone."""

    def __init__(self):
        # deliberately not BlobStore.__init__: that one needs credentials and a live account
        self.docs: dict[str, object] = {}
        self.reads: list[str] = []
        self.data = "data"
        self.pdf = "pdf"
        self.pdf_base = "https://example.invalid/pdf"
        self.workers = 2
        self._manuals = _Cache(8, 300.0)
        self._pages = _Cache(8, 300.0)
        self._specs = _Cache(8, 300.0)
        self._lists = _Cache(8, 60.0)
        self._costs = _Cache(1, 30.0)
        self._offers = _Cache(8, 300.0)

    def _read_json(self, name, default):
        self.reads.append(name)
        return self.docs.get(name, default)

    def _write_json(self, name, data, metadata=None):
        self.docs[name] = data


# --------------------------------------------------------------------- _Cache


def test_cache_entry_may_carry_its_own_shorter_ttl():
    cache = _Cache(4, 60.0)
    cache.put("long", 1)
    cache.put("short", 2, 0.05)
    assert cache.get("short") == 2
    time.sleep(0.08)
    assert cache.get("short") is _MISS
    assert cache.get("long") == 1


# ------------------------------------------------------- provisional documents


def test_missing_manual_is_not_remembered_for_the_full_ttl():
    """A 404 used to stick for DOC_TTL, so a manual another replica had just written stayed
    missing for five minutes on this one."""
    store = _FakeBlobStore()
    assert store.manual("duke-om") is None
    # the miss is remembered, but with the short TTL, not DOC_TTL
    assert store._manuals.get("duke-om") is None
    assert store._manuals._data["duke-om"][2] == MISS_TTL

    # age it out the way MISS_TTL seconds would, then let the real document land
    store._manuals.put("duke-om", None, 0.01)
    time.sleep(0.03)
    assert store._manuals.get("duke-om") is _MISS
    store.docs["manuals/duke-om.json"] = _manual("duke-om", [SECTION]).model_dump(exclude_none=True)
    found = store.manual("duke-om")
    assert found is not None and found.sections


def test_early_sectionless_manual_is_held_only_briefly():
    """`early=True` publishes a manual with no sections so the PDF is readable at once. Caching
    that for DOC_TTL made the finished one invisible for five minutes on every other replica."""
    store = _FakeBlobStore()
    store.docs["manuals/duke-om.json"] = _manual("duke-om").model_dump(exclude_none=True)
    assert store.manual("duke-om").sections == []
    entry = store._manuals._data["duke-om"]
    assert entry[2] == MISS_TTL

    store.docs["manuals/duke-om.json"] = _manual("duke-om", [SECTION]).model_dump(exclude_none=True)
    store._manuals.put("duke-om", store._manuals.get("duke-om"), 0.01)
    time.sleep(0.03)
    assert store.manual("duke-om").sections


def test_a_real_manual_keeps_the_full_ttl():
    store = _FakeBlobStore()
    store.docs["manuals/duke-om.json"] = _manual("duke-om", [SECTION]).model_dump(exclude_none=True)
    store.manual("duke-om")
    assert store._manuals._data["duke-om"][2] > MISS_TTL


@pytest.mark.parametrize(
    "getter,blob,full",
    [
        ("pages", "pages/duke-om.json", [{"manualId": "duke-om", "page": 1, "width": 1.0, "height": 2.0, "text": "x", "blocks": []}]),
        ("specs", "specs/duke-om.json", [{"sectionId": "oil", "name": "Oil", "kind": "capacity", "value": "1.7 l", "page": 12, "quote": "1.7 l"}]),
    ],
)
def test_empty_pages_and_specs_are_held_only_briefly(getter, blob, full):
    store = _FakeBlobStore()
    assert getattr(store, getter)("duke-om") == []
    cache = store._pages if getter == "pages" else store._specs
    assert cache._data["duke-om"][2] == MISS_TTL
    store.docs[blob] = full
    cache.put("duke-om", [], 0.01)
    time.sleep(0.03)
    assert getattr(store, getter)("duke-om")


def test_an_unlooked_up_offer_is_held_only_briefly():
    """Caching `None` for DOC_TTL made a part another replica had just paid a web search for
    look cold enough to pay for again."""
    store = _FakeBlobStore()
    assert store.offers("duke-om", "oil-filter") is None
    assert store._offers._data["duke-om/oil-filter"][2] == MISS_TTL
    store.docs["offers/duke-om/oil-filter.json"] = {"offers": [{"shop": "x"}]}
    store._offers.put("duke-om/oil-filter", None, 0.01)
    time.sleep(0.03)
    assert store.offers("duke-om", "oil-filter") == {"offers": [{"shop": "x"}]}


# ------------------------------------------------------------ max_manual_pages


def test_max_manual_pages_uses_the_listing_not_every_document():
    """/cost only needs the largest page count. Reading it out of manuals() pulled all 535
    documents - 72 MB, 7.5 s measured live - on every cold call."""
    store = _FakeBlobStore()
    calls = {"n": 0}

    def summaries():
        calls["n"] += 1
        return [{"id": "a", "pages": 128}, {"id": "b", "pages": 775}, {"id": "c", "pages": 0}]

    store.manual_summaries = summaries

    def never():
        raise AssertionError("max_manual_pages must not download every Manual")

    store.manuals = never
    assert max_manual_pages(store) == 775
    assert calls["n"] == 1


def test_max_manual_pages_falls_back_to_manuals_and_then_to_a_default(fresh_store: FileStore):
    assert max_manual_pages(fresh_store) == DEFAULT_PAGES
    fresh_store.put_manual(_manual("duke-om", [SECTION], pages=250))
    fresh_store.put_manual(_manual("gs-om", [SECTION], pages=99))
    assert max_manual_pages(fresh_store) == 250


def test_cost_route_reports_the_largest_manual(client):
    body = client.get("/cost").json()
    from app.llm import naive_usd
    from app.store import get_store

    assert body["naivePerAsk"] == pytest.approx(naive_usd(max_manual_pages(get_store())))

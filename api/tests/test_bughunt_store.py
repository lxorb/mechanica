"""Regressions for the store bugs found in the 2026-09-20 bug hunt (docs/qa/BUGS.md).

No Azure needed: the two things under test are the cache's own TTL bookkeeping and the fact that
BlobStore only holds a provisional document briefly, both of which sit above the blob calls.
"""

import json
import threading
import time

import pytest
from azure.core.exceptions import HttpResponseError

from app.models import CostEvent, Manual
from app.store import DEFAULT_PAGES, FileStore, max_manual_pages
from app.store_blob import _MISS, COMPACT_AT, MISS_TTL, BlobStore, _Cache


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
        self.text: dict[str, str] = {}
        self.etags: dict[str, str] = {}
        self.reads: list[str] = []
        self.parsed: list[str] = []
        self.data = "data"
        self.pdf = "pdf"
        self.pdf_base = "https://example.invalid/pdf"
        self.workers = 2
        self._manuals = _Cache(8, 300.0)
        self._pages = _Cache(8, 300.0)
        self._specs = _Cache(8, 300.0)
        self._lists = _Cache(8, 60.0)
        self._costs = _Cache(1, 30.0)
        self._cost_docs = _Cache(64, 3600.0)
        self._cost_roll: dict[str, int] = {}
        self._offers = _Cache(8, 300.0)
        self._create_lock = threading.Lock()
        self._compact_lock = threading.Lock()
        self._compacting = False
        self.service = _FakeService(self)

    def _read_json(self, name, default):
        self.reads.append(name)
        return self.docs.get(name, default)

    def _write_json(self, name, data, metadata=None):
        self.docs[name] = data

    def _names(self, prefix, container=None):
        return [n for n in {**self.docs, **self.text} if n.startswith(prefix)]

    def _read_text(self, name):
        self.parsed.append(name)
        return self.text.get(name, "")


class _Blob:
    def __init__(self, name, etag):
        self.name = name
        self.etag = etag
        self.metadata: dict[str, str] = {}


class _FakeContainer:
    def __init__(self, store):
        self.store = store

    def list_blobs(self, name_starts_with="", include=None):
        for name in sorted({**self.store.docs, **self.store.text}):
            if name.startswith(name_starts_with):
                yield _Blob(name, self.store.etags.get(name, "etag-0"))


class _FakeService:
    def __init__(self, store):
        self.store = store

    def get_container_client(self, name):
        return _FakeContainer(self.store)


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


# --------------------------------------------------------- BUG-12  costs are parsed once per day


def _line(usd: float, route: str = "ask.router") -> str:
    return json.dumps(
        {"ts": 1.0, "route": route, "model": "gpt-5.6-luna", "inputTokens": 1,
         "cachedTokens": 0, "outputTokens": 1, "usd": usd}
    )


def test_a_days_cost_blob_is_parsed_once_while_its_etag_holds():
    """The live counter refreshes every 30 s; re-reading and re-parsing every event ever logged
    each time is O(everything). Yesterday's blob never changes, so its ETag says so."""
    store = _FakeBlobStore()
    store.text["costs/20260919.jsonl"] = _line(0.1) + "\n" + _line(0.2) + "\n"
    store.text["costs/20260920.jsonl"] = _line(0.3) + "\n"
    store.etags.update({"costs/20260919.jsonl": "a", "costs/20260920.jsonl": "b"})

    assert len(store.costs()) == 3
    assert sorted(store.parsed) == ["costs/20260919.jsonl", "costs/20260920.jsonl"]

    store._costs.drop("costs")  # the 30 s live-counter refresh
    store.parsed.clear()
    assert len(store.costs()) == 3
    assert store.parsed == [], "an unchanged day must not be downloaded again"

    # today's file grew: new ETag, so only that one is read again
    store.text["costs/20260920.jsonl"] += _line(0.4) + "\n"
    store.etags["costs/20260920.jsonl"] = "b2"
    store._costs.drop("costs")
    assert round(sum(e.usd for e in store.costs()), 4) == 1.0
    assert store.parsed == ["costs/20260920.jsonl"]


def test_log_cost_rolls_to_a_new_blob_when_the_append_blob_is_full():
    """One append blob holds 50,000 blocks and one logged call is one block."""
    from datetime import datetime, timezone

    store = _FakeBlobStore()
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    full = {f"costs/{day}.jsonl"}
    written: list[tuple[str, bytes]] = []

    class _FakeBlobClient:
        def __init__(self, name):
            self.name = name

        def append_block(self, line):
            if self.name in full:
                exc = HttpResponseError(message="block count exceeds limit")
                exc.error_code = "BlockCountExceedsLimit"
                raise exc
            written.append((self.name, line))

        def create_append_blob(self, **kwargs):
            pass

    store._blob = lambda name, container=None: _FakeBlobClient(name)
    event = CostEvent(ts=1.0, route="ask.router", model="gpt-5.6-luna",
                      inputTokens=1, cachedTokens=0, outputTokens=1, usd=0.1)

    store.log_cost(event)
    assert written == [(f"costs/{day}-1.jsonl", written[0][1])]
    assert store._cost_roll[day] == 1

    # the next event goes straight to the rolled blob, no second failed attempt
    written.clear()
    store.log_cost(event)
    assert [name for name, _ in written] == [f"costs/{day}-1.jsonl"]


def test_a_non_block_limit_append_error_still_raises():
    store = _FakeBlobStore()

    class _Boom:
        def append_block(self, line):
            exc = HttpResponseError(message="forbidden")
            exc.error_code = "AuthorizationFailure"
            raise exc

        def create_append_blob(self, **kwargs):
            pass

    store._blob = lambda name, container=None: _Boom()
    with pytest.raises(HttpResponseError):
        store.log_cost(CostEvent(ts=1.0, route="r", model="m", inputTokens=1,
                                 cachedTokens=0, outputTokens=1, usd=0.1))


def test_the_rolled_blob_name_is_shaped_so_costs_finds_it():
    store = _FakeBlobStore()
    first = store._cost_name()
    assert first.startswith("costs/") and first.endswith(".jsonl")
    store._cost_roll[first[len("costs/"):-len(".jsonl")]] = 2
    second = store._cost_name()
    assert second.endswith("-2.jsonl") and second.startswith("costs/")


# ------------------------------------------------- BUG-11  link blobs are folded away on their own


def test_bikes_folds_the_link_blobs_away_once_there_are_too_many():
    store = _FakeBlobStore()
    store.docs["bikes.json"] = []
    for n in range(COMPACT_AT + 1):
        store.docs[f"links/bike-{n}.json"] = {
            "id": f"bike-{n}", "make": "KTM", "model": "390 Duke", "year": 2024, "market": "EU"
        }
    fired = threading.Event()
    store.compact_bikes = lambda: fired.set() or 0

    assert len(store.bikes()) == COMPACT_AT + 1
    assert fired.wait(5.0), "compaction never ran"


def test_bikes_leaves_a_handful_of_links_alone():
    store = _FakeBlobStore()
    store.docs["bikes.json"] = []
    for n in range(3):
        store.docs[f"links/bike-{n}.json"] = {
            "id": f"bike-{n}", "make": "KTM", "model": "390 Duke", "year": 2024, "market": "EU"
        }
    fired = threading.Event()
    store.compact_bikes = lambda: fired.set() or 0
    assert len(store.bikes()) == 3
    assert not fired.wait(0.3)


def test_cost_route_reports_the_largest_manual(client):
    body = client.get("/cost").json()
    from app.llm import naive_usd
    from app.store import get_store

    assert body["naivePerAsk"] == pytest.approx(naive_usd(max_manual_pages(get_store())))

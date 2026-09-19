"""FileStore behavior, isolated from seeded data and external services."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from unittest.mock import Mock

import pytest

from app import store as store_mod
from app.models import Bike, CostEvent, IngestJob, Manual, Page, RegistryEntry, Spec
from app.store import FileStore


@pytest.fixture
def bike():
    return Bike(
        id="duke", make="KTM", model="390 Duke", year=2024, market="EU",
        manualId="duke-manual", vins=["TESTVIN"], cues=["orange frame"],
    )


@pytest.fixture
def manual():
    return Manual(
        id="duke-manual",
        bikeIds=["duke"],
        file="/manuals/duke.pdf",
        pages=100,
        title="Owner's manual \u2014 maintenance",
        source="https://example.invalid/duke.pdf",
        outline=[{
            "title": "Maintenance", "page": 10,
            "children": [{"title": "Oil change", "page": 12}],
        }],
        sections=[{
            "id": "oil", "title": "Oil change", "chapter": "Maintenance",
            "pageStart": 12, "pageEnd": 13, "keywords": ["oil", "filter"],
            "highlights": [{"page": 12, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}],
            "partIds": ["filter"], "related": ["service"],
        }],
        parts=[{
            "id": "filter", "name": "Oil filter", "spec": "OEM", "page": 12,
            "oem": "12345",
            "links": [{"shop": "Parts", "url": "https://example.invalid/filter"}],
        }],
    )


@pytest.fixture
def registry_entries():
    return [
        RegistryEntry(
            id=entry_id, make=make, model=model, years=years, market="EU",
            type="owner", lang="en", url=f"https://example.invalid/{entry_id}.pdf",
            access="free", site="Manufacturer",
        )
        for entry_id, make, model, years in [
            ("duke", "KTM", "390 Duke", [2023, 2024]),
            ("duke-old", "KTM", "390 Duke", [2020]),
            ("rc", "KTM", "RC 390", [2024]),
            ("gs", "BMW", "R 12 GS", [2024, 2025]),
        ]
    ]


def test_empty_store_returns_empty_collections_and_missing_records(fresh_store):
    assert fresh_store.bikes() == []
    assert fresh_store.bike("missing") is None
    assert fresh_store.manuals() == []
    assert fresh_store.manual("missing") is None
    assert fresh_store.pages("missing") == []
    assert fresh_store.specs("missing") == []
    assert fresh_store.registry() == []
    assert fresh_store.job("missing") is None
    assert fresh_store.costs() == []
    assert list(fresh_store.root.iterdir()) == []


def test_writes_create_missing_parent_directories(tmp_path, bike):
    root = tmp_path / "nested" / "data"
    store = FileStore(root)
    assert store.bikes() == []
    assert not root.exists()

    store.put_bikes([bike])

    assert FileStore(root).bike(bike.id) == bike
    assert not list(root.rglob("*.tmp"))


def test_bikes_round_trip_and_upsert_by_id(fresh_store, bike):
    other = bike.model_copy(update={"id": "rc", "model": "RC 390"})
    fresh_store.put_bikes([bike, other])
    reopened = FileStore(fresh_store.root)
    assert {b.id: b for b in reopened.bikes()} == {bike.id: bike, other.id: other}
    assert reopened.bike(bike.id) == bike
    assert reopened.bike("missing") is None

    updated = bike.model_copy(update={"year": 2025, "manualId": None})
    fresh_store.put_bikes([updated])
    fresh_store.put_bikes([])

    assert {b.id: b for b in reopened.bikes()} == {bike.id: updated, other.id: other}
    assert reopened.bike(bike.id) == updated


def test_duplicate_bike_ids_in_one_batch_keep_last_value(fresh_store, bike):
    updated = bike.model_copy(update={"model": "390 Duke R"})
    fresh_store.put_bikes([bike, updated])
    assert fresh_store.bikes() == [updated]


def test_mutating_returned_bike_does_not_change_persisted_data(fresh_store, bike):
    fresh_store.put_bikes([bike])
    loaded = fresh_store.bike(bike.id)
    loaded.model = "Changed"
    loaded.cues.append("new cue")
    assert fresh_store.bike(bike.id) == bike


def test_manuals_round_trip_nested_models_and_list_in_id_order(fresh_store, manual):
    other = manual.model_copy(update={"id": "another-manual"})
    fresh_store.put_manual(manual)
    fresh_store.put_manual(other)

    reopened = FileStore(fresh_store.root)
    assert reopened.manual(manual.id) == manual
    assert reopened.manuals() == [other, manual]
    assert reopened.manual("missing") is None


def test_put_manual_replaces_existing_manual_only(fresh_store, manual):
    other = manual.model_copy(update={"id": "another-manual"})
    fresh_store.put_manual(manual)
    fresh_store.put_manual(other)
    updated = manual.model_copy(update={"title": "Revised manual", "parts": []})

    fresh_store.put_manual(updated)

    assert FileStore(fresh_store.root).manuals() == [other, updated]


def test_pages_round_trip_replace_and_clear_per_manual(fresh_store):
    page = Page(
        manualId="duke", page=2, width=595.0, height=842.0,
        text="\u00d6l: 1.7 l\nCheck level.",
        blocks=[{"text": "\u00d6l", "x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}],
    )
    first_page = page.model_copy(update={"page": 1, "text": "Introduction"})
    other = page.model_copy(update={"manualId": "gs"})
    fresh_store.put_pages("duke", [page, first_page])
    fresh_store.put_pages("gs", [other])
    reopened = FileStore(fresh_store.root)
    assert reopened.pages("duke") == [page, first_page]

    replacement = page.model_copy(update={"text": "Revised", "blocks": []})
    fresh_store.put_pages("duke", [replacement])
    assert reopened.pages("duke") == [replacement]

    fresh_store.put_pages("duke", [])
    assert reopened.pages("duke") == []
    assert reopened.pages("gs") == [other]


def test_specs_round_trip_replace_and_clear_per_manual(fresh_store):
    torque = Spec(
        sectionId="oil", name="Drain plug", kind="torque", value="20",
        unit="Nm", page=12, quote="Tighten to 20 Nm.",
    )
    grade = Spec(
        sectionId="oil", name="Engine oil", kind="grade", value="10W-40",
        page=13, quote="Use 10W-40 oil.",
    )
    fresh_store.put_specs("duke", [torque, grade])
    fresh_store.put_specs("gs", [grade])
    reopened = FileStore(fresh_store.root)
    assert reopened.specs("duke") == [torque, grade]

    updated = torque.model_copy(update={"value": "25", "quote": "Tighten to 25 Nm."})
    fresh_store.put_specs("duke", [updated])
    assert reopened.specs("duke") == [updated]

    fresh_store.put_specs("duke", [])
    assert reopened.specs("duke") == []
    assert reopened.specs("gs") == [grade]


@pytest.mark.parametrize(
    ("filters", "expected_ids"),
    [
        ({}, {"duke", "duke-old", "rc", "gs"}),
        ({"make": "kTm"}, {"duke", "duke-old", "rc"}),
        ({"model": "390 DUKE"}, {"duke", "duke-old"}),
        ({"year": 2023}, {"duke"}),
        ({"year": 2024}, {"duke", "rc", "gs"}),
        ({"year": 2025}, {"gs"}),
        ({"make": "KTM", "model": "390 duke", "year": 2024}, {"duke"}),
        ({"make": "BMW", "model": "390 Duke"}, set()),
        ({"make": "KTM", "year": 2025}, set()),
        ({"make": "KT"}, set()),
        ({"model": "Duke"}, set()),
        ({"year": 1999}, set()),
    ],
)
def test_registry_filters(fresh_store, registry_entries, filters, expected_ids):
    fresh_store.put_registry(registry_entries)
    entries = FileStore(fresh_store.root).registry(**filters)
    assert {entry.id for entry in entries} == expected_ids
    assert all(isinstance(entry, RegistryEntry) for entry in entries)


def test_registry_upserts_by_id_and_preserves_other_entries(fresh_store, registry_entries):
    original, *others = registry_entries
    fresh_store.put_registry(registry_entries)
    updated = original.model_copy(update={"access": "paid", "price": "EUR 10"})
    fresh_store.put_registry([original, updated])
    fresh_store.put_registry([])

    expected = {entry.id: entry for entry in [updated, *others]}
    assert {entry.id: entry for entry in FileStore(fresh_store.root).registry()} == expected


def test_jobs_round_trip_update_and_preserve_other_jobs(fresh_store):
    job = IngestJob(id="job-1", manualId="duke", status="queued")
    other = IngestJob(id="job-2", manualId="gs", status="queued")
    fresh_store.put_job(job)
    fresh_store.put_job(other)
    reopened = FileStore(fresh_store.root)
    assert reopened.job(job.id) == job
    assert reopened.job("missing") is None

    failed = job.model_copy(update={"status": "error", "error": "Download failed"})
    fresh_store.put_job(failed)
    assert reopened.job(job.id) == failed

    done = job.model_copy(update={"status": "done", "pages": 10, "done": 10})
    fresh_store.put_job(done)
    assert reopened.job(job.id) == done
    assert reopened.job(other.id) == other


def test_costs_append_in_order_preserve_duplicates_and_ignore_blank_lines(fresh_store):
    first = CostEvent(
        ts=1.0, route="/ask", model="test-model", inputTokens=100,
        cachedTokens=20, outputTokens=10, usd=0.001,
    )
    second = first.model_copy(update={"ts": 2.0, "route": "/ingest", "usd": 0.002})
    fresh_store.log_cost(first)
    with (fresh_store.root / "costs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("\n   \n")
    fresh_store.log_cost(second)
    fresh_store.log_cost(first)

    assert FileStore(fresh_store.root).costs() == [first, second, first]


def test_bike_json_preserves_unicode_and_omits_none(fresh_store, bike):
    bike = bike.model_copy(update={"model": "M\u00fcller", "manualId": None, "vins": None})
    fresh_store.put_bikes([bike])

    raw = (fresh_store.root / "bikes.json").read_text(encoding="utf-8")
    record, = json.loads(raw)
    assert "M\u00fcller" in raw
    assert "manualId" not in record
    assert "vins" not in record
    assert fresh_store.bike(bike.id) == bike


def test_concurrent_bike_upserts_do_not_lose_records(fresh_store, bike):
    bikes = [bike.model_copy(update={"id": f"bike-{i}"}) for i in range(20)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda item: fresh_store.put_bikes([item]), bikes))

    assert {b.id: b for b in fresh_store.bikes()} == {b.id: b for b in bikes}


def test_corrupt_json_is_reported_instead_of_silently_discarded(fresh_store):
    (fresh_store.root / "bikes.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        fresh_store.bikes()


def test_get_store_uses_configured_file_root_and_caches_instance(monkeypatch, tmp_path):
    monkeypatch.setattr(store_mod, "_store", None)
    monkeypatch.setattr(store_mod.settings, "mongodb_uri", None)
    monkeypatch.setattr(store_mod.settings, "data_dir", tmp_path)

    store = store_mod.get_store()

    assert isinstance(store, FileStore)
    assert store.root == tmp_path
    assert store_mod.get_store() is store


def test_get_store_selects_and_caches_mongo_without_connecting(monkeypatch):
    uri = "mongodb://unused.invalid/test"
    mongo_module = ModuleType("app.store_mongo")
    mongo_constructor = Mock(name="MongoStore")
    mongo_module.MongoStore = mongo_constructor
    monkeypatch.setitem(sys.modules, "app.store_mongo", mongo_module)
    monkeypatch.setattr(store_mod, "_store", None)
    monkeypatch.setattr(store_mod.settings, "mongodb_uri", uri)

    store = store_mod.get_store()

    assert store is mongo_constructor.return_value
    assert store_mod.get_store() is store
    mongo_constructor.assert_called_once_with(uri)


def test_upsert_relinks_a_bike_to_its_manual_without_duplicating_the_row(fresh_store, bike):
    """What main._start_job does once an ingest finishes: re-put the same bike carrying manualId."""
    unlinked = bike.model_copy(update={"manualId": None})
    fresh_store.put_bikes([unlinked])
    assert fresh_store.bike(bike.id).manualId is None

    fresh_store.put_bikes([unlinked.model_copy(update={"manualId": "duke-manual"})])

    rows = FileStore(fresh_store.root).bikes()
    assert len(rows) == 1
    assert rows[0].id == bike.id
    assert rows[0].manualId == "duke-manual"
    assert rows[0].vins == bike.vins

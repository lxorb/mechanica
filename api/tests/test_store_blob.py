"""BlobStore.

The cache, the factory and the URL shaping are tested without a server. The Store protocol itself is
tested against a real Blob endpoint when one is reachable:

  Azurite   npm i -g azurite && azurite-blob --silent -l %TEMP%\\azurite
            (picked up automatically on 127.0.0.1:10000, or point AZURITE_URL at it)
  Azure     TTM_BLOB_TEST_CONN=<connection string>   - containers are created and dropped per run

Neither available -> those tests skip; the FileStore suite is the one that must always be green.
"""

import json
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models import Bike, CostEvent, IngestJob, Manual, Page, RegistryEntry, Spec
from app.store_blob import _MISS, BlobStore, _Cache, _is_connection_string

# Azurite's published well-known emulator credentials - identical on every machine, not a secret.
AZURITE_CONN = (
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)


def _azurite_up(host: str = "127.0.0.1", port: int = 10000) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def _backend() -> str | None:
    import os

    if os.environ.get("TTM_BLOB_TEST_CONN"):
        return os.environ["TTM_BLOB_TEST_CONN"]
    if _azurite_up():
        return AZURITE_CONN
    return None


requires_blob = pytest.mark.skipif(_backend() is None, reason="no Azurite on :10000 and no TTM_BLOB_TEST_CONN")


@pytest.fixture
def manual() -> Manual:
    return Manual(
        id="duke-manual",
        bikeIds=["duke", "duke-r"],
        file="/manuals/duke.pdf",
        pages=143,
        title="KTM 390 DUKE — Bedienungsanleitung",
        source="https://example.invalid/duke.pdf",
        outline=[{"title": "Maintenance", "page": 10, "children": [{"title": "Oil change", "page": 12}]}],
        sections=[
            {
                "id": "oil", "title": "Oil change", "chapter": "Maintenance",
                "pageStart": 12, "pageEnd": 13, "keywords": ["oil", "filter"],
                "highlights": [{"page": 12, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}],
            }
        ],
        parts=[
            {
                "id": "filter", "name": "Oil filter", "spec": "OEM", "page": 12,
                "links": [{"shop": "Parts", "url": "https://example.invalid/filter"}],
            }
        ],
    )


# --- no server needed ------------------------------------------------------


def test_connection_string_vs_account_url():
    assert _is_connection_string("DefaultEndpointsProtocol=https;AccountName=x;AccountKey=y==")
    assert not _is_connection_string("https://ttm.blob.core.windows.net")
    assert not _is_connection_string("http://127.0.0.1:10000/devstoreaccount1")


def test_cache_returns_miss_sentinel_for_unknown_key():
    cache = _Cache(2, 60)
    assert cache.get("nope") is _MISS


def test_cache_stores_none_distinctly_from_a_miss():
    cache = _Cache(2, 60)
    cache.put("known-absent", None)
    assert cache.get("known-absent") is None
    assert cache.get("other") is _MISS


def test_cache_evicts_least_recently_used():
    cache = _Cache(2, 60)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is _MISS
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_cache_expires_by_ttl():
    cache = _Cache(4, 0.05)
    cache.put("a", 1)
    assert cache.get("a") == 1
    time.sleep(0.08)
    assert cache.get("a") is _MISS


def test_cache_drop_and_clear():
    cache = _Cache(4, 60)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.drop("a")
    assert cache.get("a") is _MISS
    cache.clear()
    assert cache.get("b") is _MISS


def test_summary_metadata_survives_a_unicode_title(manual):
    meta = BlobStore._meta(manual)
    assert meta["pagecount"] == str(manual.pages)
    assert meta["sections"] == str(len(manual.sections))
    assert meta["bikeids"] == ",".join(manual.bikeIds)
    assert meta["title"].isascii()
    import urllib.parse

    assert urllib.parse.unquote(meta["title"]) == manual.title


def test_filestore_has_no_public_pdf_url(fresh_store):
    assert fresh_store.pdf_url("anything") is None


def test_factory_prefers_blob_over_mongo(monkeypatch):
    from app import store as store_mod

    built = {}

    class FakeBlobStore:
        def __init__(self, target, **kwargs):
            built["target"] = target
            built["kwargs"] = kwargs

    monkeypatch.setattr(store_mod.settings, "azure_storage_connection_string", None, raising=False)
    monkeypatch.setattr(store_mod.settings, "azure_storage_account", "ttmtest", raising=False)
    monkeypatch.setattr(store_mod.settings, "mongodb_uri", "mongodb://unused", raising=False)
    monkeypatch.setattr("app.store_blob.BlobStore", FakeBlobStore)
    store_mod._store = None

    store = store_mod.get_store()
    assert isinstance(store, FakeBlobStore)
    assert built["target"] == "https://ttmtest.blob.core.windows.net"
    assert built["kwargs"]["pdf_container"] == "pdf"
    assert built["kwargs"]["data_container"] == "data"


def test_factory_falls_back_to_filestore(monkeypatch):
    from app import store as store_mod

    monkeypatch.setattr(store_mod.settings, "azure_storage_connection_string", None, raising=False)
    monkeypatch.setattr(store_mod.settings, "azure_storage_account", None, raising=False)
    monkeypatch.setattr(store_mod.settings, "mongodb_uri", None, raising=False)
    store_mod._store = None
    assert isinstance(store_mod.get_store(), store_mod.FileStore)


def test_manual_file_route_redirects_to_the_public_pdf(client, monkeypatch):
    from app import main as main_mod

    monkeypatch.setattr(main_mod, "pdf_url", lambda mid: f"https://cdn.invalid/pdf/{mid}.pdf")
    res = client.get("/manuals/ktm-390-duke-2024-om-en/file", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://cdn.invalid/pdf/ktm-390-duke-2024-om-en.pdf"


def test_manual_file_route_still_serves_the_local_pdf(client):
    res = client.get("/manuals/ktm-390-duke-2024-om-en/file")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"


def test_manual_document_points_at_the_public_pdf(client, monkeypatch):
    from app import main as main_mod

    monkeypatch.setattr(main_mod, "pdf_url", lambda mid: f"https://cdn.invalid/pdf/{mid}.pdf")
    body = client.get("/manuals/ktm-390-duke-2024-om-en").json()
    assert body["file"] == "https://cdn.invalid/pdf/ktm-390-duke-2024-om-en.pdf"


def test_serving_a_local_pdf_hands_it_to_blob_for_the_other_replicas(client, monkeypatch):
    from app import main as main_mod
    from app import store as store_mod

    pushed = []

    class Pushing:
        def put_pdf(self, manual_id, path):
            pushed.append((manual_id, str(path)))

        def pdf_url(self, manual_id):
            return None

    monkeypatch.setattr(main_mod, "get_store", lambda: Pushing())
    monkeypatch.setattr(store_mod, "get_store", lambda: Pushing())
    main_mod._pushed.clear()

    assert client.get("/manuals/ktm-390-duke-2024-om-en/file").status_code == 200
    assert [m for m, _ in pushed] == ["ktm-390-duke-2024-om-en"]

    client.get("/manuals/ktm-390-duke-2024-om-en/file")
    assert len(pushed) == 1


def test_a_filestore_only_deployment_pushes_nothing(client):
    from app import main as main_mod

    main_mod._pushed.clear()
    assert client.get("/manuals/ktm-390-duke-2024-om-en/file").status_code == 200
    assert main_mod._pushed == set()


def test_manuals_route_uses_the_store_summaries_when_it_has_them(client, monkeypatch):
    from app import store as store_mod

    rows = [{"id": "x", "title": "X", "bikeIds": ["b"], "pages": 3, "sections": 1}]

    class Summarising:
        def manual_summaries(self):
            return rows

    monkeypatch.setattr(store_mod, "get_store", lambda: Summarising())
    monkeypatch.setattr("app.main.get_store", lambda: Summarising())
    assert client.get("/manuals").json() == rows


# --- against a real blob endpoint -----------------------------------------


@pytest.fixture
def blob_store():
    conn = _backend()
    suffix = uuid.uuid4().hex[:10]
    store = BlobStore(conn, data_container=f"tdata{suffix}", pdf_container=f"tpdf{suffix}")
    yield store
    for name in (store.data, store.pdf):
        try:
            store.service.delete_container(name)
        except Exception:
            pass


@requires_blob
def test_manual_round_trip_and_listing(blob_store, manual):
    assert blob_store.manual(manual.id) is None
    blob_store.put_manual(manual)
    blob_store._manuals.clear()
    back = blob_store.manual(manual.id)
    assert back == manual
    assert [m.id for m in blob_store.manuals()] == [manual.id]


@requires_blob
def test_summaries_read_metadata_without_downloading_documents(blob_store, manual):
    blob_store.put_manual(manual)
    blob_store._lists.clear()
    blob_store._manuals.clear()
    calls = []
    original = blob_store._read_json
    blob_store._read_json = lambda name, default: (calls.append(name), original(name, default))[1]

    rows = blob_store.manual_summaries()

    assert rows == [
        {
            "id": manual.id,
            "title": manual.title,
            "bikeIds": manual.bikeIds,
            "pages": manual.pages,
            "sections": len(manual.sections),
        }
    ]
    assert not [c for c in calls if c.startswith("manuals/")]


@requires_blob
def test_pages_and_specs_round_trip(blob_store):
    pages = [
        Page(manualId="m", page=1, width=595, height=842, text="oil change", blocks=[]),
        Page(manualId="m", page=2, width=595, height=842, text="torque 25 Nm", blocks=[]),
    ]
    specs = [Spec(sectionId="s", name="Axle nut", kind="torque", value="25", unit="Nm", page=2, quote="25 Nm")]
    blob_store.put_pages("m", pages)
    blob_store.put_specs("m", specs)
    blob_store._pages.clear()
    blob_store._specs.clear()
    assert blob_store.pages("m") == pages
    assert blob_store.specs("m") == specs
    assert blob_store.pages("missing") == []


@requires_blob
def test_jobs_are_never_cached(blob_store):
    job = IngestJob(id="j1", manualId="m", status="running", pages=10, done=3)
    blob_store.put_job(job)
    assert blob_store.job("j1") == job
    blob_store.put_job(job.model_copy(update={"status": "done", "done": 10}))
    assert blob_store.job("j1").status == "done"
    assert blob_store.job("nope") is None


@requires_blob
def test_registry_merges_by_id_and_filters(blob_store):
    entries = [
        RegistryEntry(
            id=eid, make=make, model=model, years=years, market="EU", type="owner", lang="en",
            url=f"https://example.invalid/{eid}.pdf", access="free", site="Manufacturer",
        )
        for eid, make, model, years in [("a", "KTM", "390 Duke", [2024]), ("b", "BMW", "R 12 G/S", [2025])]
    ]
    blob_store.put_registry(entries[:1])
    blob_store.put_registry(entries[1:])
    blob_store._lists.clear()
    assert {e.id for e in blob_store.registry()} == {"a", "b"}
    assert [e.id for e in blob_store.registry(make="ktm")] == ["a"]
    assert [e.id for e in blob_store.registry(year=2025)] == ["b"]


@requires_blob
def test_single_bike_writes_land_in_link_blobs_and_merge_over_the_catalogue(blob_store):
    catalogue = [
        Bike(id=f"b{i}", make="KTM", model=f"{i} Duke", year=2024, market="EU") for i in range(20)
    ]
    blob_store.put_bikes(catalogue)
    assert blob_store._names("links/") == []

    blob_store.put_bikes([catalogue[3].model_copy(update={"manualId": "m3"})])
    assert blob_store._names("links/") == ["links/b3.json"]

    blob_store._lists.clear()
    bikes = {b.id: b for b in blob_store.bikes()}
    assert len(bikes) == 20
    assert bikes["b3"].manualId == "m3"
    assert bikes["b4"].manualId is None


@requires_blob
def test_parallel_workers_never_lose_a_manual_link(blob_store):
    blob_store.put_bikes([Bike(id=f"b{i}", make="KTM", model=f"{i}", year=2024, market="EU") for i in range(30)])

    def link(i: int) -> None:
        bike = Bike(id=f"b{i}", make="KTM", model=f"{i}", year=2024, market="EU", manualId=f"m{i}")
        blob_store.put_bikes([bike])

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(link, range(30)))

    blob_store._lists.clear()
    bikes = {b.id: b for b in blob_store.bikes()}
    assert len(bikes) == 30
    assert all(bikes[f"b{i}"].manualId == f"m{i}" for i in range(30))


@requires_blob
def test_compact_bikes_folds_links_into_the_catalogue(blob_store):
    blob_store.put_bikes([Bike(id=f"b{i}", make="KTM", model=f"{i}", year=2024, market="EU") for i in range(12)])
    blob_store.put_bikes([Bike(id="b1", make="KTM", model="1", year=2024, market="EU", manualId="m1")])

    assert blob_store.compact_bikes() == 1
    assert blob_store._names("links/") == []

    blob_store._lists.clear()
    bikes = {b.id: b for b in blob_store.bikes()}
    assert len(bikes) == 12
    assert bikes["b1"].manualId == "m1"


@requires_blob
def test_concurrent_registry_writes_keep_every_entry(blob_store):
    def write(i: int) -> None:
        blob_store.put_registry(
            [
                RegistryEntry(
                    id=f"r{i}", make="KTM", model=str(i), years=[2024], market="EU", type="owner",
                    lang="en", url=f"https://example.invalid/{i}.pdf", access="free", site="Manufacturer",
                )
            ]
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(write, range(24)))

    blob_store._lists.clear()
    assert {e.id for e in blob_store.registry()} == {f"r{i}" for i in range(24)}


@requires_blob
def test_costs_append_concurrently(blob_store):
    def log(i: int) -> None:
        blob_store.log_cost(
            CostEvent(ts=1.0 + i, route="ask", model="m", inputTokens=i, cachedTokens=0, outputTokens=1, usd=0.001)
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(log, range(40)))

    blob_store._costs.clear()
    events = blob_store.costs()
    assert len(events) == 40
    assert sum(e.usd for e in events) == pytest.approx(0.04)


@requires_blob
def test_pdf_url_is_none_until_the_pdf_is_uploaded(blob_store, tmp_path):
    assert blob_store.pdf_url("duke-manual") is None
    pdf = tmp_path / "duke-manual.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    url = blob_store.put_pdf("duke-manual", pdf)
    assert url.endswith(f"/{blob_store.pdf}/duke-manual.pdf")
    assert blob_store.pdf_url("duke-manual") == url


@requires_blob
def test_manual_blob_is_plain_json_any_tool_can_read(blob_store, manual):
    blob_store.put_manual(manual)
    raw = blob_store._blob(f"manuals/{manual.id}.json").download_blob().readall()
    assert json.loads(raw)["id"] == manual.id

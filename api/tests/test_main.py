"""Routes, against a throwaway copy of api/data (see conftest). No OpenAI, no network."""

import pytest

from app import ask as ask_mod
from app.models import Manual
from conftest import BMW, KTM

KTM_BIKE = "ktm-390-duke-2024"
MOCK_VIN_PREFIX = "VBKJSA40"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_catalog(client):
    r = client.get("/catalog")
    assert r.status_code == 200
    bikes = r.json()
    assert len(bikes) >= 2
    by_id = {b["id"]: b for b in bikes}
    assert KTM_BIKE in by_id
    ktm = by_id[KTM_BIKE]
    assert ktm["make"] == "KTM" and ktm["year"] == 2024 and ktm["manualId"] == KTM
    assert set(ktm) >= {"id", "make", "model", "year", "market", "manualId"}


@pytest.mark.parametrize("q", ["390 duke", "KTM", "duke2024", "  390  DUKE  "])
def test_catalog_suggest_finds_the_ktm(client, q):
    r = client.get("/catalog/suggest", params={"q": q})
    assert r.status_code == 200
    assert any(b["id"] == KTM_BIKE for b in r.json())


def test_catalog_suggest_empty_and_miss(client):
    assert client.get("/catalog/suggest", params={"q": ""}).json() == []
    assert client.get("/catalog/suggest", params={"q": "harley sportster"}).json() == []


def test_manuals_list(client):
    r = client.get("/manuals")
    assert r.status_code == 200
    rows = {m["id"]: m for m in r.json()}
    assert {KTM, BMW} <= set(rows)
    row = rows[KTM]
    assert row["pages"] > 0 and row["sections"] > 0
    assert KTM_BIKE in row["bikeIds"]
    assert set(row) == {"id", "title", "bikeIds", "pages", "sections"}


def test_manual_detail_is_a_manual_with_a_served_file_url(client):
    r = client.get(f"/manuals/{KTM}")
    assert r.status_code == 200
    body = r.json()
    manual = Manual.model_validate(body)
    assert manual.id == KTM
    assert manual.file == f"http://testserver/manuals/{KTM}/file"
    assert manual.sections and manual.parts


def test_manual_404(client):
    assert client.get("/manuals/no-such-manual").status_code == 404


@pytest.mark.parametrize("manual_id", [KTM, BMW])
def test_manual_file_is_a_pdf(client, manual_id):
    r = client.get(f"/manuals/{manual_id}/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 1000


def test_manual_file_404(client):
    assert client.get("/manuals/no-such-manual/file").status_code == 404


def test_cost_shape(client):
    r = client.get("/cost")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"total", "count", "byRoute", "byModel", "naivePerAsk", "asks"}
    assert body["count"] > 0
    assert body["total"] == pytest.approx(sum(body["byRoute"].values()))
    assert body["total"] == pytest.approx(sum(body["byModel"].values()))
    assert body["asks"] > 0
    assert any(route.startswith("ask") for route in body["byRoute"])
    assert all(isinstance(v, float) for v in body["byRoute"].values())
    # the whole point of the product: routing beats stuffing the PDF into a frontier model
    assert body["naivePerAsk"] > body["total"] / body["asks"]


def test_identify_vin_mock_prefix(client):
    r = client.post("/identify/vin", json={"vin": f"{MOCK_VIN_PREFIX}XR1234567"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0] == {"bikeId": KTM_BIKE, "confidence": 1.0}
    assert body["bike"]["id"] == KTM_BIKE
    assert body["bike"]["manualId"] == KTM


def test_identify_vin_is_normalised(client):
    r = client.post("/identify/vin", json={"vin": "vbk jsa-40 xr1234567"})
    assert r.json()["candidates"][0]["bikeId"] == KTM_BIKE


def test_identify_vin_short_vin_is_422(client):
    assert client.post("/identify/vin", json={"vin": "ABC123"}).status_code == 422


def test_identify_vin_unknown_vin_does_not_reach_the_network(client):
    """vPIC is unreachable in tests; identify._decode swallows it and answers empty."""
    r = client.post("/identify/vin", json={"vin": "JH2SC59A5XM200001"})
    assert r.status_code == 200
    assert r.json() == {"candidates": [], "bike": None}


# ---------------------------------------------------------------- /ask


class _Recorder:
    """Stands in for app.llm.structured: hands back canned Route/Pick objects and counts calls."""

    def __init__(self, route: ask_mod.Route, pick: ask_mod.Pick | None = None):
        self.route = route
        self.pick = pick
        self.routes = 0
        self.picks = 0

    def __call__(self, route=None, model=None, schema=None, system=None, user=None, reasoning=None, **kw):
        if schema is ask_mod.Route:
            self.routes += 1
            return self.route
        if schema is ask_mod.Pick:
            self.picks += 1
            if self.pick is None:
                raise AssertionError("the picker must not be called for this query")
            return self.pick
        raise AssertionError(f"unexpected schema {schema}")


def _install(monkeypatch, recorder: _Recorder) -> _Recorder:
    monkeypatch.setattr("app.llm.structured", recorder)
    return recorder


CHAIN_ROUTE = ask_mod.Route(
    intent="procedure",
    components=["drive chain", "chain tension"],
    queries=["checking the chain tension", "adjusting the chain tension"],
    specName=None,
    specKind=None,
)


def test_ask_returns_the_manuals_own_sections_in_the_pickers_order(client, monkeypatch):
    """Two chain sections score within a hair of each other, so the picker gets to decide."""
    rec = _install(
        monkeypatch,
        _Recorder(
            CHAIN_ROUTE,
            ask_mod.Pick(sectionIds=["chain-tension-adjust", "chain-tension-check"], relatedIds=["chain-clean"]),
        ),
    )
    r = client.post("/ask", json={"manualId": KTM, "query": "chain rattles"})
    assert r.status_code == 200
    body = r.json()
    ids = [m["section"]["id"] for m in body["matches"]]
    assert ids == ["chain-tension-adjust", "chain-tension-check", "chain-clean"]
    assert body["intent"] == "procedure"
    assert body["usd"] == 0.0
    assert rec.routes == 1 and rec.picks == 1
    first = body["matches"][0]["section"]
    assert first["title"] == "Adjusting the chain tension"
    assert first["pageStart"] == 78 and first["pageEnd"] == 78
    assert first["highlights"], "a match must carry the printed lines to mark"
    assert body["matches"][0]["score"] > body["matches"][1]["score"]
    # the UI contract is Manual + Match[]: no prose may ride along
    assert all(set(m) == {"section", "score"} for m in body["matches"])
    assert "answer" not in body and "text" not in body


def test_ask_skips_the_picker_when_the_index_is_already_decisive(client, monkeypatch):
    rec = _install(
        monkeypatch,
        _Recorder(
            ask_mod.Route(
                intent="procedure",
                components=["engine oil", "oil filter"],
                queries=["changing the engine oil and oil filter", "engine oil change oil drain plug"],
                specName=None,
                specKind=None,
            ),
            pick=None,  # the recorder raises if the picker is reached
        ),
    )
    body = client.post("/ask", json={"manualId": KTM, "query": "change the oil"}).json()
    ids = [m["section"]["id"] for m in body["matches"]]
    assert ids[0] == "engine-oil-change"
    assert 1 <= len(ids) <= 4
    assert rec.routes == 1 and rec.picks == 0
    assert body["matches"][0]["section"]["pageStart"] == 114


def test_ask_drops_unknown_picker_ids(client, monkeypatch):
    rec = _install(
        monkeypatch,
        _Recorder(
            ask_mod.Route(
                intent="procedure",
                components=["drive chain"],
                queries=["checking the chain tension", "adjusting the chain tension"],
                specName=None,
                specKind=None,
            ),
            ask_mod.Pick(
                sectionIds=["hallucinated-section", "chain-tension-check", "also-not-real"],
                relatedIds=["chain-tension-adjust", "nope-not-a-section"],
            ),
        ),
    )
    body = client.post("/ask", json={"manualId": KTM, "query": "chain is loose"}).json()
    ids = [m["section"]["id"] for m in body["matches"]]
    assert ids == ["chain-tension-check", "chain-tension-adjust"]
    assert rec.picks == 1


def test_ask_spec_intent_never_pays_for_the_picker(client, monkeypatch):
    rec = _install(
        monkeypatch,
        _Recorder(
            ask_mod.Route(
                intent="spec",
                components=["rear wheel", "wheel spindle"],
                queries=["rear wheel spindle tightening torque", "chassis tightening torques rear wheel"],
                specName="rear wheel spindle nut torque",
                specKind="torque",
            ),
            pick=None,  # the recorder raises if the picker is reached
        ),
    )
    body = client.post("/ask", json={"manualId": KTM, "query": "torque for the rear axle"}).json()
    ids = [m["section"]["id"] for m in body["matches"]]
    assert ids, "spec intent produced no sections"
    assert "chassis-torques" in ids
    assert body["intent"] == "spec"
    assert rec.routes == 1
    assert rec.picks == 0


def test_ask_router_failure_still_answers_from_the_index(client, monkeypatch):
    def boom(**kw):
        raise RuntimeError("openai down")

    monkeypatch.setattr("app.llm.structured", boom)
    body = client.post("/ask", json={"manualId": KTM, "query": "checking tire pressure"}).json()
    assert body["matches"][0]["section"]["id"] == "tire-pressure"
    assert body["intent"] == "procedure"


def test_ask_out_of_scope_query_returns_no_pages_and_never_pays_for_the_picker(client, monkeypatch):
    """Router says the sentence names no vehicle system: no index lookup, no picker, no pages.
    The app must show nothing rather than guess a section."""
    rec = _install(
        monkeypatch,
        _Recorder(
            ask_mod.Route(intent="unknown", components=[], queries=["what is the capital of france"],
                          specName=None, specKind=None),
            pick=None,  # the recorder raises if the picker is reached
        ),
    )
    body = client.post("/ask", json={"manualId": KTM, "query": "what is the capital of france"}).json()
    assert body["matches"] == []
    assert body["intent"] == "unknown"
    assert body["usd"] == 0.0
    assert rec.routes == 1 and rec.picks == 0

    direct = ask_mod.answer(KTM, "tell me a joke about motorcycles")
    assert direct.matches == []
    assert direct.intent == "unknown"
    assert rec.picks == 0


def test_ask_unknown_manual_is_404(client):
    assert client.post("/ask", json={"manualId": "no-such-manual", "query": "oil"}).status_code == 404


def test_ask_blank_query_is_unknown(client, monkeypatch):
    monkeypatch.setattr("app.llm.structured", _Recorder(None))
    body = client.post("/ask", json={"manualId": KTM, "query": "   "}).json()
    assert body == {"matches": [], "intent": "unknown", "usd": 0.0}


def test_ask_is_cached_per_manual_and_query(client, monkeypatch):
    rec = _install(
        monkeypatch,
        _Recorder(
            ask_mod.Route(intent="procedure", components=["fuse"], queries=["replacing fuses"], specName=None, specKind=None),
            ask_mod.Pick(sectionIds=["fuses"], relatedIds=[]),
        ),
    )
    first = client.post("/ask", json={"manualId": KTM, "query": "fuse blown"}).json()
    second = client.post("/ask", json={"manualId": KTM, "query": "  FUSE   blown "}).json()
    assert first["matches"] == second["matches"]
    assert rec.routes == 1, "the normalised query should hit the cache"


def test_registry_route_answers(client):
    r = client.get("/registry")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ingest_status_404(client):
    assert client.get("/ingest/deadbeef").status_code == 404

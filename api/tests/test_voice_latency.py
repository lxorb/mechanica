"""What the voice path is allowed to spend while a mechanic stands there listening to silence.

The rules under test are latency rules, so they are written as "this work did not happen" rather than
as a stopwatch: a wall-clock assertion on a machine that also runs 600 other tests is a flake, and the
real numbers live in docs/pitches/deepgram/latency-after.md, measured against the live pipeline.

Three of them:
  - a sentence the rider already said in the manual's own words asks no model anything (`ask._fast`)
  - a spoken turn reads no cost log, compresses no prompt, and reasons at "none"
  - opening a voice session builds this manual's index and page map before the first question does
"""

import threading

import pytest

from conftest import BMW, KTM

# Deepgram calls the tool endpoints from its own servers and accepts https only, so /voice/agent-settings
# refuses an http PUBLIC_BASE outright. The test harness advertises one; say https here instead.
BASE = "https://ttm.example.test/api"


@pytest.fixture
def https_base(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "public_base", BASE)
    return BASE

# Sentences whose lead section the BM25 index already names outright, and which therefore must never
# reach the router. Chosen from the eval's own vocabulary, not invented for the test.
DECISIVE = ["check the coolant level", "battery is dead"]
# Sentences that must still reach the router: the top two sections are within a hair of each other,
# the sentence asks for a printed figure, or it is not about the motorcycle at all.
ROUTED = ["chain is loose", "chain rattles", "torque for the rear axle", "tell me a joke about motorcycles"]


@pytest.fixture
def no_llm(monkeypatch):
    """Any model call at all fails the test it happens in."""
    calls: list[str] = []

    def forbidden(**kwargs):
        calls.append(kwargs.get("route", "?"))
        raise AssertionError(f"the voice path called {kwargs.get('route')!r}")

    monkeypatch.setattr("app.llm.structured", forbidden)
    return calls


@pytest.fixture
def counted(monkeypatch):
    """Every llm.structured call recorded as (route, model, reasoning), answered with a stub."""
    from app import ask as ask_mod

    seen: list[tuple[str, str, str | None]] = []

    def record(**kwargs):
        seen.append((kwargs["route"], kwargs["model"], kwargs.get("reasoning")))
        if kwargs["schema"] is ask_mod.Route:
            return ask_mod.Route(
                intent="procedure",
                components=["drive chain", "chain tension"],
                queries=["checking the chain tension", "adjusting the chain tension"],
                specName=None,
                specKind=None,
            )
        return ask_mod.Pick(sectionIds=["chain-tension-check"], relatedIds=[])

    monkeypatch.setattr("app.llm.structured", record)
    return seen


# ---------------------------------------------------------------- the rider's own words


@pytest.mark.parametrize("query", DECISIVE)
def test_a_sentence_already_in_the_manuals_words_asks_no_model(client, no_llm, query):
    body = client.post("/voice/tools/find_procedure", json={"manualId": KTM, "query": query}).json()
    assert body["sections"], f"{query!r} produced no section"
    assert body["firstPage"] > 0
    assert no_llm == []


@pytest.mark.parametrize("query", ROUTED)
def test_an_ambiguous_or_off_topic_sentence_still_goes_to_the_router(client, counted, query):
    client.post("/voice/tools/find_procedure", json={"manualId": KTM, "query": query})
    assert [route for route, _, _ in counted][:1] == ["ask.router"], f"{query!r} skipped the router"


def test_the_fast_path_leads_with_the_section_the_rider_named(client, no_llm):
    body = client.post("/voice/tools/find_procedure", json={"manualId": KTM, "query": "check the coolant level"}).json()
    assert body["sections"][0]["id"] == "coolant-level"


def test_a_figure_always_goes_to_the_router_so_the_spec_path_gets_its_name(counted):
    """The router is what hands the deterministic spec path a printed spec name and kind. A lexical
    hit, however confident, may never stand in for it."""
    from app import ask as ask_mod

    for query in ("front axle nut torque", "how much oil does it take", "tyre pressure"):
        ask_mod.clear_cache()
        sections = {}
        assert ask_mod._fast(KTM, query, sections) is None


def test_the_fast_path_never_answers_an_off_topic_sentence():
    from app import ask as ask_mod
    from app.store import get_store

    sections = {s.id: s for s in get_store().manual(KTM).sections}
    for query in ("best exhaust", "how do i wheelie", "book me a hotel in milan", "hello", "asdfgh"):
        assert ask_mod._fast(KTM, query, sections) is None, query


def test_the_fast_path_costs_nothing_and_is_remembered(client, no_llm):
    body = client.post("/voice/tools/find_procedure", json={"manualId": BMW, "query": "battery is dead"}).json()
    again = client.post("/voice/tools/find_procedure", json={"manualId": BMW, "query": " BATTERY  is   dead "}).json()
    assert body["sections"] and body == again
    assert no_llm == []


# ---------------------------------------------------------------- what a spoken turn does not pay for


def test_a_spoken_turn_reads_no_cost_log(client, counted, monkeypatch):
    """`usd` is a number nobody hears. On the blob store reading it is a document fetch that every
    model call invalidates as it writes its own cost event."""
    from app.store import get_store

    store = get_store()
    reads: list[int] = []
    original = store.costs

    def counting():
        reads.append(1)
        return original()

    monkeypatch.setattr(store, "costs", counting)
    client.post("/voice/tools/find_procedure", json={"manualId": KTM, "query": "chain rattles"})
    assert reads == []


def test_a_typed_ask_still_prices_itself_and_reads_the_log_once(client, counted, monkeypatch):
    from app.store import get_store

    store = get_store()
    reads: list[int] = []
    original = store.costs

    def counting():
        reads.append(1)
        return original()

    monkeypatch.setattr(store, "costs", counting)
    body = client.post("/ask", json={"manualId": KTM, "query": "chain rattles"}).json()
    assert "usd" in body
    assert len(reads) == 1, "the baseline is the event timestamp, not a second whole read of the log"


def test_a_spoken_turn_does_not_wait_for_prompt_compression(client, counted, monkeypatch):
    """The Token Company is a cost lever (app/ttc.py). Out loud it buys its saving with silence."""
    from app import ttc

    called: list[str] = []
    monkeypatch.setattr(ttc, "compress", lambda text, **kw: called.append(text) or (text, 0, 0))
    client.post("/voice/tools/find_procedure", json={"manualId": KTM, "query": "chain rattles"})
    assert called == []


def test_a_typed_ask_still_compresses_the_pickers_candidates(client, counted, monkeypatch):
    from app import ttc

    called: list[str] = []
    monkeypatch.setattr(ttc, "compress", lambda text, **kw: called.append(text) or (text, 0, 0))
    client.post("/ask", json={"manualId": KTM, "query": "chain rattles"})
    assert len(called) == 1


def test_a_spoken_turn_reasons_at_none_and_a_typed_one_at_low(client, counted):
    from app import ask as ask_mod

    client.post("/voice/tools/find_procedure", json={"manualId": KTM, "query": "chain rattles"})
    spoken = [effort for _, _, effort in counted]
    assert spoken and set(spoken) == {ask_mod.VOICE_EFFORT}

    counted.clear()
    ask_mod.clear_cache()
    client.post("/ask", json={"manualId": KTM, "query": "chain rattles"})
    assert counted and {effort for _, _, effort in counted} == {ask_mod.EFFORT}


def test_the_spoken_flag_does_not_leak_out_of_the_block():
    from app import ask as ask_mod

    assert ask_mod._spoken.get() is False
    with ask_mod.spoken():
        assert ask_mod._spoken.get() is True
    assert ask_mod._spoken.get() is False


# ---------------------------------------------------------------- the session warm-up


def test_warm_builds_the_index_and_the_page_map(monkeypatch):
    from app import ask as ask_mod
    from app.search import get_index

    ask_mod._pages.pop(KTM, None)
    get_index().remove(KTM)
    ask_mod.warm(KTM)
    assert get_index().built(KTM) is not None
    assert ask_mod._pages.get(KTM), "the page map the picker's snippets come from was not built"


def test_warm_is_silent_about_a_manual_that_is_not_there():
    from app import ask as ask_mod

    ask_mod.warm("no-such-manual")


def test_a_warm_up_that_throws_is_swallowed(monkeypatch):
    """A warm-up may never break the session it is warming."""
    from app import ask as ask_mod
    from app.search import get_index

    def boom(*args, **kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(get_index(), "query", boom)
    ask_mod.warm(KTM)


def test_opening_a_voice_session_warms_that_manual_off_the_request_thread(client, https_base, monkeypatch):
    warmed: list[str] = []
    started = threading.Event()

    def fake_warm(manual_id: str) -> None:
        warmed.append(manual_id)
        started.set()

    monkeypatch.setattr("app.ask.warm", fake_warm)
    r = client.get("/voice/agent-settings", params={"manualId": KTM})
    assert r.status_code == 200
    assert started.wait(5), "the warm-up never ran"
    assert warmed == [KTM]


def test_a_session_that_never_opens_warms_nothing(client, monkeypatch):
    """An http PUBLIC_BASE is refused before the Settings message exists; nothing gets warmed for it."""
    warmed: list[str] = []
    monkeypatch.setattr("app.ask.warm", warmed.append)
    assert client.get("/voice/agent-settings", params={"manualId": KTM}).status_code == 503
    assert warmed == []

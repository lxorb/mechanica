"""The four webhook tools an ElevenLabs agent may call, plus /voice/config and the shared-secret guard.

Every tool must hand back the manual's own words and the page they are printed on: no paraphrase,
no invented number. The BMW rider's manual is the fixture because it is the longer of the two.
"""

import json
import os

import pytest

from conftest import BMW, DATA_DIR, KTM

TOOLS = ["/voice/tools/find_procedure", "/voice/tools/read_page", "/voice/tools/get_spec", "/voice/tools/list_parts"]
CHUNK = 1200


@pytest.fixture(scope="module")
def bmw_pages() -> dict[int, str]:
    rows = json.loads((DATA_DIR / "pages" / f"{BMW}.json").read_text(encoding="utf-8"))
    return {r["page"]: r["text"] for r in rows}


@pytest.fixture(scope="module")
def long_page(bmw_pages) -> int:
    return max(bmw_pages, key=lambda p: len(bmw_pages[p]))


# ---------------------------------------------------------------- config


def test_config(client):
    r = client.get("/voice/config")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"elevenlabsAgentId", "deepgram"}
    assert body["elevenlabsAgentId"] == "agent_test"
    assert isinstance(body["deepgram"], bool)


# ---------------------------------------------------------------- read_page


def test_read_page_is_verbatim(client, bmw_pages):
    page = 164
    r = client.post("/voice/tools/read_page", json={"manualId": BMW, "page": page})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"page", "text", "hasMore", "nextOffset"}
    assert body["page"] == page
    printed = bmw_pages[page]
    assert body["text"] == printed[: len(body["text"])]
    assert printed.startswith(body["text"])


def test_read_page_chunks_and_resumes_without_losing_a_character(client, bmw_pages, long_page):
    printed = bmw_pages[long_page]
    assert len(printed) > CHUNK, "fixture page is too short to exercise chunking"

    collected = ""
    offset = 0
    for _ in range(20):
        body = client.post("/voice/tools/read_page", json={"manualId": BMW, "page": long_page, "offset": offset}).json()
        assert len(body["text"]) <= CHUNK
        assert body["nextOffset"] == offset + len(body["text"])
        collected += body["text"]
        offset = body["nextOffset"]
        if not body["hasMore"]:
            break
    else:
        pytest.fail("read_page never reported the end of the page")

    assert collected == printed
    assert offset == len(printed)


def test_read_page_first_chunk_reports_more(client, long_page):
    body = client.post("/voice/tools/read_page", json={"manualId": BMW, "page": long_page}).json()
    assert body["hasMore"] is True
    assert 0 < body["nextOffset"] <= CHUNK


def test_read_page_offset_past_the_end_is_empty_and_final(client, bmw_pages, long_page):
    body = client.post(
        "/voice/tools/read_page",
        json={"manualId": BMW, "page": long_page, "offset": len(bmw_pages[long_page]) + 50},
    ).json()
    assert body["text"] == ""
    assert body["hasMore"] is False


def test_read_page_unknown_manual_and_unknown_page(client):
    assert client.post("/voice/tools/read_page", json={"manualId": "nope", "page": 1}).status_code == 404
    assert client.post("/voice/tools/read_page", json={"manualId": BMW, "page": 99999}).status_code == 404


# ---------------------------------------------------------------- get_spec


def test_get_spec_quotes_the_manual(client):
    body = client.post("/voice/tools/get_spec", json={"manualId": BMW, "name": "tyre pressure"}).json()
    specs = body["specs"]
    assert specs, "no tyre pressure spec found"
    assert len(specs) <= 8
    for s in specs:
        assert set(s) == {"name", "value", "unit", "page", "quote", "sectionId"}
        assert "tyre pressure" in s["name"].lower()
        assert s["page"] > 0
        assert s["value"] and s["value"] in s["quote"]
    assert any("bar" in s["value"] for s in specs)


def test_get_spec_falls_back_to_single_words(client):
    body = client.post("/voice/tools/get_spec", json={"manualId": BMW, "name": "how thin can the front pads get"}).json()
    names = [s["name"].lower() for s in body["specs"]]
    assert names, "the word-level fallback returned nothing"
    assert any("wear limit" in n or "brake" in n for n in names)


def test_get_spec_answers_the_end_that_was_asked_for(client):
    """"and the front one?" is the whole question. A word-level match for "front axle nut torque"
    used to come back with "Nut, rear wheel spindle" - the right shape, the wrong end, 55 Nm of
    difference - and spoken aloud there is no page on screen to catch it."""
    front = client.post("/voice/tools/get_spec", json={"manualId": KTM, "name": "front axle nut torque"}).json()
    assert front["specs"], "the front spindle torque is printed in this manual"
    assert "front" in front["specs"][0]["name"].lower()
    assert not any("rear" in s["name"].lower() for s in front["specs"])

    rear = client.post("/voice/tools/get_spec", json={"manualId": KTM, "name": "rear axle nut torque"}).json()
    assert "rear" in rear["specs"][0]["name"].lower()
    assert rear["specs"][0]["value"] != front["specs"][0]["value"]


def test_get_spec_prefers_the_kind_of_figure_that_was_asked_for(client):
    """"torque" is not a word that happens to appear, it says which column of the book to read."""
    body = client.post("/voice/tools/get_spec", json={"manualId": KTM, "name": "front axle nut torque"}).json()
    assert "Nm" in body["specs"][0]["value"], "a pressure shares the word 'front' and nothing else"


def test_get_spec_unknown_name_returns_an_empty_list_not_a_guess(client):
    body = client.post("/voice/tools/get_spec", json={"manualId": BMW, "name": "zzzz"}).json()
    assert body == {"specs": []}


def test_get_spec_unknown_manual(client):
    assert client.post("/voice/tools/get_spec", json={"manualId": "nope", "name": "oil"}).status_code == 404


# ---------------------------------------------------------------- list_parts


def test_list_parts_for_the_whole_manual(client):
    body = client.post("/voice/tools/list_parts", json={"manualId": BMW}).json()
    parts = body["parts"]
    assert parts and len(parts) <= 12
    for p in parts:
        assert set(p) == {"name", "spec", "page", "oem", "shop", "url"}
        assert p["name"] and p["spec"] and p["page"] > 0
    assert any(p["name"] == "Engine oil" for p in parts)


def test_list_parts_narrows_to_a_section(client):
    body = client.post("/voice/tools/list_parts", json={"manualId": BMW, "sectionId": "engine-oil-level"}).json()
    names = [p["name"] for p in body["parts"]]
    assert names == ["Engine oil"]


def test_list_parts_unknown_section_falls_back_to_the_whole_manual(client):
    everything = client.post("/voice/tools/list_parts", json={"manualId": BMW}).json()
    body = client.post("/voice/tools/list_parts", json={"manualId": BMW, "sectionId": "no-such-section"}).json()
    assert body == everything


def test_list_parts_unknown_manual(client):
    assert client.post("/voice/tools/list_parts", json={"manualId": "nope"}).status_code == 404


# ---------------------------------------------------------------- find_procedure


def test_find_procedure(client, monkeypatch):
    from app.models import AskResponse, Match
    from app.store import get_store

    manual = get_store().manual(BMW)
    wanted = [s for s in manual.sections if s.id in {"engine-oil-level", "engine-oil-topup"}]
    assert len(wanted) == 2

    calls: list[tuple[str, str]] = []

    def fake_answer(manual_id: str, query: str) -> AskResponse:
        calls.append((manual_id, query))
        return AskResponse(matches=[Match(section=s, score=1.0 - 0.1 * i) for i, s in enumerate(wanted)], intent="procedure")

    monkeypatch.setattr("app.ask.answer", fake_answer)

    body = client.post("/voice/tools/find_procedure", json={"manualId": BMW, "query": "check my oil"}).json()
    assert calls == [(BMW, "check my oil")]
    assert body["firstPage"] == wanted[0].pageStart
    assert [s["id"] for s in body["sections"]] == [s.id for s in wanted]
    for got, want in zip(body["sections"], wanted):
        assert set(got) == {"id", "title", "chapter", "pageStart", "pageEnd"}
        assert got["title"] == want.title
        assert got["pageStart"] == want.pageStart
    assert "text" not in json.dumps(body["sections"][0])


def test_find_procedure_with_no_matches_reports_page_zero(client, monkeypatch):
    from app.models import AskResponse

    monkeypatch.setattr("app.ask.answer", lambda m, q: AskResponse(matches=[], intent="unknown"))
    body = client.post("/voice/tools/find_procedure", json={"manualId": BMW, "query": "how do I fly"}).json()
    assert body == {"sections": [], "firstPage": 0}


def test_find_procedure_unknown_manual(client):
    assert client.post("/voice/tools/find_procedure", json={"manualId": "nope", "query": "oil"}).status_code == 404


def test_find_procedure_surfaces_an_unavailable_index_as_501(client, monkeypatch):
    def boom(manual_id, query):
        raise NotImplementedError

    monkeypatch.setattr("app.ask.answer", boom)
    assert client.post("/voice/tools/find_procedure", json={"manualId": BMW, "query": "oil"}).status_code == 501


# ---------------------------------------------------------------- the shared secret


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("VOICE_TOOL_SECRET", "s3cret")
    return "s3cret"


BODIES = {
    "/voice/tools/find_procedure": {"manualId": BMW, "query": "oil"},
    "/voice/tools/read_page": {"manualId": BMW, "page": 164},
    "/voice/tools/get_spec": {"manualId": BMW, "name": "tyre pressure"},
    "/voice/tools/list_parts": {"manualId": BMW},
}


@pytest.mark.parametrize("path", TOOLS)
def test_tools_are_open_when_no_secret_is_configured(client, path):
    assert "VOICE_TOOL_SECRET" not in os.environ
    assert client.post(path, json=BODIES[path]).status_code != 401


@pytest.mark.parametrize("path", TOOLS)
def test_tools_401_without_the_header(client, secret, path):
    assert client.post(path, json=BODIES[path]).status_code == 401


@pytest.mark.parametrize("path", TOOLS)
def test_tools_401_with_a_wrong_header(client, secret, path):
    r = client.post(path, json=BODIES[path], headers={"X-Voice-Secret": "wrong"})
    assert r.status_code == 401


@pytest.mark.parametrize("path", TOOLS)
def test_tools_pass_with_the_right_header(client, secret, path, monkeypatch):
    from app.models import AskResponse

    monkeypatch.setattr("app.ask.answer", lambda m, q: AskResponse(matches=[], intent="unknown"))
    r = client.post(path, json=BODIES[path], headers={"X-Voice-Secret": secret})
    assert r.status_code == 200


def test_config_is_not_behind_the_secret(client, secret):
    assert client.get("/voice/config").status_code == 200


def test_deepgram_token_without_a_key_is_501(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepgram_api_key", None)
    assert client.post("/voice/deepgram-token").status_code == 501

"""The Deepgram Voice Agent wiring: GET /voice/agent-settings, and the tool handlers seen from
Deepgram's side rather than from ours.

The settings endpoint is the whole contract with the browser — one wrong field and the socket
closes with an error nobody can read out loud — so every field the Settings message must carry is
asserted here, and every promise the prompt makes (one or two sentences, spoken, never a dealer,
never a guessed figure) is asserted as text.

The four grounded tools already have their own suite in test_voice.py, which calls them the way
THIS api calls them: manualId in the body. Deepgram calls them differently — only the model's own
arguments in the body, the manual id in the endpoint's query string — so they are exercised again
from that side. No network: the one HTTP call in this module (key minting) is mocked.
"""

import json

import pytest

from conftest import BMW, KTM

SETTINGS = "/voice/agent-settings"
SERVER_TOOLS = ["find_procedure", "read_page", "get_spec", "list_parts"]
BASE = "https://ttm.example.test/api"


@pytest.fixture(autouse=True)
def https_base(monkeypatch):
    """Deepgram calls the tool endpoints from its own servers and accepts https only, so every
    test here runs against a deployed-shaped base. conftest's http://testserver is the local
    default, and what it does is asserted by itself below."""
    from app.config import settings

    monkeypatch.setattr(settings, "public_base", BASE)


@pytest.fixture
def ktm(client):
    r = client.get(SETTINGS, params={"manualId": KTM})
    assert r.status_code == 200
    return r.json()


@pytest.fixture
def agent(ktm):
    return ktm["settings"]["agent"]


# ---------------------------------------------------------------- the envelope


def test_settings_carries_the_socket_and_the_rate_the_browser_must_capture_at(ktm):
    assert ktm["url"] == "wss://agent.deepgram.com/v1/agent/converse"
    assert ktm["sampleRate"] == 24000
    assert ktm["manualId"] == KTM
    assert ktm["settings"]["type"] == "Settings"


def test_audio_is_linear16_at_the_advertised_rate_both_ways(ktm):
    audio = ktm["settings"]["audio"]
    assert audio["input"] == {"encoding": "linear16", "sample_rate": ktm["sampleRate"]}
    assert audio["output"] == {"encoding": "linear16", "sample_rate": ktm["sampleRate"], "container": "none"}


def test_unknown_manual_is_404_not_an_empty_agent(client):
    assert client.get(SETTINGS, params={"manualId": "nope"}).status_code == 404


# ---------------------------------------------------------------- providers


def test_listen_speak_and_think_providers(agent):
    assert agent["language"] == "en"
    assert agent["speak"]["provider"] == {"type": "deepgram", "model": "aura-2-asteria-en"}
    assert agent["think"]["provider"]["type"] == "open_ai"


def test_listening_is_flux_with_eager_end_of_turn(agent):
    """Flux detects the end of a turn inside the model and, with an eager threshold, starts the
    answer before the rider has stopped. Measured at 1.35 s to first audio against nova-3's 1.97."""
    listen = agent["listen"]["provider"]
    assert listen["type"] == "deepgram"
    assert listen["version"] == "v2", "flux is a listen v2 model"
    assert listen["model"] == "flux-general-en"
    assert 0.3 <= listen["eager_eot_threshold"] <= listen["eot_threshold"] <= 1.0
    assert 500 <= listen["eot_timeout_ms"] <= 3000, "a mechanic's question ends when it ends"


def test_the_listen_config_is_copied_not_shared(client):
    """The module-level dict must not be handed out by reference, or one response's edit - the
    per-manual keyterms, for one - would follow every later one."""
    from app import voice as voice_mod

    body = client.get(SETTINGS, params={"manualId": KTM}).json()
    listen = body["settings"]["agent"]["listen"]["provider"]
    assert listen is not voice_mod.LISTEN
    assert "keyterms" not in voice_mod.LISTEN
    assert {k: v for k, v in listen.items() if k != "keyterms"} == voice_mod.LISTEN


# ---------------------------------------------------------------- keyterm prompting


@pytest.fixture
def keyterms(agent):
    return agent["listen"]["provider"]["keyterms"]


def test_the_transcriber_is_primed_with_this_bikes_vocabulary(keyterms, ktm):
    """Keyterm prompting, the Voice Agent's own spelling of it: a list of plain strings on the
    listen provider. Deepgram accepts up to 100 of them, 500 tokens, for flux and nova-3."""
    assert isinstance(keyterms, list) and keyterms
    assert len(keyterms) <= 100
    assert all(isinstance(t, str) and t.strip() == t and t for t in keyterms)
    assert sum(len(t) + 1 for t in keyterms) <= 1500, "well inside Deepgram's 500-token ceiling"
    assert ktm["keyterms"] == len(keyterms), "the count is reported so a screen can show it"


def test_the_bike_leads_and_the_manuals_own_words_follow(keyterms):
    assert keyterms[0] == "KTM 390 Duke 2024", "mishear the bike and the thread is lost"
    low = [t.lower() for t in keyterms]
    assert "engine oil" in low, "a part this manual names"
    assert any("chain" in t for t in low), "a job this manual covers"


def test_a_keyterm_is_a_term_not_a_heading(keyterms):
    """Deepgram asks for a phrase per element. A whole instruction ("Checking that the brake
    linings of the front brake are secured") primes the wrong words, so it is dropped, not cut."""
    for term in keyterms:
        assert 1 <= len(term.split()) <= 5, term
        assert "(" not in term and ")" not in term and "," not in term, term
        assert not term.lower().startswith(("checking", "changing", "adjusting", "the ")), term


def test_two_manuals_are_primed_differently(client, keyterms):
    other = client.get(SETTINGS, params={"manualId": BMW}).json()
    theirs = other["settings"]["agent"]["listen"]["provider"]["keyterms"]
    assert theirs[0].startswith("BMW")
    assert set(theirs) != set(keyterms), "the priming follows the bike on the lift"


def test_the_standard_catalogue_fills_what_the_manual_never_prints(keyterms):
    """An owner manual's index is short. The parts taxonomy knows the words a mechanic says that
    this book never prints, and it gets the tail of the budget - spread across every group, so the
    suspension and the wheels are reached and not twelve more ways to say "oil filter"."""
    low = {t.lower() for t in keyterms}
    assert "fork springs" in low or "fork oil seals" in low, "suspension was reached"
    assert any("wheel bearings" in t for t in low), "wheels were reached"


def test_the_page_count_reaches_the_browser(ktm):
    """The reader will not jump to a page this manual does not have, so it needs the count."""
    assert ktm["pages"] > 0


def test_think_model_is_one_deepgram_lists_for_open_ai(agent):
    # https://developers.deepgram.com/docs/voice-agent-llm-models
    supported = {
        "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4",
        "gpt-5.3-chat-latest", "gpt-5.2-chat-latest", "gpt-5.2", "gpt-5.1-chat-latest", "gpt-5.1",
        "gpt-5-nano", "gpt-5-mini", "gpt-5", "gpt-4.1-nano", "gpt-4.1-mini", "gpt-4.1",
        "gpt-4o-mini", "gpt-4o",
    }
    assert agent["think"]["provider"]["model"] in supported


def test_the_think_model_is_overridable_without_a_deploy(client, monkeypatch):
    monkeypatch.setattr("app.voice.THINK_MODEL", "gpt-4o-mini")
    body = client.get(SETTINGS, params={"manualId": KTM}).json()
    assert body["settings"]["agent"]["think"]["provider"]["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------- the greeting


def test_greeting_names_the_make_model_and_year(client, ktm):
    assert ktm["bike"] == "KTM 390 Duke 2024"
    assert ktm["settings"]["agent"]["greeting"] == "KTM 390 Duke 2024. Go ahead."


def test_an_explicit_bike_id_wins_over_the_manuals_first_bike(client):
    body = client.get(SETTINGS, params={"manualId": KTM, "bikeId": "ktm-390-duke-2024"}).json()
    assert body["bike"] == "KTM 390 Duke 2024"


def test_an_unknown_bike_id_falls_back_to_the_manual_rather_than_greeting_nobody(client):
    body = client.get(SETTINGS, params={"manualId": KTM, "bikeId": "no-such-bike"}).json()
    assert body["bike"] == "KTM 390 Duke 2024"
    assert body["settings"]["agent"]["greeting"].startswith("KTM 390 Duke 2024.")


# ---------------------------------------------------------------- the digest


def digest_of(prompt: str) -> str:
    head, _, rest = prompt.partition("WHAT THIS MANUAL CONTAINS:\n")
    assert head, "the context block moved"
    return rest.split("\n\n")[0]


def test_the_prompt_carries_the_bike_the_title_and_a_digest(agent):
    prompt = agent["think"]["prompt"]
    assert "THE BIKE: KTM 390 Duke 2024" in prompt
    assert "OWNER'S MANUAL 2024 390 DUKE" in prompt
    assert "143 printed pages" in prompt


def test_the_digest_is_the_manuals_own_chapters_with_page_ranges(agent):
    digest = digest_of(agent["think"]["prompt"])
    assert "13 BRAKE SYSTEM (p. 82-89)" in digest
    assert "14 WHEELS, TIRES (p. 90-95)" in digest
    assert "18 SERVICE WORK ON THE ENGINE (p. 114-116)" in digest
    # Every chapter the manual prints, not a truncated head of them.
    assert len(digest.splitlines()) == 30
    for line in digest.splitlines():
        assert line.endswith(")") and "(p. " in line, line


def test_the_digest_stays_under_1500_characters_on_every_seeded_manual(client):
    from app.voice import DIGEST_CHARS

    for manual_id in (KTM, BMW):
        prompt = client.get(SETTINGS, params={"manualId": manual_id}).json()["settings"]["agent"]["think"]["prompt"]
        assert 0 < len(digest_of(prompt)) <= DIGEST_CHARS


def test_a_manual_with_no_outline_still_gets_a_digest_from_its_sections(client, monkeypatch):
    from app.store import get_store

    manual = get_store().manual(KTM).model_copy(deep=True)
    manual.outline = []
    monkeypatch.setattr("app.voice.get_store", lambda: type("S", (), {
        "manual": staticmethod(lambda mid: manual if mid == KTM else None),
        "bike": staticmethod(lambda bid: None),
    })())
    digest = digest_of(client.get(SETTINGS, params={"manualId": KTM}).json()["settings"]["agent"]["think"]["prompt"])
    assert digest
    assert "SERVICE WORK ON THE ENGINE (p. " in digest


# ---------------------------------------------------------------- the prompt's promises


@pytest.mark.parametrize(
    "phrase",
    [
        "One sentence. A second one only when it carries a different fact",
        "No bullet points",
        "no markdown",
        "Answer ONLY from what a function gave you back",
        "NEVER guess",
        "The page first, in the same sentence as the figure",
        "NEVER finish with a question, an offer or a check-in",
        "EVERY QUESTION IS A NEW QUESTION",
    ],
)
def test_the_spoken_style_is_spelled_out(agent, phrase):
    assert phrase in agent["think"]["prompt"]


def test_the_grounding_rule_stands_above_the_style_rules(agent):
    """Measured, not assumed: with this rule written as one more bullet, gpt-4.1 answered "how
    much engine oil does it take?" off its own memory of the 390 Duke - twice, with two different
    wrong capacities and no function call. Hoisted above the list, four runs out of four called
    get_spec and said the 1.5 l the manual prints."""
    prompt = agent["think"]["prompt"]
    head = prompt.split("How you answer:")[0]
    assert "THE ONE RULE ABOVE ALL OTHERS" in head
    assert "You do not know anything about this motorcycle" in head
    assert "Call\na function FIRST" in head


@pytest.mark.parametrize("filler", ["sure", "of course", "great question", "let me check", "according to the manual"])
def test_the_prompt_names_the_filler_openings_it_bans(agent, filler):
    """A spoken answer that opens with "sure, let me check" has already spent the second that
    made voice worth using."""
    prompt = agent["think"]["prompt"].lower()
    assert "no filler, ever" in prompt
    assert f'"{filler}"' in prompt


def test_the_prompt_bans_the_dealer_referral(agent):
    prompt = agent["think"]["prompt"].lower()
    assert "never tell anyone to visit, consult or contact a dealer" in prompt
    for word in ("retailer", "authorised workshop", "specialist", "service centre"):
        assert word in prompt


def test_a_job_the_manual_names_but_does_not_print_gets_the_general_steps(agent):
    """Same policy as the typed chat: the ordinary workshop procedure, marked as general, plus
    every figure the manual does print - never the referral the manual prints instead."""
    prompt = agent["think"]["prompt"]
    assert "naming the job but printing no steps" in prompt
    assert "the manual\n  doesn't print the steps" in prompt
    assert "Mark the general part as general" in prompt
    assert "the usual way\n  is" in prompt
    assert "say every figure the\n  manual DOES print for that job with its page" in prompt
    # the licence must not leak into the figures, which is the whole safety of the feature
    assert "This licence covers STEPS AND ORDER ONLY" in prompt
    assert "general steps carry no figures" in prompt


def test_the_prompt_says_what_to_do_when_the_manual_does_not_cover_it_at_all(agent):
    """One sentence, and no offer on the end of it. The offer used to be in this rule and the
    agent duly ended a live turn with "do you want the page on the brake system opened?", which
    is a question a mechanic with both hands on a wheel cannot answer.
    """
    prompt = agent["think"]["prompt"]
    assert "say so in one sentence" in prompt
    assert "Never carry a figure over from another motorcycle" in prompt
    assert "offer to open the closest" not in prompt


# ---------------------------------------------------------------- the functions


def by_name(agent) -> dict[str, dict]:
    return {f["name"]: f for f in agent["think"]["functions"]}


def test_every_tool_is_exposed_exactly_once(agent):
    fns = by_name(agent)
    assert sorted(fns) == sorted([*SERVER_TOOLS, "show_page"])
    assert len(agent["think"]["functions"]) == len(fns)


@pytest.mark.parametrize("name", SERVER_TOOLS)
def test_grounded_tools_are_server_side_and_carry_the_manual_in_the_url(agent, name):
    endpoint = by_name(agent)[name]["endpoint"]
    assert endpoint["method"] == "post"
    assert endpoint["url"] == f"{BASE}/voice/tools/{name}?manualId={KTM}"


def test_a_plain_http_public_base_is_refused_with_the_reason(client, monkeypatch):
    """Deepgram answers an http endpoint with INVALID_SETTINGS and closes the socket a second
    after the rider pressed VOICE. Refuse it here, where the message can still be read."""
    from app.config import settings

    monkeypatch.setattr(settings, "public_base", "http://localhost:8000")
    r = client.get(SETTINGS, params={"manualId": KTM})
    assert r.status_code == 503
    assert "https" in r.json()["detail"]
    assert "http://localhost:8000" in r.json()["detail"]


def test_show_page_is_client_side_so_the_browser_moves_the_reader(agent):
    show = by_name(agent)["show_page"]
    assert "endpoint" not in show
    assert show["parameters"]["required"] == ["page"]
    assert show["parameters"]["properties"]["page"]["type"] == "integer"


def test_show_page_carries_the_highlight_and_the_printed_steps(agent):
    """The browser never sees a tool result - Deepgram fetches the manual's text, not the tab.

    So the only way the manual's printed steps can be WRITTEN on the mechanic's screen is if the
    agent hands them over in the call that turns the page. Both are optional; the page is not.
    """
    props = by_name(agent)["show_page"]["parameters"]["properties"]
    assert props["highlight"]["type"] == "string"
    assert props["steps"]["type"] == "array"
    assert props["steps"]["items"]["type"] == "string"
    assert "word for word" in props["steps"]["description"]
    assert "highlight" not in by_name(agent)["show_page"]["parameters"]["required"]
    assert "steps" not in by_name(agent)["show_page"]["parameters"]["required"]


def test_the_prompt_turns_the_page_before_it_speaks(agent):
    """A page named after the fact is a page he has to go and find himself."""
    prompt = agent["think"]["prompt"]
    assert "TURN THE PAGE FOR THE MECHANIC, THEN SPEAK" in prompt
    # and the steps licence is bounded to what a result actually printed
    assert "Never write a step the result did not print" in prompt


@pytest.mark.parametrize("name", [*SERVER_TOOLS, "show_page"])
def test_every_function_is_a_usable_json_schema(agent, name):
    fn = by_name(agent)[name]
    assert fn["description"].strip()
    params = fn["parameters"]
    assert params["type"] == "object"
    assert isinstance(params["properties"], dict)
    for key in params.get("required", []):
        assert key in params["properties"]


def test_the_manual_id_is_never_a_thing_the_model_has_to_say(agent):
    """It rides in the URL. An agent that could name the book could name the wrong one."""
    for fn in agent["think"]["functions"]:
        assert "manualId" not in fn["parameters"]["properties"]


def test_the_shared_secret_travels_as_a_header_when_one_is_configured(client, monkeypatch):
    monkeypatch.setenv("VOICE_TOOL_SECRET", "s3cret")
    agent = client.get(SETTINGS, params={"manualId": KTM}).json()["settings"]["agent"]
    for name in SERVER_TOOLS:
        assert by_name(agent)[name]["endpoint"]["headers"] == {"x-voice-secret": "s3cret"}


def test_no_header_key_at_all_when_the_api_is_open(agent):
    for name in SERVER_TOOLS:
        assert "headers" not in by_name(agent)[name]["endpoint"]


def test_the_key_is_never_in_the_settings_the_browser_receives(client, ktm, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepgram_api_key", "dg-super-secret")
    body = json.dumps(client.get(SETTINGS, params={"manualId": KTM}).json())
    assert "dg-super-secret" not in body


# ---------------------------------------------------------------- the tools, as Deepgram calls them


def test_read_page_with_the_manual_only_in_the_query_string(client):
    r = client.post(f"/voice/tools/read_page?manualId={KTM}", json={"page": 114})
    assert r.status_code == 200
    assert r.json()["page"] == 114
    assert r.json()["text"].strip()


def test_get_spec_with_the_manual_only_in_the_query_string(client):
    body = client.post(f"/voice/tools/get_spec?manualId={KTM}", json={"name": "tyre pressure"}).json()
    assert body["specs"], "no spec came back for the Deepgram-shaped call"
    assert all(s["page"] > 0 for s in body["specs"])


def test_list_parts_with_no_arguments_at_all(client):
    body = client.post(f"/voice/tools/list_parts?manualId={KTM}", json={}).json()
    assert body["parts"]


def test_arguments_nested_as_a_json_string_are_unwrapped(client):
    """FunctionCallRequest carries `arguments` as a JSON string; an endpoint envelope could too."""
    r = client.post(f"/voice/tools/read_page?manualId={KTM}", json={"arguments": json.dumps({"page": 114})})
    assert r.status_code == 200
    assert r.json()["page"] == 114


def test_arguments_nested_as_an_object_are_unwrapped(client):
    r = client.post(f"/voice/tools/get_spec?manualId={KTM}", json={"parameters": {"name": "tyre pressure"}})
    assert r.status_code == 200
    assert r.json()["specs"]


def test_a_body_manual_id_still_wins_so_our_own_callers_are_untouched(client):
    r = client.post(f"/voice/tools/read_page?manualId={KTM}", json={"manualId": BMW, "page": 164})
    assert r.status_code == 200
    printed = client.post("/voice/tools/read_page", json={"manualId": BMW, "page": 164}).json()
    assert r.json() == printed


def test_no_manual_anywhere_is_404_rather_than_a_silent_wrong_book(client):
    assert client.post("/voice/tools/read_page", json={"page": 1}).status_code == 404


def test_find_procedure_through_the_deepgram_shape(client, monkeypatch):
    from app.models import AskResponse, Match
    from app.store import get_store

    wanted = [s for s in get_store().manual(KTM).sections if s.id == "engine-oil-level"]
    assert wanted
    seen: list[tuple[str, str]] = []

    def fake_answer(manual_id: str, query: str) -> AskResponse:
        seen.append((manual_id, query))
        return AskResponse(matches=[Match(section=wanted[0], score=1.0)], intent="procedure")

    monkeypatch.setattr("app.ask.answer", fake_answer)
    body = client.post(f"/voice/tools/find_procedure?manualId={KTM}", json={"query": "how do I check the oil"}).json()
    assert seen == [(KTM, "how do I check the oil")]
    assert body["firstPage"] == wanted[0].pageStart


# ---------------------------------------------------------------- the browser's key


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.Client so nothing leaves the machine; records what was asked of it.

    `deny` is the set of paths this fake account has no scope for, which is the whole point:
    the seeded Deepgram key on this project can mint NEITHER a project key nor a grant, and the
    endpoint has to walk both doors before it gives up.
    """

    calls: list[tuple[str, str, dict | None]] = []
    headers: dict = {}
    deny: tuple[str, ...] = ()

    def __init__(self, base_url, headers, timeout):
        FakeClient.headers = dict(headers)
        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _blocked(self, path):
        return any(mark in path for mark in FakeClient.deny)

    def get(self, path):
        FakeClient.calls.append(("GET", path, None))
        if self._blocked(path):
            return FakeResponse({"err_msg": "Insufficient permissions."}, 403)
        return FakeResponse({"projects": [{"project_id": "proj-1"}]})

    def post(self, path, json=None):
        FakeClient.calls.append(("POST", path, json))
        if self._blocked(path):
            return FakeResponse({"err_msg": "Insufficient permissions."}, 403)
        if path.endswith("/auth/grant"):
            return FakeResponse({"access_token": "dg-jwt", "expires_in": 30})
        return FakeResponse({"key": "dg-temp-key"})


@pytest.fixture
def fake_deepgram(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepgram_api_key", "dg-master-key")
    monkeypatch.setattr("app.voice._project", None)
    FakeClient.calls = []
    FakeClient.deny = ()
    monkeypatch.setattr("app.voice.httpx.Client", FakeClient)
    return FakeClient


def test_the_browser_key_is_short_lived_scoped_and_carries_its_subprotocol(client, fake_deepgram):
    body = client.post("/voice/deepgram-token").json()
    assert body["key"] == "dg-temp-key"
    assert body["scheme"] == "token"
    assert 0 < body["expiresIn"] <= 3600

    minted = [c for c in fake_deepgram.calls if c[0] == "POST"]
    assert len(minted) == 1
    _, path, payload = minted[0]
    assert path == "/v1/projects/proj-1/keys"
    assert payload["scopes"] == ["usage:write"]
    assert payload["time_to_live_in_seconds"] == body["expiresIn"]
    assert fake_deepgram.headers["Authorization"] == "Token dg-master-key"


def test_a_key_without_keys_write_falls_back_to_a_grant_and_says_which_subprotocol(client, fake_deepgram):
    fake_deepgram.deny = ("/keys",)
    body = client.post("/voice/deepgram-token").json()
    assert body == {"key": "dg-jwt", "expiresIn": 30, "scheme": "bearer"}
    assert ("POST", "/v1/auth/grant", {"ttl_seconds": 30}) in fake_deepgram.calls


def test_a_key_that_cannot_list_projects_still_tries_the_grant(client, fake_deepgram):
    fake_deepgram.deny = ("/v1/projects",)
    body = client.post("/voice/deepgram-token").json()
    assert body["scheme"] == "bearer"


def test_both_doors_shut_is_a_502_that_names_the_missing_scope(client, fake_deepgram):
    fake_deepgram.deny = ("/keys", "/auth/grant")
    r = client.post("/voice/deepgram-token")
    assert r.status_code == 502
    assert "keys:write" in r.json()["detail"]


def test_the_master_key_never_reaches_the_browser(client, fake_deepgram):
    assert "dg-master-key" not in json.dumps(client.post("/voice/deepgram-token").json())

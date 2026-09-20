"""The ElevenLabs path: GET /voice/elevenlabs/session, the four tools seen from ElevenLabs' side,
and the agent/tool bodies api/tools/elevenlabs_setup.py would POST.

Nothing here touches the network. The one outbound call the session endpoint makes (minting a
conversation credential) is mocked at httpx.Client, and the setup tool is exercised through its
body builders, which is the whole of what it decides.

The thing being protected is the binding between a session and ONE BOOK. ElevenLabs offers the
manual id three ways - a substituted header, a substituted query string, and the model's own
argument - and the order they are resolved in is the difference between an agent that reads the
right manual and one that can be talked into reading a different one.
"""


import json
from types import SimpleNamespace

import pytest

from conftest import BMW, KTM

SESSION = "/voice/elevenlabs/session"
TOOLS = "/voice/elevenlabs/tools"
SERVER_TOOLS = ["find_procedure", "read_page", "get_spec", "list_parts"]
BASE = "https://ttm.example.test/api"


@pytest.fixture(autouse=True)
def https_base(monkeypatch):
    """ElevenLabs calls the tool endpoints from its own servers, over https only."""
    from app.config import settings

    monkeypatch.setattr(settings, "public_base", BASE)


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    """Default to the state of this machine: an agent id, no account key. Tests that need a key
    set one themselves."""
    from app.config import settings

    monkeypatch.setattr(settings, "elevenlabs_api_key", None)


# ---------------------------------------------------------------- the session


def test_session_binds_one_bike_and_one_book(client):
    r = client.get(SESSION, params={"manualId": KTM})
    assert r.status_code == 200
    body = r.json()
    assert body["agentId"] == "agent_test"
    assert body["manualId"] == KTM
    variables = body["dynamicVariables"]
    assert variables["manual_id"] == KTM
    assert variables["bike_name"] == body["bike"] and variables["bike_name"]
    # The digest is what lets the agent say "that is not in this manual" without a round trip.
    assert variables["manual_digest"] and len(variables["manual_digest"]) <= 1500
    assert variables["manual_pages"].isdigit() and int(variables["manual_pages"]) > 0


def test_session_404s_on_a_manual_that_does_not_exist(client):
    assert client.get(SESSION, params={"manualId": "no-such-manual"}).status_code == 404


def test_session_501s_when_no_agent_has_been_created(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "elevenlabs_agent_id", None)
    r = client.get(SESSION, params={"manualId": KTM})
    assert r.status_code == 501
    assert "elevenlabs_setup" in r.json()["detail"]


def test_without_an_account_key_the_session_is_public_and_carries_no_credential(client):
    body = client.get(SESSION, params={"manualId": KTM}).json()
    assert body["auth"] == "public"
    assert body["connectionType"] == "webrtc"
    assert "conversationToken" not in body and "signedUrl" not in body


class _Reply:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeEleven:
    """Stands in for httpx.Client against api.elevenlabs.io. Records what was asked for."""

    def __init__(self, replies: dict):
        self.replies = replies
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict = {}

    def __call__(self, *, base_url, headers, timeout):
        assert base_url == "https://api.elevenlabs.io"
        self.headers = headers
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path, params=None):
        self.calls.append((path, params or {}))
        return self.replies.get(path, _Reply(404, {}))


@pytest.fixture
def eleven(monkeypatch):
    """Install a fake ElevenLabs HTTP client; the test supplies the replies."""
    import app.voice_elevenlabs as mod
    from app.config import settings

    monkeypatch.setattr(settings, "elevenlabs_api_key", "xi-test-key")

    def install(replies):
        fake = _FakeEleven(replies)
        # Only this module's httpx, so the TestClient's own transport is untouched.
        monkeypatch.setattr(mod, "httpx", SimpleNamespace(Client=fake))
        return fake

    return install


def test_a_key_mints_a_webrtc_token_and_the_key_itself_never_leaves_the_server(client, eleven):
    fake = eleven(
        {"/v1/convai/conversation/token": _Reply(200, {"token": "tok_live", "conversation_id": "conv_1"})}
    )
    body = client.get(SESSION, params={"manualId": KTM}).json()
    assert body["auth"] == "token"
    assert body["connectionType"] == "webrtc"
    assert body["conversationToken"] == "tok_live"
    assert body["conversationId"] == "conv_1"
    assert fake.headers["xi-api-key"] == "xi-test-key"
    assert fake.calls[0] == ("/v1/convai/conversation/token", {"agent_id": "agent_test"})
    assert "xi-test-key" not in json.dumps(body)


def test_an_account_without_webrtc_falls_back_to_a_signed_websocket_url(client, eleven):
    fake = eleven(
        {
            "/v1/convai/conversation/token": _Reply(403, {}),
            "/v1/convai/conversation/get-signed-url": _Reply(200, {"signed_url": "wss://signed.test/x"}),
        }
    )
    body = client.get(SESSION, params={"manualId": KTM}).json()
    assert body["connectionType"] == "websocket"
    assert body["signedUrl"] == "wss://signed.test/x"
    assert body["auth"] == "signed"
    assert [c[0] for c in fake.calls] == [
        "/v1/convai/conversation/token",
        "/v1/convai/conversation/get-signed-url",
    ]


def test_an_agent_elevenlabs_will_not_open_is_a_readable_502(client, eleven):
    eleven({})
    r = client.get(SESSION, params={"manualId": KTM})
    assert r.status_code == 502
    assert "credential" in r.json()["detail"]


# ---------------------------------------------------------------- binding the manual


def test_the_header_binds_the_manual_and_the_model_cannot_override_it(client):
    """The model asks for the BMW; ElevenLabs' substituted header says KTM. The header wins."""
    r = client.post(
        f"{TOOLS}/read_page",
        json={"manualId": BMW, "page": 1},
        headers={"X-Manual-Id": KTM},
    )
    assert r.status_code == 200
    bmw = client.post(f"{TOOLS}/read_page", json={"page": 1}, headers={"X-Manual-Id": BMW}).json()
    assert r.json()["text"] != bmw["text"]


def test_the_query_string_binds_the_manual_when_there_is_no_header(client):
    r = client.post(f"{TOOLS}/read_page?manualId={KTM}", json={"manualId": BMW, "page": 1})
    assert r.status_code == 200
    direct = client.post("/voice/tools/read_page", json={"manualId": KTM, "page": 1})
    assert r.json() == direct.json()


def test_the_models_own_argument_is_the_last_resort_not_the_first(client):
    r = client.post(f"{TOOLS}/get_spec", json={"manualId": KTM, "name": "tyre pressure"})
    assert r.status_code == 200
    assert isinstance(r.json()["specs"], list)


@pytest.mark.parametrize("placeholder", ["{{manual_id}}", "{manual_id}", ""])
def test_an_unsubstituted_placeholder_is_ignored_rather_than_looked_up(client, placeholder):
    """A platform that does not substitute into the header must fall through to the next source,
    not 404 on a manual literally called '{{manual_id}}'."""
    r = client.post(
        f"{TOOLS}/read_page?manualId={KTM}",
        json={"page": 1},
        headers={"X-Manual-Id": placeholder},
    )
    assert r.status_code == 200
    assert r.json()["page"] == 1


def test_no_manual_anywhere_is_422_not_500(client):
    assert client.post(f"{TOOLS}/read_page", json={"page": 1}).status_code == 422


# ---------------------------------------------------------------- the four tools


def test_every_server_tool_answers_from_the_bound_manual(client):
    payloads = {
        "find_procedure": {"query": "engine oil"},
        "read_page": {"page": 2},
        "get_spec": {"name": "tyre pressure"},
        "list_parts": {},
    }
    for name in SERVER_TOOLS:
        r = client.post(f"{TOOLS}/{name}", json=payloads[name], headers={"X-Manual-Id": KTM})
        assert r.status_code == 200, (name, r.text)
        assert isinstance(r.json(), dict)


def test_tools_accept_the_nested_argument_envelope_a_platform_may_wrap_them_in(client):
    """voice.ToolBody flattens `{"arguments": ...}` — inherited here, asserted here."""
    flat = client.post(f"{TOOLS}/read_page", json={"page": 3}, headers={"X-Manual-Id": KTM}).json()
    nested = client.post(
        f"{TOOLS}/read_page", json={"arguments": {"page": 3}}, headers={"X-Manual-Id": KTM}
    ).json()
    as_string = client.post(
        f"{TOOLS}/read_page", json={"arguments": json.dumps({"page": 3})}, headers={"X-Manual-Id": KTM}
    ).json()
    assert flat == nested == as_string


def test_read_page_chunks_a_long_page_and_says_where_to_resume(client):
    first = client.post(f"{TOOLS}/read_page", json={"page": 1, "offset": 0}, headers={"X-Manual-Id": BMW}).json()
    assert len(first["text"]) <= 1200
    if first["hasMore"]:
        assert first["nextOffset"] > 0


def test_the_shared_secret_guards_these_endpoints_too(client, monkeypatch):
    monkeypatch.setenv("VOICE_TOOL_SECRET", "shh")
    assert client.post(f"{TOOLS}/read_page", json={"page": 1}, headers={"X-Manual-Id": KTM}).status_code == 401
    ok = client.post(
        f"{TOOLS}/read_page", json={"page": 1}, headers={"X-Manual-Id": KTM, "x-voice-secret": "shh"}
    )
    assert ok.status_code == 200


def test_every_tool_call_is_timed_so_latency_is_measured_not_estimated(client):
    client.post(f"{TOOLS}/get_spec", json={"name": "oil"}, headers={"X-Manual-Id": KTM})
    body = client.get("/voice/elevenlabs/timings").json()
    assert body["count"] >= 1
    assert body["p50"] is not None and body["p50"] >= 0
    assert body["calls"][-1]["tool"] == "get_spec"


# ---------------------------------------------------------------- the prompt


@pytest.fixture(scope="module")
def prompt():
    from app import voice_elevenlabs as mod

    return mod.prompt_template()


def test_the_prompt_is_the_deepgram_grounding_policy_not_a_second_one(prompt, client):
    """Substitute this session's own dynamic variables into the ElevenLabs template and you get
    the Deepgram agent's prompt back, character for character.

    That is the whole claim of this integration: ONE grounding policy, two engines. If someone
    edits the policy in voice.py, this keeps holding; if someone forks it, this fails.
    """
    live = client.get("/voice/agent-settings", params={"manualId": KTM}).json()
    deepgram = live["settings"]["agent"]["think"]["prompt"]
    variables = client.get(SESSION, params={"manualId": KTM}).json()["dynamicVariables"]

    filled = prompt
    for name, value in variables.items():
        filled = filled.replace("{{" + name + "}}", value)
    head, _, tail = filled.partition("Two more things about how you are wired here:")
    assert head.strip() == deepgram.strip()
    assert tail  # and the only addition is the ElevenLabs-specific wiring note

    for sentence in (
        "You do not know anything about this motorcycle",
        "NEVER guess, round, convert or recall a value",
        "NEVER tell anyone to visit, consult or contact a dealer",
        "Say the page whenever a figure came off one",
    ):
        assert sentence in prompt
    assert "find_procedure" in prompt and "show_page" in prompt


def test_the_prompt_carries_every_dynamic_variable_the_session_supplies(prompt, client):
    body = client.get(SESSION, params={"manualId": KTM}).json()
    for name in body["dynamicVariables"]:
        if name == "manual_id":
            continue  # bound by the URL and the header, never spoken into the prompt
        assert "{{" + name + "}}" in prompt, name


def test_the_prompt_forbids_translating_a_printed_figure(prompt):
    assert "Speak whatever language the mechanic speaks" in prompt
    assert "never translate a unit or convert a number" in prompt


# ---------------------------------------------------------------- the setup tool


@pytest.fixture(scope="module")
def setup_mod():
    import sys
    from pathlib import Path

    tools_dir = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools_dir))
    import elevenlabs_setup  # noqa: PLC0415

    return elevenlabs_setup


@pytest.fixture
def configs(setup_mod, https_base):
    return {c["name"]: c for c in setup_mod.tool_configs()}


def test_setup_declares_four_webhook_tools_and_exactly_one_client_tool(configs):
    assert sorted(c for c, v in configs.items() if v["type"] == "webhook") == sorted(SERVER_TOOLS)
    client_tools = [c for c, v in configs.items() if v["type"] == "client"]
    assert client_tools == ["show_page"]


def test_the_manual_text_never_travels_through_the_browser(configs):
    """Every tool that returns the manual's words is a SERVER tool pointed at this API."""
    for name in SERVER_TOOLS:
        schema = configs[name]["api_schema"]
        assert schema["url"].startswith(f"{BASE}/voice/elevenlabs/tools/{name}")
        assert schema["method"] == "POST"


def test_the_manual_id_is_bound_three_ways_and_never_by_the_model(configs):
    for name in SERVER_TOOLS:
        schema = configs[name]["api_schema"]
        assert "manualId={{manual_id}}" in schema["url"]
        assert schema["request_headers"]["X-Manual-Id"] == "{{manual_id}}"
        # The model is never given a manualId argument to get wrong.
        assert "manualId" not in schema["request_body_schema"]["properties"]


def test_show_page_runs_immediately_so_the_page_turns_during_the_sentence(configs):
    show = configs["show_page"]
    assert show["execution_mode"] == "immediate"
    assert show["expects_response"] is False
    assert show["parameters"]["required"] == ["page"]


def test_the_agent_body_is_authorised_low_latency_and_deterministic(setup_mod, https_base):
    body = setup_mod.agent_body(["tool_a", "tool_b"])
    agent = body["conversation_config"]["agent"]
    assert agent["prompt"]["tool_ids"] == ["tool_a", "tool_b"]
    assert agent["prompt"]["temperature"] == 0.0
    assert body["conversation_config"]["tts"]["model_id"] == "eleven_flash_v2_5"
    # Without client_tool_call the browser never hears show_page and the page never turns.
    assert "client_tool_call" in body["conversation_config"]["conversation"]["client_events"]
    assert body["platform_settings"]["auth"]["enable_auth"] is True
    assert "{{bike_name}}" in agent["first_message"]


def test_the_secret_rides_in_the_tool_headers_when_one_is_configured(setup_mod, monkeypatch, https_base):
    monkeypatch.setenv("VOICE_TOOL_SECRET", "shh")
    for config in setup_mod.tool_configs():
        if config["type"] == "webhook":
            assert config["api_schema"]["request_headers"]["X-Voice-Secret"] == "shh"


def test_dry_run_prints_valid_json_and_sends_nothing(setup_mod, capsys, https_base):
    setup_mod.dry_run()
    out = capsys.readouterr().out
    assert out.count("POST /v1/convai/tools") == 5
    assert "POST /v1/convai/agents/create" in out
    chunks = out.split("POST ")
    assert len(chunks) == 7  # the PUBLIC_BASE line, five tools, one agent
    for chunk in chunks[1:]:
        json.loads(chunk[chunk.index("{") :].strip())

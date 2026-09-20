"""ElevenLabs Agents Platform — the same four grounded manual tools, a different engine.

Live voice runs on the Deepgram Voice Agent (app/voice.py). This module is the ElevenLabs path:
NOT a re-skin, because the two platforms ground an agent in opposite directions.

  Deepgram  the whole Settings message — prompt, models, tool endpoints — is built per session in
            /voice/agent-settings and pushed down the socket. Nothing persists on their side.
  ElevenLabs the agent is a PERSISTENT object in their workspace, created once by
            api/tools/elevenlabs_setup.py. One static prompt, one static set of tool ids, and the
            per-session facts (which bike, which manual, that manual's table of contents) arrive as
            dynamic variables when the browser opens the session.

So the run-time job here is smaller and sharper than Deepgram's:
  GET /voice/elevenlabs/session   mint a short-lived credential for an authorised agent and hand
                                  the browser the dynamic variables for THIS manual.
  POST /voice/elevenlabs/tools/*  the four grounded tools, seen from ElevenLabs' side.

WHY ITS OWN TOOL ENDPOINTS, when /voice/tools/* already exists.
The one thing that must never be wrong is WHICH BOOK is being read. Deepgram takes the manual id in
the endpoint's query string, which their server owns and the model cannot touch. ElevenLabs can
substitute a dynamic variable into a webhook tool's URL and into its headers, but exactly which of
those substitutions a given account/version performs is not something this repo can verify without
a key. So the id is offered three ways and resolved in order of how hard it is for the model to
lie about it:

    1. X-Manual-Id header   substituted by ElevenLabs from {{manual_id}} — the model never sees it
    2. ?manualId= query     substituted by ElevenLabs from {{manual_id}} — likewise
    3. the request body     the model's own argument — LAST, and only if 1 and 2 are absent

A placeholder that came back unsubstituted (still containing "{{") is treated as absent, so a
platform that does not do one of those substitutions degrades to the next one instead of 404ing on
a manual literally called "{{manual_id}}". The model's own word is the last resort, never the first.

The prompt is not rewritten for ElevenLabs. prompt_template() calls voice._prompt() — the exact
grounding policy the Deepgram agent runs under — with the per-manual facts replaced by ElevenLabs
dynamic-variable placeholders, so the two engines cannot drift apart. One policy, two engines.

Docs: elevenlabs.io/docs/agents-platform (agents, server/client tools, signed URLs, WebRTC tokens).
"""

import time
from collections import deque
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query

from . import voice
from .config import settings

router = APIRouter(prefix="/voice/elevenlabs", tags=["voice"])

ELEVEN = "https://api.elevenlabs.io"
# Ultra-low latency, ~75 ms to the first byte of audio, half the price per character of the
# multilingual model. A mechanic wants the figure, not a performance.
TTS_MODEL = "eleven_flash_v2_5"
# One of the enum values the Agents Platform lists for prompt.llm. Chosen the way voice.py chose
# gpt-4.1: strong tool-calling, no reasoning pre-roll in front of the first word.
LLM = "gpt-4.1"
HTTP_TIMEOUT = 15

# The tail added to the shared grounding policy. Everything above it in the prompt is voice.py's.
ELEVEN_TAIL = """\
Two more things about how you are wired here:
- You never supply a manual id to a function. The book is already bound to this session before you
  are reached; the functions know which one it is. Send only the argument each one asks for.
- show_page runs on the mechanic's screen the moment you call it, not after you stop talking. Call
  it BEFORE you start reading a page out loud, so the page is in front of them while you read.
- Speak whatever language the mechanic speaks to you. Your own words translate; the manual's do
  not. A printed figure, a printed part designation and a page number are read as the manual prints
  them, in the manual's own language, and you never translate a unit or convert a number."""


# ---------------------------------------------------------------- the prompt


def prompt_template() -> str:
    """The Deepgram prompt with the per-manual facts swapped for ElevenLabs dynamic variables.

    voice._prompt() only ever reads `.title` and `.pages` off the manual, so a two-field stand-in
    is enough to render it — and the policy itself (call a function first, never guess a figure,
    never send anyone to a dealer, say the page) is imported, not retyped.
    """
    shim = SimpleNamespace(title="{{manual_title}}", pages="{{manual_pages}}")
    return f"{voice._prompt(shim, '{{bike_name}}', '{{manual_digest}}')}\n\n{ELEVEN_TAIL}"


def dynamic_variables(manual, bike: str) -> dict:
    """What this session is about. ElevenLabs substitutes these into the prompt, the tool URLs and
    the tool headers; the agent object itself stays the same for every bike in the catalogue."""
    return {
        "bike_name": bike,
        "manual_id": manual.id,
        "manual_title": manual.title,
        "manual_pages": str(manual.pages),
        "manual_digest": voice._digest(manual),
    }


# ---------------------------------------------------------------- the session


@router.get("/session")
def session(manualId: str, bikeId: str | None = None):
    """Everything the browser needs to open one conversation, and nothing it could forge.

    An agent created with enable_auth (what tools/elevenlabs_setup.py does) refuses a bare agent id,
    so a credential is minted here with the account key: a WebRTC conversation token first, because
    WebRTC carries the audio on its own congestion-controlled transport instead of a TCP socket that
    head-of-line blocks under a workshop's wifi, and a signed WebSocket URL as the fallback.

    With no account key on the box the response still describes the session; a PUBLIC agent then
    connects on the agent id alone, which is how this path comes up before Emil creates a key.
    """
    agent_id = settings.elevenlabs_agent_id
    if not agent_id:
        raise HTTPException(501, "no ELEVENLABS_AGENT_ID; run api/tools/elevenlabs_setup.py first")
    manual = voice._manual(manualId)
    bike = voice._label(manual, bikeId)
    payload = {
        "agentId": agent_id,
        "manualId": manual.id,
        "bike": bike,
        "dynamicVariables": dynamic_variables(manual, bike),
    }

    key = settings.elevenlabs_api_key
    if not key:
        # A public agent needs no credential. Say so plainly rather than 502-ing: the browser can
        # still open the session, and the writeup can still be honest about which mode it ran in.
        return {**payload, "connectionType": "webrtc", "auth": "public"}

    with httpx.Client(base_url=ELEVEN, headers={"xi-api-key": key}, timeout=HTTP_TIMEOUT) as http:
        token = http.get("/v1/convai/conversation/token", params={"agent_id": agent_id})
        if token.status_code < 400:
            body = token.json()
            if body.get("token"):
                return {
                    **payload,
                    "connectionType": "webrtc",
                    "auth": "token",
                    "conversationToken": body["token"],
                    "conversationId": body.get("conversation_id"),
                }
        signed = http.get("/v1/convai/conversation/get-signed-url", params={"agent_id": agent_id})
        if signed.status_code < 400:
            body = signed.json()
            if body.get("signed_url"):
                return {**payload, "connectionType": "websocket", "auth": "signed", "signedUrl": body["signed_url"]}
    raise HTTPException(502, "elevenlabs refused a conversation credential for this agent")


# ---------------------------------------------------------------- the four grounded tools

tools = APIRouter(prefix="/tools", dependencies=[Depends(voice._guard)])

# Every tool call this process has served, newest last. Not analytics: the one number this
# integration can be judged on is how long the agent waits between asking the manual something and
# being able to speak, and that number is measured here rather than estimated in a slide.
_TIMINGS: deque[dict] = deque(maxlen=64)


@contextmanager
def _timed(name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        _TIMINGS.append({"tool": name, "ms": round((time.perf_counter() - started) * 1000, 1), "at": time.time()})


def _clean(value: str | None) -> str:
    """A manual id, or "" for anything that is not one — an unsubstituted {{placeholder}} included."""
    text = str(value or "").strip()
    return "" if (not text or "{" in text or "}" in text) else text


def _bind(body: voice.ToolBody, from_query: str | None, from_header: str | None) -> voice.ToolBody:
    """Header, then query, then the model's own argument. See the module docstring."""
    chosen = _clean(from_header) or _clean(from_query) or _clean(body.manualId)
    if not chosen:
        raise HTTPException(422, "no manual bound to this session")
    body.manualId = chosen
    return body


@tools.post("/find_procedure")
def find_procedure(
    body: voice.FindBody,
    manualId: str | None = Query(default=None),
    x_manual_id: str | None = Header(default=None),
):
    with _timed("find_procedure"):
        return voice.find_procedure(_bind(body, manualId, x_manual_id), None)


@tools.post("/read_page")
def read_page(
    body: voice.PageBody,
    manualId: str | None = Query(default=None),
    x_manual_id: str | None = Header(default=None),
):
    with _timed("read_page"):
        return voice.read_page(_bind(body, manualId, x_manual_id), None)


@tools.post("/get_spec")
def get_spec(
    body: voice.SpecBody,
    manualId: str | None = Query(default=None),
    x_manual_id: str | None = Header(default=None),
):
    with _timed("get_spec"):
        return voice.get_spec(_bind(body, manualId, x_manual_id), None)


@tools.post("/list_parts")
def list_parts(
    body: voice.PartsBody,
    manualId: str | None = Query(default=None),
    x_manual_id: str | None = Header(default=None),
):
    with _timed("list_parts"):
        return voice.list_parts(_bind(body, manualId, x_manual_id), None)


@router.get("/timings")
def timings():
    """The tool leg of the latency budget, measured, newest last.

    The rest of the budget belongs to ElevenLabs: Scribe v2 realtime partials ~150 ms, the LLM's
    first token, eleven_flash_v2_5 ~75 ms to first audio. This endpoint is the only part of it we
    are allowed to claim as our own measurement.
    """
    rows = list(_TIMINGS)
    values = sorted(r["ms"] for r in rows)
    return {
        "calls": rows,
        "count": len(values),
        "p50": values[len(values) // 2] if values else None,
        "p95": values[max(0, int(len(values) * 0.95) - 1)] if values else None,
    }


router.include_router(tools)

"""Voice. Deepgram Voice Agent settings + the webhook tools any agent may call + temporary keys.

The agent never paraphrases: every tool returns the manual's own words, with the page they are printed on.

DEEPGRAM VOICE AGENT (docs: developers.deepgram.com/reference/voice-agent/voice-agent).
GET /voice/agent-settings builds the whole `Settings` message on the server, so the browser holds no
prompt, no model name and no tool wiring — it opens wss://agent.deepgram.com/v1/agent/converse with a
short-lived key and forwards what this endpoint handed it.

Two kinds of function in that Settings message:
  server-side  find_procedure / read_page / get_spec / list_parts carry an `endpoint` object, so
               DEEPGRAM calls this API directly and the manual's text never travels through the
               browser. The manual id rides in the endpoint's query string rather than in the
               function's parameters: an agent that had to say which manual it is reading could say
               the wrong one, and every answer here has to come out of ONE book.
  client-side  show_page has no `endpoint`; it arrives at the browser as a FunctionCallRequest with
               client_side:true and moves the reader.

Deepgram POSTs the model's arguments to the endpoint; the exact envelope is not pinned down in the
docs, so _flatten() below accepts the three shapes it could take (flat, nested, nested-as-JSON-string)
and the JSON this API already returns goes back to the model as the function result.
"""

import json
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, model_validator

from . import ask as ask_mod
from . import ingest as ingest_mod
from .config import settings
from .models import Manual, OutlineNode
from .store import get_store

router = APIRouter(prefix="/voice", tags=["voice"])

CHUNK = 1200
DEEPGRAM = "https://api.deepgram.com"
TOKEN_TTL = 600

AGENT_WS = "wss://agent.deepgram.com/v1/agent/converse"
AGENT_RATE = 24000

# Flux (listen v2) has end-of-turn detection inside the model instead of a silence timer, and
# `eager_eot_threshold` lets it start the LLM before the rider has finished the sentence, throwing
# the speculative turn away on TurnResumed. Measured against nova-3 on "how much engine oil does
# it take?", spoken into the socket at real speed: 1.35 s to the first byte of the answer's audio
# against 1.97 s. eot_timeout_ms is the silence fallback - 2 s, not the 5 s default, because a
# mechanic's question ends when it ends.
LISTEN = {
    "type": "deepgram",
    "version": "v2",
    "model": "flux-general-en",
    "eot_threshold": 0.7,
    "eager_eot_threshold": 0.4,
    "eot_timeout_ms": 2000,
}
# Aura-2. Deepgram describes asteria as "clear, confident, knowledgeable" and thalia as
# "energetic, enthusiastic"; this assistant reads torque figures to someone holding a spanner,
# so knowledgeable wins. Measured within noise of thalia and a second faster than luna.
SPEAK_MODEL = "aura-2-asteria-en"
# One of the models Deepgram lists for think.provider.type "open_ai", and NOT a reasoning one.
# Deepgram drives think through /v1/chat/completions with reasoning_effort set, which OpenAI
# rejects outright the moment function tools are attached ("Function tools with reasoning_effort
# are not supported ... use /v1/responses or set reasoning_effort to 'none'") - so the app's own
# gpt-5.6-* models close the socket with FAILED_TO_THINK here.
# Of what is left, gpt-4.1 is both the strongest and, measured on the KTM, the fastest: it picks
# the one right function and answers in a sentence, where the mini and 4o take an extra hop and
# pad the reply. 1.35 s to first audio against 2.37 s (mini) and 1.83 s (4o).
THINK_MODEL = os.getenv("MODEL_VOICE", "gpt-4.1")
DIGEST_CHARS = 1500


def _guard(x_voice_secret: str | None = Header(default=None)) -> None:
    want = os.getenv("VOICE_TOOL_SECRET")
    if want and x_voice_secret != want:
        raise HTTPException(401)


tools = APIRouter(prefix="/tools", dependencies=[Depends(_guard)])

# Envelopes a function-call payload might arrive in, innermost value first.
_NESTS = ("arguments", "parameters", "input", "args")


class ToolBody(BaseModel):
    # Optional because Deepgram sends only the model's own arguments; the manual id comes from the
    # endpoint URL's query string instead (see _pick below).
    manualId: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, raw):
        """Accept the model's arguments flat, nested under a key, or nested as a JSON string."""
        if not isinstance(raw, dict):
            return raw
        for key in _NESTS:
            inner = raw.get(key)
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    continue
            if isinstance(inner, dict):
                merged = {k: v for k, v in raw.items() if k != key}
                merged.update(inner)
                return merged
        return raw


class FindBody(ToolBody):
    query: str


class PageBody(ToolBody):
    page: int
    offset: int = 0


class SpecBody(ToolBody):
    name: str


class PartsBody(ToolBody):
    sectionId: str | None = None


def _pick(body: ToolBody, from_query: str | None) -> str:
    """The body wins (our own callers), the endpoint's query string stands in (Deepgram's)."""
    return str(body.manualId or from_query or "")


def _manual(manual_id: str) -> Manual:
    m = get_store().manual(manual_id)
    if not m:
        raise HTTPException(404, "unknown manual")
    return m


def _page_text(manual_id: str, page: int) -> str:
    for p in get_store().pages(manual_id):
        if p.page == page:
            return p.text
    path = ingest_mod.pdf_path(manual_id)
    if path.exists():
        import pymupdf

        with pymupdf.open(path) as doc:
            if 1 <= page <= doc.page_count:
                return doc[page - 1].get_text()
    raise HTTPException(404, "no such page")


def _chunk(text: str, offset: int) -> tuple[str, bool, int]:
    rest = text[max(0, offset) :]
    if len(rest) <= CHUNK:
        return rest, False, offset + len(rest)
    cut = rest.rfind("\n", 0, CHUNK)
    if cut < CHUNK // 2:
        cut = rest.rfind(" ", 0, CHUNK)
    if cut < CHUNK // 2:
        cut = CHUNK
    return rest[:cut], True, offset + cut


@router.get("/config")
def config():
    return {
        "elevenlabsAgentId": settings.elevenlabs_agent_id,
        "deepgram": bool(settings.deepgram_api_key),
    }


_project: str | None = None


@router.post("/deepgram-token")
def deepgram_token():
    """A short-lived credential the browser may hold, and the subprotocol to send it with.

    A browser WebSocket has no headers, so Deepgram is authenticated with the
    Sec-WebSocket-Protocol pair `[scheme, credential]` — `new WebSocket(url, [scheme, key])`,
    which is what Deepgram's own browser-agent component does, for wss://api.deepgram.com/v2/listen
    and wss://agent.deepgram.com/v1/agent/converse alike. `scheme` travels with the credential so
    the browser never has to guess which kind it got.

    Two ways to mint one, and which of them an account can use depends on its key's scopes:
      token   a project key scoped to usage:write, ten minutes (needs keys:write)
      bearer  the JWT from /v1/auth/grant, thirty seconds, long enough for the handshake
    The project key is tried first because it is what this app already ships to the browser; the
    grant is the fallback. A 502 here means the account key can do NEITHER, and the fix is on the
    Deepgram console, not in this file: give the key keys:write on the project.
    """
    global _project
    key = settings.deepgram_api_key
    if not key:
        raise HTTPException(501, "no deepgram key")
    with httpx.Client(base_url=DEEPGRAM, headers={"Authorization": f"Token {key}"}, timeout=15) as http:
        if _project is None:
            projects = http.get("/v1/projects")
            listed = (projects.json().get("projects") or []) if projects.status_code < 400 else []
            _project = listed[0]["project_id"] if listed else ""
        if _project:
            made = http.post(
                f"/v1/projects/{_project}/keys",
                json={
                    "comment": "trustthemanual browser",
                    "scopes": ["usage:write"],
                    "time_to_live_in_seconds": TOKEN_TTL,
                },
            )
            if made.status_code < 400:
                return {"key": made.json()["key"], "expiresIn": TOKEN_TTL, "scheme": "token"}
        granted = http.post("/v1/auth/grant", json={"ttl_seconds": 30})
        if granted.status_code < 400:
            body = granted.json()
            return {
                "key": body["access_token"],
                "expiresIn": int(body.get("expires_in") or 30),
                "scheme": "bearer",
            }
        raise HTTPException(502, "deepgram key failed: the account key needs keys:write on the project")


# ---------------------------------------------------------------- the voice agent


def _label(manual: Manual, bike_id: str | None) -> str:
    """"KTM 390 Duke 2024" — the bike the agent is standing in front of."""
    store = get_store()
    rec = store.bike(bike_id) if bike_id else None
    if rec is None:
        for candidate in manual.bikeIds:
            rec = store.bike(candidate)
            if rec is not None:
                break
    if rec is None:
        return manual.title
    return " ".join(str(x) for x in (rec.make, rec.model, rec.year) if x not in (None, ""))


def _spans(nodes: list[OutlineNode], last: int) -> list[tuple[str, int, int]]:
    """Top-level outline entries as (title, first page, last page). A chapter runs to the page
    before the next one starts, which is the only end the outline actually prints."""
    out: list[tuple[str, int, int]] = []
    for i, node in enumerate(nodes):
        start = int(node.page or 0)
        if start <= 0:
            continue
        nxt = next((int(n.page) for n in nodes[i + 1 :] if int(n.page or 0) > start), None)
        end = (nxt - 1) if nxt else last
        out.append((" ".join(str(node.title or "").split()), start, max(start, end)))
    return out


def _digest(manual: Manual) -> str:
    """What this book contains, in under DIGEST_CHARS characters.

    The agent reads it before it calls anything, so it can say "that is not in this manual" without
    a round trip, and aim find_procedure at a chapter that exists. Outline first (the manual's own
    contents page); a manual with no outline falls back to the indexed sections' chapters.
    """
    rows = _spans(manual.outline or [], manual.pages)
    if not rows:
        seen: dict[str, list[int]] = {}
        for s in manual.sections:
            span = seen.setdefault(" ".join(str(s.chapter or s.title).split()), [s.pageStart, s.pageEnd])
            span[0] = min(span[0], s.pageStart)
            span[1] = max(span[1], s.pageEnd)
        rows = [(title, span[0], span[1]) for title, span in seen.items()]
        rows.sort(key=lambda r: r[1])

    lines: list[str] = []
    used = 0
    for title, start, end in rows:
        if not title:
            continue
        line = f"{title} (p. {start}-{end})" if end > start else f"{title} (p. {start})"
        if used + len(line) + 1 > DIGEST_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _prompt(manual: Manual, bike: str, digest: str) -> str:
    return f"""You are the voice of Mechanica, answering out loud for a professional mechanic who has
this motorcycle on the lift and dirty hands. You speak; you are never read.

THE BIKE: {bike}
THE MANUAL: {manual.title} ({manual.pages} printed pages)
WHAT THIS MANUAL CONTAINS:
{digest}

THE ONE RULE ABOVE ALL OTHERS. You do not know anything about this motorcycle. Everything you
think you remember about a KTM, a BMW or any other bike is wrong here and may not be spoken. Call
a function FIRST, every single time, before the first word of every answer about this machine, and
say only what its result printed. You have never answered a question here without calling a
function first and you never will. A wrong torque figure or a wrong oil quantity breaks a
motorcycle and hurts the person who trusted you; recalling one from memory is the single worst
thing you can do.

How you answer:
- One or two sentences. Never three. Plain spoken English, the way one mechanic tells another.
- Start with the answer. No filler, ever: never open with "sure", "of course", "great question",
  "let me check", "one moment", "I found that", "according to the manual". The first word out of
  your mouth is part of the answer.
- No bullet points, no numbered lists, no markdown, no headers, no asterisks, no emoji. Nothing that
  only works on a screen. Say "four point five newton metres", not "4.5 Nm".
- Answer ONLY from what a function gave you back. That text is the manual's own words. If you have
  not called a function for this question yet, call one first and wait for it.
- NEVER guess, round, convert or recall a value. A torque, a capacity, a pressure, a clearance, a
  gap, an interval, a fuse rating or a part number may only leave your mouth if a function result
  you have already received printed it, word for word. If no result printed the figure asked for,
  say the manual does not print it - do not supply one from anywhere else.
- Say the page whenever a figure came off one: "page 114 says ...". The rider is holding the book.
- Owner manuals name a hundred jobs and print the procedure for twenty. When a function result
  shows this manual naming the job but printing no steps, say so in four words - "the manual
  doesn't print the steps" - then give the ordinary workshop procedure, and say every figure the
  manual DOES print for that job with its page. Mark the general part as general: "the usual way
  is ...", "normally you ...". This licence covers STEPS AND ORDER ONLY. It never covers a number:
  general steps carry no figures, only the manual's own pages do.
- NEVER tell anyone to visit, consult or contact a dealer, a retailer, an authorised workshop, a
  specialist or a service centre. They ARE the workshop. Owner manuals pad every job with that
  sentence; it is the one thing you must not pass on. Answer the question instead.
- If this manual says nothing about it at all, say so in one sentence and offer to open the closest
  page you can see in the contents above. Never carry a figure over from another motorcycle.
- No safety boilerplate, no disclaimers, no "if you are unsure", no offers to help further.

Your functions:
- find_procedure(query): which chapters and pages of THIS manual cover something. Start here.
- read_page(page, offset): the printed text of one page, verbatim. Read this before you quote steps.
- get_spec(name): the printed figures - torques, capacities, pressures, clearances, intervals.
- list_parts(sectionId): the parts this manual names, with the page they are printed on.
- show_page(page): put a page on the rider's screen. Call it whenever you name a page worth reading."""


def _endpoint(name: str, manual_id: str) -> dict:
    """The manual id rides in the URL, not in the model's arguments: the agent cannot misname the
    book it is reading, and the manual's text never passes through the browser."""
    url = f"{settings.public_base}/voice/tools/{name}?manualId={quote(manual_id, safe='')}"
    if not url.startswith("https://"):
        # Deepgram calls these from its own servers and refuses anything but https/wss, so an
        # http PUBLIC_BASE (the local default) would close the socket with "INVALID_SETTINGS"
        # seconds after the rider pressed VOICE. Say it here instead, where it is readable.
        raise HTTPException(503, f"voice needs an https PUBLIC_BASE; this API advertises {settings.public_base}")
    out: dict = {"url": url, "method": "post"}
    secret = os.getenv("VOICE_TOOL_SECRET")
    if secret:
        out["headers"] = {"x-voice-secret": secret}
    return out


def _functions(manual_id: str, pages: int) -> list[dict]:
    return [
        {
            "name": "find_procedure",
            "description": "Find which chapters and printed pages of this manual cover a job or a topic. Call this first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What the rider asked, in their own words."}
                },
                "required": ["query"],
            },
            "endpoint": _endpoint("find_procedure", manual_id),
        },
        {
            "name": "read_page",
            "description": "The verbatim printed text of one page of this manual. Use it before quoting any step or figure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": f"Printed page number, 1 to {pages}."},
                    "offset": {"type": "integer", "description": "Characters already read; use nextOffset to continue a long page."},
                },
                "required": ["page"],
            },
            "endpoint": _endpoint("read_page", manual_id),
        },
        {
            "name": "get_spec",
            "description": "The figures this manual prints - torques, capacities, pressures, clearances, intervals - each with its page and the sentence it came from.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "The specification asked for, e.g. 'tyre pressure'."}},
                "required": ["name"],
            },
            "endpoint": _endpoint("get_spec", manual_id),
        },
        {
            "name": "list_parts",
            "description": "The parts this manual names, with the page they are printed on.",
            "parameters": {
                "type": "object",
                "properties": {"sectionId": {"type": "string", "description": "Narrow to one section id from find_procedure."}},
            },
            "endpoint": _endpoint("list_parts", manual_id),
        },
        {
            # No endpoint: this one comes back to the browser as client_side true and moves the reader.
            "name": "show_page",
            "description": "Open a printed page of this manual on the rider's screen.",
            "parameters": {
                "type": "object",
                "properties": {"page": {"type": "integer", "description": f"Printed page number, 1 to {pages}."}},
                "required": ["page"],
            },
        },
    ]


@router.get("/agent-settings")
def agent_settings(manualId: str, bikeId: str | None = None):
    """The whole Deepgram `Settings` message for one manual, plus the socket to send it down.

    The browser gets no prompt to edit, no model name to swap and no tool URL to forge: it opens the
    socket, forwards `settings` unchanged, and handles exactly one function itself (show_page).
    """
    manual = _manual(manualId)
    bike = _label(manual, bikeId)
    digest = _digest(manual)
    return {
        "url": AGENT_WS,
        "sampleRate": AGENT_RATE,
        "manualId": manual.id,
        "bike": bike,
        "settings": {
            "type": "Settings",
            "audio": {
                "input": {"encoding": "linear16", "sample_rate": AGENT_RATE},
                "output": {"encoding": "linear16", "sample_rate": AGENT_RATE, "container": "none"},
            },
            "agent": {
                "language": "en",
                "listen": {"provider": dict(LISTEN)},
                "think": {
                    "provider": {"type": "open_ai", "model": THINK_MODEL},
                    "prompt": _prompt(manual, bike, digest),
                    "functions": _functions(manual.id, manual.pages),
                },
                "speak": {"provider": {"type": "deepgram", "model": SPEAK_MODEL}},
                "greeting": f"I see you're looking at the {bike}.",
            },
        },
    }


@tools.post("/find_procedure")
def find_procedure(body: FindBody, manualId: str | None = Query(default=None)):
    manual_id = _pick(body, manualId)
    _manual(manual_id)
    try:
        answer = ask_mod.answer(manual_id, body.query)
    except NotImplementedError:
        raise HTTPException(501, "search unavailable") from None
    sections = [
        {
            "id": m.section.id,
            "title": m.section.title,
            "chapter": m.section.chapter,
            "pageStart": m.section.pageStart,
            "pageEnd": m.section.pageEnd,
        }
        for m in answer.matches
    ]
    return {"sections": sections, "firstPage": sections[0]["pageStart"] if sections else 0}


@tools.post("/read_page")
def read_page(body: PageBody, manualId: str | None = Query(default=None)):
    manual_id = _pick(body, manualId)
    _manual(manual_id)
    text, has_more, next_offset = _chunk(_page_text(manual_id, body.page), body.offset)
    return {"page": body.page, "text": text, "hasMore": has_more, "nextOffset": next_offset}


@tools.post("/get_spec")
def get_spec(body: SpecBody, manualId: str | None = Query(default=None)):
    manual_id = _pick(body, manualId)
    _manual(manual_id)
    needle = body.name.strip().lower()
    hits = [s for s in get_store().specs(manual_id) if needle and (needle in s.name.lower() or s.name.lower() in needle)]
    if not hits:
        words = [w for w in needle.split() if len(w) > 2]
        hits = [s for s in get_store().specs(manual_id) if any(w in s.name.lower() for w in words)]
    return {
        "specs": [
            {"name": s.name, "value": s.value, "unit": s.unit, "page": s.page, "quote": s.quote, "sectionId": s.sectionId}
            for s in hits[:8]
        ]
    }


@tools.post("/list_parts")
def list_parts(body: PartsBody, manualId: str | None = Query(default=None)):
    m = _manual(_pick(body, manualId))
    by_id = {p.id: p for p in m.parts}
    section = next((s for s in m.sections if s.id == body.sectionId), None)
    chosen = [by_id[i] for i in (section.partIds or []) if i in by_id] if section else m.parts
    return {
        "parts": [
            {
                "name": p.name,
                "spec": p.spec,
                "page": p.page,
                "oem": p.oem,
                "shop": p.links[0].shop if p.links else None,
                "url": p.links[0].url if p.links else None,
            }
            for p in chosen[:12]
        ]
    }


router.include_router(tools)

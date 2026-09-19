"""Voice. ElevenLabs Agents webhook tools + Deepgram temporary keys.

The agent never paraphrases: every tool returns the manual's own words, with the page they are printed on.
"""

import os

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from . import ask as ask_mod
from . import ingest as ingest_mod
from .config import settings
from .models import Manual
from .store import get_store

router = APIRouter(prefix="/voice", tags=["voice"])

CHUNK = 1200
DEEPGRAM = "https://api.deepgram.com"
TOKEN_TTL = 600


def _guard(x_voice_secret: str | None = Header(default=None)) -> None:
    want = os.getenv("VOICE_TOOL_SECRET")
    if want and x_voice_secret != want:
        raise HTTPException(401)


tools = APIRouter(prefix="/tools", dependencies=[Depends(_guard)])


class ToolBody(BaseModel):
    manualId: str


class FindBody(ToolBody):
    query: str


class PageBody(ToolBody):
    page: int
    offset: int = 0


class SpecBody(ToolBody):
    name: str


class PartsBody(ToolBody):
    sectionId: str | None = None


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
    """Short-lived usage:write key.

    The browser sends it as the `token` Sec-WebSocket-Protocol pair, the only documented
    browser auth for wss://api.deepgram.com/v2/listen. The JWT from /v1/auth/grant is not
    accepted in that subprotocol, so a scoped project key is minted instead.
    """
    global _project
    key = settings.deepgram_api_key
    if not key:
        raise HTTPException(501, "no deepgram key")
    with httpx.Client(base_url=DEEPGRAM, headers={"Authorization": f"Token {key}"}, timeout=15) as http:
        if not _project:
            projects = http.get("/v1/projects")
            if projects.status_code >= 400:
                raise HTTPException(502, "deepgram projects failed")
            listed = projects.json().get("projects") or []
            if not listed:
                raise HTTPException(502, "no deepgram project")
            _project = listed[0]["project_id"]
        made = http.post(
            f"/v1/projects/{_project}/keys",
            json={
                "comment": "trustthemanual browser",
                "scopes": ["usage:write"],
                "time_to_live_in_seconds": TOKEN_TTL,
            },
        )
        if made.status_code >= 400:
            raise HTTPException(502, "deepgram key failed")
        return {"key": made.json()["key"], "expiresIn": TOKEN_TTL}


@tools.post("/find_procedure")
def find_procedure(body: FindBody):
    _manual(body.manualId)
    try:
        answer = ask_mod.answer(body.manualId, body.query)
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
def read_page(body: PageBody):
    _manual(body.manualId)
    text, has_more, next_offset = _chunk(_page_text(body.manualId, body.page), body.offset)
    return {"page": body.page, "text": text, "hasMore": has_more, "nextOffset": next_offset}


@tools.post("/get_spec")
def get_spec(body: SpecBody):
    _manual(body.manualId)
    needle = body.name.strip().lower()
    hits = [s for s in get_store().specs(body.manualId) if needle and (needle in s.name.lower() or s.name.lower() in needle)]
    if not hits:
        words = [w for w in needle.split() if len(w) > 2]
        hits = [s for s in get_store().specs(body.manualId) if any(w in s.name.lower() for w in words)]
    return {
        "specs": [
            {"name": s.name, "value": s.value, "unit": s.unit, "page": s.page, "quote": s.quote, "sectionId": s.sectionId}
            for s in hits[:8]
        ]
    }


@tools.post("/list_parts")
def list_parts(body: PartsBody):
    m = _manual(body.manualId)
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

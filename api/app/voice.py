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
import re
import threading
from itertools import zip_longest
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
# Aura-2, and this one was auditioned rather than chosen off the adjectives. "Most natural for a
# workshop" is not a taste question when the room has an impact wrench in it: it is whether the
# sentence survives the noise. Each candidate spoke the six lines this agent actually says (a page
# and a torque, a tyre pressure, an oil grade, the acknowledgement, a general procedure), the same
# synthetic shop noise was mixed in at 3 dB and 0 dB SNR, and nova-3 transcribed it back. WER
# against what we asked for, plus the pace it read at:
#
#   voice      pace       clean   3 dB    0 dB
#   asteria    2.50 w/s    8.5%    8.5%   13.6%   <- keeps it
#   orpheus    2.94 w/s   11.9%   16.9%   18.6%
#   arcas      2.78 w/s   11.9%   22.0%   23.7%
#   harmonia   3.17 w/s   25.4%   18.6%   22.0%
#
# Deepgram files asteria under "advertising" and orpheus under "customer service", which is why
# orpheus was the favourite going in. It lost on the only thing that matters here: at 3 dB it read
# "forty five newton metres" back as "forty five MILLIMETERS", and so did arcas at both levels. A
# torque that arrives as a length is the one mistake this product cannot make. asteria is also the
# slowest of the four, which is the right direction for a workshop - `speed` is left at its default
# because aura-2 would not go below it (0.9 shaved 0.08 s off a 5.12 s line) and 1.15 only made it
# quicker, which nobody here wants.
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


def _bike(manual: Manual, bike_id: str | None):
    """The registry row for the bike on the lift, or the manual's own first bike."""
    store = get_store()
    rec = store.bike(bike_id) if bike_id else None
    if rec is None:
        for candidate in manual.bikeIds:
            rec = store.bike(candidate)
            if rec is not None:
                break
    return rec


def _label(manual: Manual, rec) -> str:
    """"KTM 390 Duke 2024" — the bike the agent is standing in front of."""
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


# ---------------------------------------------------------------- keyterm prompting
#
# `agent.listen.provider.keyterms` is the Voice Agent's own spelling of keyterm prompting
# (developers.deepgram.com/docs/configure-voice-agent, same feature as the repeated `keyterm=`
# query parameter on wss://api.deepgram.com/v2/listen). Flux and nova-3 take it; nova-2 does not.
# Deepgram caps it at 100 terms / 500 tokens per request and asks for a multi-word phrase as one
# array element, not word by word.
#
# A workshop is the worst room a transcriber ever works in, and the words a mechanic says there are
# exactly the ones a general model has no reason to expect: "swingarm pivot", "wheel spindle",
# "preload adjuster", "DOT 4", "telltale", "CVT". They are not guesses — the manual on screen has
# already been indexed, so its part names, its printed spec names, its section headings and the
# rider phrasings each section was indexed under are all on this server. Pick the bike and the
# transcriber is primed with that bike's vocabulary before the first word is spoken.

KEYTERM_MAX = 100
# Deepgram's ceiling is 500 tokens; an English term here runs about 1.4 tokens per word, so a
# character budget well under that is the cheap way to stay inside it without a tokenizer.
KEYTERM_CHARS = 1500
# Where the manual's own vocabulary stops and the standard catalogue starts.
CATALOGUE_FROM = 900
KEYTERM_WORDS = 5

# Manual headings are instructions ("Checking the engine oil level"); the term is the noun phrase.
_VERB = re.compile(
    r"^(?:check(?:ing)?|chang(?:e|ing)|adjust(?:ing)?|clean(?:ing)?|remov(?:e|ing)|install(?:ing)?|"
    r"mount(?:ing)?|replac(?:e|ing)|inspect(?:ing)?|add(?:ing)?|top(?:ping)? up|set(?:ting)?|"
    r"charg(?:e|ing)|drain(?:ing)?|bleed(?:ing)?|lubricat(?:e|ing)|servic(?:e|ing)|fill(?:ing)?|"
    r"test(?:ing)?|measur(?:e|ing)|read(?:ing)?|prepar(?:e|ing)|align(?:ing)?|tighten(?:ing)?)"
    r"\s+(?:that\s+)?(?:the\s+)?",
    re.I,
)
_PAREN = re.compile(r"\s*\([^)]*\)")
_TRIM = re.compile(r"^(?:the\s+)?[\s\-–—:,.]*|[\s\-–—:,.]+$")
# A spaced slash is a printed either/or ("DOT 4 / DOT 5.1"); a tight one is part of the word
# ("R 12 G/S", "110/70", "USA/CA") and cutting there would rename the bike.
_EITHER_OR = re.compile(r"\s+/\s+")
# A heading fragment, not a term: "with enduro package", "for the front wheel".
_LEADS = re.compile(r"^(?:with|without|for|from|and|or|per|at|on|in|to|of|when|as)\b", re.I)


def _term(raw: str) -> str:
    """One keyterm out of one piece of manual vocabulary, or "" when it is not a term.

    "Engine oil (SAE 15W/50)" -> "Engine oil"; "Nut, rear wheel spindle" -> "rear wheel spindle Nut"
    (the manual's index inverts the head noun, a mechanic does not); "Checking the chain tension"
    -> "chain tension"; "Brake fluid DOT 4 / DOT 5.1" -> "Brake fluid DOT 4", because a slash is a
    printed either/or and nobody says it out loud. Case is kept: KTM, DOT and SAE are read back as
    printed. Anything still longer than a spoken term - a whole heading, a sentence of rider slang
    - is dropped rather than truncated: half a phrase primes the transcriber for the wrong words.
    """
    text = " ".join(_PAREN.sub("", str(raw or "")).split())
    text = _EITHER_OR.split(text)[0]
    head, _, tail = text.partition(",")
    # Index order ("Nut, rear wheel spindle"), not a second clause: a one- or two-word head only.
    if tail.strip() and 1 <= len(head.split()) <= 2 and len(text.split()) <= KEYTERM_WORDS + 1:
        text = f"{tail.strip()} {head.strip()}"
    text = _TRIM.sub("", _VERB.sub("", text)).replace(",", " ")
    words = " ".join(text.split()).split()
    text = " ".join(words)
    if not words or len(words) > KEYTERM_WORDS or len(text) < 3 or _LEADS.match(text):
        return ""
    # A term is words and figures, not punctuation a transcriber would never hear, and not the
    # loose letters a PDF text layer leaves behind ("g p y g Specification").
    if not any(w[:1].isalpha() for w in words):
        return ""
    if sum(1 for w in words if len(w) == 1 and w.isalpha()) > 1:
        return ""
    return text


def _fill(
    sources: list[str], out: list[str], seen: set[str], used: int, budget: int, covered: set[str] | None = None
) -> int:
    """Append the terms of `sources` that are new, up to `budget` characters. Returns the total.

    `covered` is the vocabulary already primed: a term made only of words that are all in it is
    skipped, so the second tier spends its slots on words the manual never printed ("swingarm
    pivot", "monoshock", "cvt") instead of a third way of saying "oil filter".
    """
    for raw in sources:
        if len(out) >= KEYTERM_MAX:
            break
        term = _term(raw)
        low = term.lower()
        if not term or low in seen:
            continue
        if covered is not None and all(w in covered for w in low.split()):
            continue
        if used + len(term) + 1 > budget:
            break
        seen.add(low)
        out.append(term)
        used += len(term) + 1
    return used


def _keyterms(manual: Manual, bike, rec) -> list[str]:
    """This bike's spoken vocabulary, capped at what Deepgram accepts.

    Two tiers, because a well-indexed manual would otherwise fill the list on its own. First the
    book in front of the mechanic — its name, the parts it names, the specs it prints, the
    headings, and the rider phrasings each section was indexed under — held to CATALOGUE_FROM so
    there is always room for the second: the standard parts catalogue for this kind of vehicle,
    which knows the words a manual's own index never prints, like "swingarm pivot" or "CVT".
    The bike's own name leads — an agent that mishears "390 Duke" has already lost the thread.
    """
    out: list[str] = []
    seen: set[str] = set()

    own: list[str] = [bike] + [p.name for p in manual.parts]
    try:
        own += [s.name for s in get_store().specs(manual.id)]
    except Exception:  # noqa: BLE001 - a manual with no spec index still gets its other terms
        pass
    for section in manual.sections:
        own += list(section.keywords or [])
    own += [s.title for s in manual.sections]
    used = _fill(own, out, seen, 0, CATALOGUE_FROM)

    # The catalogue is stored grouped - engine first, suspension and wheels last - and the budget
    # runs out long before the end of it, so take one entry from each group in turn instead. A
    # mechanic is as likely to ask about the swingarm as about the oil filter.
    names: dict[str, list[str]] = {}
    synonyms: dict[str, list[str]] = {}
    try:
        from . import parts_catalog

        for part in parts_catalog.parts_for(parts_catalog.profile_of(rec)):
            names.setdefault(part.group, []).append(part.name)
            synonyms.setdefault(part.group, []).extend(part.synonyms or [])
    except Exception:  # noqa: BLE001 - the taxonomy is a bonus on top of the manual's own words
        pass

    def spread(rows: dict[str, list[str]]) -> list[str]:
        return [x for row in zip_longest(*rows.values()) for x in row if x]

    # Every group's own name for a thing before any group's second way of saying it.
    catalogue = spread(names) + spread(synonyms)
    covered = {word for term in out for word in term.lower().split()}
    _fill(catalogue, out, seen, used, KEYTERM_CHARS, covered)
    return out


def _prompt(manual: Manual, bike: str, digest: str) -> str:
    """The spoken-style rules, rewritten against six-turn conversations measured on the live socket.

    Every rule below replaced a thing the agent actually did wrong in a recorded turn, not a thing
    it might do: it answered "and the front one?" out of context and invented thirty newton metres;
    it said "the manual doesn't print the brake fluid type" off a get_spec result that had come back
    about brake linings, when page 85 prints DOT 4; it offered "do you want the page on the brake
    system opened?" at the end of an answer; it read a semicolon out loud; it answered "thanks" with
    a page number. The wording is deliberately concrete about each one, because a general rule
    ("be concise", "stay grounded") is what was there before and it is what produced those turns.
    """
    return f"""You are the voice of Mechanica, answering out loud for a professional mechanic who has
this motorcycle on the lift and dirty hands. You speak; you are never read. You are another
mechanic across the bench, not an assistant: no "as an AI", no "I'd be happy to", no "I hope that
helps".

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

EVERY QUESTION IS A NEW QUESTION. "And the front one?" is not a follow-up, it is a question about
a different part, and it gets its own function call. A different end of the bike, a different
part, a different kind of figure: call again, every time, before you speak. The ONLY thing you may
say without calling anything is a repeat of something you already said in this conversation -
"which page was that?", "say that again", "what was the number?" - and then you repeat it word for
word and change nothing.

HOW YOU TALK
- One sentence. A second one only when it carries a different fact. Never a third.
- The page first, in the same sentence as the figure: "Page 78, one hundred newton metres." His
  eye goes to the page while his ear takes the number. Write the page as digits - "page 78" - and
  the figure as words.
- Say the figure once, in the unit the manual prints first. Do not convert and do not read out the
  bracketed second unit.
- Write only what a mouth can say. No bullet points, no numbered lists, no markdown, no
  asterisks, no emoji, no "e.g.", no "etc." - and no semicolons, colons, dashes or brackets,
  because a mouth has no punctuation for them.
- Every figure spelled the way you say it, never the way it is printed:
    100 Nm        -> one hundred newton metres
    4.5 Nm        -> four point five newton metres
    2.0 bar       -> two point zero bar
    1.5 l         -> one point five litres
    0.10-0.15 mm  -> nought point one zero to nought point one five millimetres
    SAE 15W/50    -> SAE fifteen W fifty
    DOT 4         -> DOT four
    M10x1.25      -> M ten by one point two five
- Use his words for the part. He said rear axle nut, you say rear axle nut, even if the manual
  indexes it as "Nut, rear wheel spindle". Correct him only when the manual's row is genuinely a
  different part, and then say which.
- Start with the answer. No filler, ever: never open with "sure", "of course", "great question",
  "I found that", "according to the manual", "let me check". The first word out of your mouth
  is part of the answer.
- End on the answer. NEVER finish with a question, an offer or a check-in. Not "do you want the
  page opened", not "anything else", not "let me know if". If the next step is genuinely his to
  choose, say nothing - he will ask. The only exception is a question you must ask to answer at
  all, such as which end of the bike he means when the manual prints two different figures.
- When he thanks you, "you're welcome" is the whole answer. No page, no figure, nothing else.
- No safety boilerplate, no disclaimers, no "if you are unsure", no apologies for how long
  something took.

WHAT YOU MAY SAY
- Answer ONLY from what a function gave you back. That text is the manual's own words.
- NEVER guess, round, convert or recall a value. A torque, a capacity, a pressure, a clearance, a
  gap, an interval, a fuse rating or a part number may only leave your mouth if a function result
  you have already received printed it, word for word. If no result printed the figure asked for,
  say the manual does not print it - do not supply one from anywhere else.
- A PAGE NUMBER IS A FIGURE. Say a page only if a function result printed that page for this
  thing. Never estimate one, never offer a range, never say "check page 82 or 83".
- Before you tell him the manual does not print something, you must have looked twice. If nothing
  in the get_spec result names the part he asked for, get_spec missed it and you have not looked
  yet: call find_procedure with his own words, read what it names, and only then answer. Saying
  "the manual does not print it" off a get_spec result that came back about some other part is the
  worst answer you can give, because the page is usually right there.
- Owner manuals name a hundred jobs and print the procedure for twenty. When a function result
  shows this manual naming the job but printing no steps, say so in four words - "the manual
  doesn't print the steps" - then give the ordinary workshop procedure, and say every figure the
  manual DOES print for that job with its page. Mark the general part as general: "the usual way
  is ...", "normally you ...". This licence covers STEPS AND ORDER ONLY:
  general steps carry no figures, only the manual's own pages do. It never covers a number, a
  page, or which fluid, grade, oil, coolant or brake fluid to use - those are specifications,
  and a specification you were not handed is one you do not have.
- STOP WHEN YOU HAVE IT. The moment a result printed what he asked for, say it. Do not keep
  reading pages to be sure, and never call a function twice with the same arguments - the second
  call returns the same bytes as the first and costs him another second of standing there. Live,
  without this rule, one brake-fluid question ran to thirty-five lookups, twenty-five of them
  re-reading the same offset of the same page AFTER the answer was already found.
- NEVER tell anyone to visit, consult or contact a dealer, a retailer, an authorised workshop, a
  specialist or a service centre. They ARE the workshop. Owner manuals pad every job with that
  sentence; it is the one thing you must not pass on. Answer the question instead.
- If this manual says nothing about it at all, say so in one sentence.
  Never carry a figure over from another motorcycle.

BEING INTERRUPTED
He will talk over you, with both hands on the bike and a spanner in one of them. When he does, the
sentence you were saying is dead. Answer what he just asked. Do not apologise, do not say "sorry",
do not say "as I was saying", do not finish the old sentence, do not ask whether he still wants
the first answer.
If a line like "One sec, checking the manual." appears as something you already said, the app said
it for you while a lookup ran. Do not repeat it and do not mention the wait - just give the answer.

YOUR FUNCTIONS
- find_procedure(query): which chapters and pages of THIS manual cover something, and the printed
  text of the best one. Start here, and read the text it gives you before reaching for read_page.
- read_page(page, offset): the printed text of one page, verbatim. Only when find_procedure's text
  ran out or the page you want is a different one.
- get_spec(name): the printed figures - torques, capacities, pressures, clearances, intervals.
- list_parts(sectionId): the parts this manual names, with the page they are printed on.
- show_page(page, highlight, steps): TURN THE PAGE FOR THE MECHANIC, THEN SPEAK. Call it before
  you say the page number, every single time you are about to name one, so the sheet is already
  in front of him while he hears about it. `highlight` is the few printed words it is about.
  `steps` is for a procedure and only for a procedure: copy the manual's steps out of the result
  word for word, one step per entry, in the manual's own order, and they are written under your
  answer on his screen - which is the only way he can read them, because your own sentence is
  gone the moment you have said it. Never write a step the result did not print, never renumber
  them, never tidy the wording, and still say your one sentence out loud afterwards."""


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
            "description": "Find which chapters and printed pages of this manual cover a job or a topic, and get the best section's printed text back with it. Call this first; you usually will not need read_page after it.",
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
            "description": "The verbatim printed text of one page of this manual. Use it only when find_procedure's own text stopped short or you need a different page.",
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
            # No endpoint: this one comes back to the browser as client_side true and moves the
            # reader. `steps` and `highlight` ride with the page because the browser never sees a
            # tool result - Deepgram fetches the manual's text, not the tab - so the only way the
            # printed lines can be WRITTEN on his screen is if the agent hands them over here,
            # word for word, in the same call that turns the page.
            "name": "show_page",
            "description": (
                "Turn the rider's screen to a printed page of this manual, and optionally write the "
                "manual's own steps under your answer. Call this BEFORE you speak, every time you are "
                "about to name a page: he should be looking at it while he hears about it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": f"Printed page number, 1 to {pages}."},
                    "highlight": {
                        "type": "string",
                        "description": "The few words on that page this is about, copied from the printed text.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The procedure's steps copied from the printed text word for word, one step per "
                            "entry, in the manual's own order. Only when a result printed steps."
                        ),
                    },
                },
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
    rec = _bike(manual, bikeId)
    bike = _label(manual, rec)
    digest = _digest(manual)
    keyterms = _keyterms(manual, bike, rec)
    settings_message = {
        "url": AGENT_WS,
        "sampleRate": AGENT_RATE,
        "manualId": manual.id,
        "bike": bike,
        # The browser bounds-checks a page against this before it moves the reader.
        "pages": manual.pages,
        "keyterms": len(keyterms),
        "settings": {
            "type": "Settings",
            "audio": {
                "input": {"encoding": "linear16", "sample_rate": AGENT_RATE},
                "output": {"encoding": "linear16", "sample_rate": AGENT_RATE, "container": "none"},
            },
            "agent": {
                "language": "en",
                # A manual with nothing indexed yet sends no `keyterms` key at all rather than an
                # empty array, which is one more shape to hope Deepgram accepts.
                "listen": {"provider": dict(LISTEN, keyterms=keyterms) if keyterms else dict(LISTEN)},
                "think": {
                    "provider": {"type": "open_ai", "model": THINK_MODEL},
                    "prompt": _prompt(manual, bike, digest),
                    "functions": _functions(manual.id, manual.pages),
                },
                "speak": {"provider": {"type": "deepgram", "model": SPEAK_MODEL}},
                "greeting": f"{bike}. Go ahead.",
            },
        },
    }
    # The session is real from here (an http PUBLIC_BASE has already 503'd above), so build what this
    # manual's FIRST spoken question would otherwise build while the rider waits on it: the BM25 index
    # and the page map the picker's snippets are sliced out of, both built on first use. Off this
    # thread, under the 724 ms it takes the greeting to be spoken. Idempotent, and it swallows its own
    # failures - a warm-up may never break the session it is warming.
    threading.Thread(target=ask_mod.warm, args=(manual.id,), daemon=True).start()
    return settings_message


# How much of a section find_procedure hands back with it. Three pages covers every procedure the
# KTM prints (the longest is two); SECTION_CHARS is roughly two printed pages of text and keeps the
# result inside the think model's context without a second call.
SECTION_PAGES = 3
SECTION_CHARS = 3600


def _printed(manual_id: str, start: int, end: int) -> tuple[str, list[int]]:
    """The manual's own text for a section's pages — the same bytes read_page serves, never
    rewritten — with the page each run of it is printed on marked in the manual's own words."""
    first = max(1, int(start or 0))
    if not first:
        return "", []
    last = max(first, min(int(end or first), first + SECTION_PAGES - 1))
    out: list[str] = []
    pages: list[int] = []
    budget = SECTION_CHARS
    for page in range(first, last + 1):
        try:
            text = _page_text(manual_id, page).strip()
        except HTTPException:
            break
        if not text:
            continue
        # Not a paraphrase and not a summary: a cut, at a line, with the page it came off named.
        if len(text) > budget:
            cut = text.rfind("\n", 0, budget)
            text = text[: cut if cut > budget // 2 else budget]
        if not text:
            break
        out.append(f"[page {page}]\n{text}")
        pages.append(page)
        budget -= len(text)
        if budget <= 200:
            break
    return "\n\n".join(out), pages


@tools.post("/find_procedure")
def find_procedure(body: FindBody, manualId: str | None = Query(default=None)):
    manual_id = _pick(body, manualId)
    _manual(manual_id)
    try:
        # A spoken turn: no cost-log scan for a dollar figure nobody hears, no prompt compression the
        # rider pays for in silence, and the picker that does run reasons at "none".
        with ask_mod.spoken():
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
    if sections:
        # Improvement #4. Measured on the live socket, a procedure question was find_procedure
        # followed by four to six read_page calls, and the whole chain took 5-10 s while the rider
        # heard nothing: every single round trip is 250-650 ms, so the cost is the number of hops,
        # not any one hop. The pages the best section is printed on come back WITH it, verbatim out
        # of the same page text read_page serves, so the ordinary case is one call.
        text, pages = _printed(manual_id, sections[0]["pageStart"], sections[0]["pageEnd"])
        if text:
            sections[0]["text"] = text
            sections[0]["textPages"] = pages
    return {"sections": sections, "firstPage": sections[0]["pageStart"] if sections else 0}


@tools.post("/read_page")
def read_page(body: PageBody, manualId: str | None = Query(default=None)):
    manual_id = _pick(body, manualId)
    _manual(manual_id)
    text, has_more, next_offset = _chunk(_page_text(manual_id, body.page), body.offset)
    return {"page": body.page, "text": text, "hasMore": has_more, "nextOffset": next_offset}


# Which end of the motorcycle a name is about. "and the front one?" is not a hint on top of the
# previous question, it IS the question: measured on the live socket, a word-level match for
# "front axle nut torque" came back with "Nut, rear wheel spindle" - the right shape, the wrong
# end, and 45 Nm of difference. Spoken, there is no page on screen to catch it.
SIDES = (("front",), ("rear", "back"), ("left",), ("right",), ("intake", "inlet"), ("exhaust",))
# What kind of figure the question is after, in the words a mechanic uses for it. The Spec rows
# already carry a `kind`, so "front axle nut TORQUE" can outrank a tyre pressure that happens to
# share the word "front" and nothing else.
KINDS = {
    "torque": ("torque", "torques", "tighten", "tightening", "newton", "nm", "lbf"),
    "capacity": ("capacity", "quantity", "volume", "litre", "litres", "liter", "liters", "refill", "fill"),
    "pressure": ("pressure", "bar", "psi", "inflate", "inflation"),
    "clearance": ("clearance", "clearances", "gap", "play", "slack", "backlash"),
    "size": ("size", "dimension", "thickness", "depth", "diameter", "length", "limit"),
    "electrical": ("volt", "volts", "voltage", "amp", "amps", "ampere", "fuse", "watt", "battery"),
    "grade": ("grade", "spec", "specification", "type", "viscosity"),
}
WORD = re.compile(r"[a-z0-9.]+")
# Words a spoken question is full of and a spec name means nothing by. "the" alone put a handlebar
# clamp above a brake-pad wear limit, because the clamp's name is long enough to contain it.
SKIP = frozenset(
    "the and for how can get much what which does did are was you your with from that this have "
    "should when its it's out off too but not any".split()
)


def _sides(text: str) -> set[str]:
    words = set(WORD.findall(text.lower()))
    return {group[0] for group in SIDES if words.intersection(group)}


def _kinds(text: str) -> set[str]:
    words = set(WORD.findall(text.lower()))
    return {kind for kind, cues in KINDS.items() if words.intersection(cues)}


def _rank(needle: str, specs: list) -> list:
    """The specs whose name shares words with `needle`, best first, the wrong end dropped."""
    want = _sides(needle)
    kinds = _kinds(needle)
    words = [w for w in WORD.findall(needle) if len(w) > 2 and w not in SKIP]
    scored = []
    for i, spec in enumerate(specs):
        name = spec.name.lower()
        side = _sides(name)
        if want and side and not want.intersection(side):
            continue
        score = sum(1 for w in words if w in name)
        if not score:
            continue
        # A row that names the end asked for beats one that names no end at all, and a row that
        # prints the KIND of figure asked for beats one that shares a word by accident.
        if want.intersection(side):
            score += 1
        if kinds:
            score += 2 if spec.kind in kinds else -2
        scored.append((-score, i, spec))
    scored.sort()
    return [spec for _, _, spec in scored]


@tools.post("/get_spec")
def get_spec(body: SpecBody, manualId: str | None = Query(default=None)):
    manual_id = _pick(body, manualId)
    _manual(manual_id)
    needle = body.name.strip().lower()
    specs = get_store().specs(manual_id)
    exact = [s for s in specs if needle and (needle in s.name.lower() or s.name.lower() in needle)]
    hits = _rank(needle, exact) if exact else _rank(needle, specs)
    if not hits:
        hits = exact
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

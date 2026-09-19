"""Question -> pages. Router (cheap, cached system prompt) -> index -> picker (ids only, server-validated).

Never returns prose: the answer is always a list of the manual's own sections.
Spec intents answer straight from the parsed Spec rows and never pay for a picker call.
"""

import os
import re
import threading

import httpx
from pydantic import BaseModel

from . import llm
from .config import settings
from .models import AskResponse, Match, Section
from .search import get_index
from .store import get_store

KINDS = {"torque", "capacity", "clearance", "pressure", "grade", "size", "electrical", "other"}
MAX_MAIN = 4
MAX_RELATED = 2
SPEC_FLOOR = 0.5
SNIPPET = 300
TTC_URL = "https://api.thetokencompany.com/v1/compress"


class Route(BaseModel):
    intent: str
    components: list[str]
    queries: list[str]
    specName: str | None
    specKind: str | None


class Pick(BaseModel):
    sectionIds: list[str]
    relatedIds: list[str]


ROUTER_SYSTEM = """You are the query router of a motorcycle manual finder. A rider standing next to a bike types or
says one short sentence. You never answer the question. You never write prose, advice, warnings or explanations. You
only translate the rider's words into the vocabulary that a manufacturer's owner manual actually prints, so that a
keyword index can find the right printed section.

Return exactly these fields:
- intent: "procedure" when the rider wants to DO something (change, adjust, check, remove, install, clean, charge,
  bleed, lubricate, replace, fix, top up); "spec" when the rider wants a NUMBER or a rated value (torque, capacity,
  pressure, clearance, thickness, gap, voltage, amperage, oil grade, tyre size); "part" when the rider wants to know
  WHICH consumable or component fits (which oil, which spark plug, which fuse, which tyre, which brake fluid, which
  battery); "unknown" when the sentence names no vehicle system at all.
- components: the bike systems and parts named or clearly implied, in manual vocabulary, lowercase, singular.
  Examples of good component tokens: engine oil, oil filter, coolant, radiator, drive chain, rear sprocket, front
  brake, rear brake, brake pad, brake fluid, brake lining, front wheel, rear wheel, wheel spindle, axle, tyre, tyre
  pressure, tread depth, battery, fuse, headlight, spark plug, air filter, clutch, throttle, spring preload, fork,
  shock absorber, seat, side stand, chain tension.
- queries: 2 or 3 rephrasings of the rider's sentence in manual vocabulary. Each rephrasing must be a short noun
  phrase or imperative of the kind a manual prints as a heading, not a question. Keep the rider's own decisive nouns
  in at least one of the rephrasings. Do not invent bike parts that were not implied.
- specName: for intent "spec", the printed name of the value, for example "engine oil capacity", "tyre pressure
  front", "rear wheel spindle torque", "brake pad wear limit", "chain tension", "battery rated capacity". Null for
  every other intent.
- specKind: one of torque, capacity, clearance, pressure, grade, size, electrical, other. Null for every other intent.

Rider vocabulary guide. Riders speak casually; manuals do not. Translate in this direction:
- "oil change", "change the oil", "drop the oil" -> changing the engine oil and oil filter, oil drain plug, oil screen.
- "how much oil", "how many litres of oil", "oil capacity" -> engine oil capacity, quantity for topping up.
- "top up the oil", "add oil", "fill oil" -> topping up engine oil, oil filler plug, oil filler opening.
- "check my oil", "is my oil low", "oil window", "sight glass" -> checking engine oil level, oil level markings.
- "tyre", "tire", "rubber" -> tyre, tire. Both spellings mean the same section; emit both spellings across the
  rephrasings when the manual language is unknown.
- "tyre pressure", "psi", "bar", "how hard should my tyres be", "pump up the tyres" -> checking tyre pressure, tyre
  pressure front, tyre pressure rear, one-up, two-up with luggage, tyre cold.
- "tread", "bald tyre", "how worn", "legal limit" -> tyre tread depth, minimum tread depth, checking tyre condition.
- "chain is loose", "chain slack", "chain sag", "chain too tight", "chain rattles" -> checking the chain tension,
  adjusting the chain tension, drive chain, chain tension measurement.
- "lube the chain", "chain spray", "grease the chain", "dirty chain" -> cleaning the chain, chain lubricant.
- "brake pads worn", "how thin are my pads", "pads", "linings", "squealing brakes" -> checking brake pad thickness,
  brake lining thickness, brake-pad wear limit, wear indicator.
- "brake fluid", "spongy brakes", "lever goes to the bar", "DOT 4" -> checking brake fluid level, brake fluid
  reservoir, brake fluid specification.
- "coolant", "antifreeze", "radiator", "it is overheating", "temperature light" -> checking the coolant level,
  compensating tank, radiator cap, coolant specification.
- "battery dead", "won't start", "flat battery", "trickle charger", "jump start" -> charging the 12-V battery,
  battery rated voltage, battery rated capacity, jump-starting, connecting a battery charger.
- "fuse blown", "no lights", "nothing works", "check the fuses" -> replacing fuses, fuse assignment, fuse box,
  main fuse, fuse rating in amperes.
- "headlight", "beam too high", "aim the light", "high beam" -> adjusting the headlight range, headlight beam.
- "front wheel out", "take the wheel off", "pull the wheel", "puncture" -> removing the front wheel, quick-release
  axle, wheel spindle, brake caliper removal.
- "rear wheel out", "back wheel off" -> removing the rear wheel, rear wheel carrier, wheel spindle nut.
- "torque", "how tight", "Nm", "newton metres", "spec on the bolt" -> tightening torque, tightening torques,
  threaded fasteners, guideline torque.
- "service", "when is my next service", "maintenance intervals" -> service schedule, service work, maintenance work.
- "seat off", "remove the seat", "get to the battery" -> removing the seat, seat lock, seat on rear frame.
- "preload", "suspension is soft", "sag", "set up the shock" -> adjusting spring preload, front wheel, rear wheel,
  negative spring travel.
- "plug", "spark plugs", "which plug" -> spark plug, spark plug designation, spark plug tightening torque.

Rules. Keep queries short, at most eight words each. Use the singular unless the manual plainly prints a plural
("brake pads", "fuses", "threaded fasteners"). Never add a manufacturer name, a model name or a year. Never add
the word "motorcycle", "bike" or "manual" to a query. If the rider mentions front or rear, keep that word in every
rephrasing, because front and rear are different printed sections. If the rider mentions a number or a unit, treat
it as a spec intent. If the rider describes a symptom rather than a task ("it pulls to one side", "clunking from
the back", "smells of petrol"), pick the component most likely to be inspected and use intent procedure.

Examples.
"change the oil" -> intent procedure; components ["engine oil", "oil filter"]; queries ["changing the engine oil and
oil filter", "engine oil change oil drain plug", "replace oil filter"]; specName null; specKind null.
"how much oil does it take" -> intent spec; components ["engine oil"]; queries ["engine oil capacity", "engine oil
quantity with filter change", "how much engine oil"]; specName "engine oil capacity"; specKind capacity.
"torque for the rear axle" -> intent spec; components ["rear wheel", "wheel spindle"]; queries ["rear wheel spindle
tightening torque", "chassis tightening torques rear wheel", "nut rear wheel spindle"]; specName "rear wheel spindle
nut torque"; specKind torque.
"chain is loose" -> intent procedure; components ["drive chain", "chain tension"]; queries ["checking the chain
tension", "adjusting the chain tension", "drive chain slack"]; specName null; specKind null.
"tyre pressure" -> intent spec; components ["tyre", "tyre pressure"]; queries ["checking tyre pressure", "tire
pressure front rear", "tyre pressure cold"]; specName "tyre pressure front"; specKind pressure.
"brake pads worn" -> intent procedure; components ["brake pad", "front brake", "rear brake"]; queries ["checking
brake pad thickness", "brake lining thickness wear limit", "brake pad wear"]; specName null; specKind null.
"which oil do I need" -> intent part; components ["engine oil"]; queries ["engine oil specification", "engine oil
SAE grade", "recommended engine oil"]; specName "engine oil specification"; specKind grade.
"fuse blown" -> intent procedure; components ["fuse"]; queries ["replacing fuses", "fuse assignment fuse box",
"changing the fuses"]; specName null; specKind null.
"battery dead" -> intent procedure; components ["battery"]; queries ["charging the 12-V battery", "battery charger
connection", "jump-starting"]; specName null; specKind null.
"front wheel out" -> intent procedure; components ["front wheel", "wheel spindle"]; queries ["removing the front
wheel", "front wheel removal quick-release axle", "take off front wheel"]; specName null; specKind null."""

PICKER_SYSTEM = """You order candidate sections of a motorcycle manual for a rider who asked one question. You do not
write prose and you do not answer the question. You return ids only.

Rules:
- Use only ids that appear in the candidate list. Never invent an id, never reword an id.
- sectionIds: at most 4 ids, ordered by what a mechanic reads first for this exact question. The first id must be
  the one printed page a rider would open. Checking comes before adjusting when the rider reports a symptom;
  the procedure comes before the technical-data table when the rider wants to do the job; the technical-data table
  comes first when the rider only wants a printed number.
- Front and rear are different sections: if the rider said front, do not lead with the rear section, and the other
  way round.
- relatedIds: at most 2 ids a rider would plausibly need next (the torque table for a removal job, the topping-up
  procedure after a level check, the seat removal before battery work). Never repeat an id from sectionIds.
- Drop candidates that only share a generic word (oil in "fork oil" for an engine-oil question). Fewer, correct ids
  beat a long list. If only one candidate fits, return one id."""

_cache: dict[tuple[str, str], AskResponse] = {}
_pages: dict[str, dict[int, str]] = {}
_lock = threading.RLock()
_WS = re.compile(r"[^a-z0-9]+")


def _norm(query: str) -> str:
    return _WS.sub(" ", query.lower()).strip()


def _page_text(manual_id: str) -> dict[int, str]:
    with _lock:
        hit = _pages.get(manual_id)
    if hit is not None:
        return hit
    text = {p.page: " ".join(p.text.split()) for p in get_store().pages(manual_id)}
    with _lock:
        _pages[manual_id] = text
    return text


def _snippet(manual_id: str, section: Section, chars: int = SNIPPET) -> str:
    pages = _page_text(manual_id)
    body = " ".join(pages.get(p, "") for p in range(section.pageStart, section.pageEnd + 1))
    return body[:chars]


def _spend(store, before: int) -> float:
    events = store.costs()
    return round(sum(e.usd for e in events[before:]), 6)


def _route(query: str) -> Route:
    try:
        route = llm.structured(
            route="ask.router",
            model=settings.model_router,
            schema=Route,
            system=ROUTER_SYSTEM,
            user=query,
        )
    except Exception:
        return Route(intent="procedure", components=[], queries=[query], specName=None, specKind=None)
    queries = [q.strip() for q in route.queries if q and q.strip()][:3]
    if query.strip() not in queries:
        queries.append(query.strip())
    kind = route.specKind if route.specKind in KINDS else None
    intent = route.intent if route.intent in {"procedure", "spec", "part", "unknown"} else "procedure"
    return Route(
        intent=intent,
        components=[c.strip() for c in route.components if c and c.strip()][:6],
        queries=queries,
        specName=route.specName,
        specKind=kind,
    )


def _compress(text: str) -> str:
    """The Token Company, POST /v1/compress. Unverified API: any failure keeps the original text."""
    key = os.getenv("TTC_API_KEY")
    if not key:
        return text
    try:
        response = httpx.post(
            TTC_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "bear-2", "input": text, "compression_settings": {"aggressiveness": 0.3}},
            timeout=8.0,
        )
        response.raise_for_status()
        data = response.json()
        out = data.get("output") or data.get("compressed") or data.get("text")
        return out if isinstance(out, str) and out.strip() else text
    except Exception:
        return text


def _pick(manual_id: str, query: str, route: Route, order: list[str], sections: dict[str, Section]) -> list[str]:
    lines = []
    for section_id in order:
        section = sections[section_id]
        lines.append(
            f"{section_id} | {section.title} | {section.chapter} | p. {section.pageStart}-{section.pageEnd}\n"
            f"  {_snippet(manual_id, section)}"
        )
    user = f"Question: {query}\nComponents: {', '.join(route.components) or '-'}\n\nCandidates:\n" + _compress(
        "\n".join(lines)
    )
    try:
        pick = llm.structured(
            route="ask.picker",
            model=settings.model_picker,
            schema=Pick,
            system=PICKER_SYSTEM,
            user=user,
        )
    except Exception:
        return order[:MAX_MAIN]
    allowed = set(order)
    out: list[str] = []
    for section_id in list(pick.sectionIds)[: MAX_MAIN * 2]:
        if section_id in allowed and section_id not in out:
            out.append(section_id)
    out = out[:MAX_MAIN]
    for section_id in list(pick.relatedIds)[: MAX_RELATED * 2]:
        if section_id in allowed and section_id not in out and len(out) < MAX_MAIN + MAX_RELATED:
            out.append(section_id)
    return out or order[:MAX_MAIN]


def _by_spec(manual_id: str, route: Route, sections: dict[str, Section]) -> list[str]:
    if not route.specName:
        return []
    index = get_index()
    best: dict[str, float] = {}
    for hit in index.spec(manual_id, route.specName, route.specKind, k=8):
        section_id = hit.spec.sectionId
        if hit.score >= SPEC_FLOOR and section_id in sections and hit.score > best.get(section_id, 0.0):
            best[section_id] = hit.score
    if not best:
        return []
    lexical = {h.sectionId: h.score for h in index.query(manual_id, route.queries, route.components, k=8)}
    ranked = sorted(best.items(), key=lambda kv: -(kv[1] + 0.5 * lexical.get(kv[0], 0.0)))
    return [section_id for section_id, _ in ranked][: MAX_MAIN + MAX_RELATED]


def answer(manual_id: str, query: str) -> AskResponse:
    store = get_store()
    manual = store.manual(manual_id)
    if manual is None or not query.strip():
        return AskResponse(matches=[], intent="unknown")

    key = (manual_id, _norm(query))
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached.model_copy(update={"usd": 0.0})

    before = len(store.costs())
    sections = {s.id: s for s in manual.sections}
    route = _route(query)

    ordered: list[str] = []
    if route.intent == "spec":
        ordered = _by_spec(manual_id, route, sections)
    if not ordered:
        hits = get_index().query(manual_id, route.queries, route.components, k=8)
        order = [h.sectionId for h in hits if h.sectionId in sections]
        if not order:
            return AskResponse(matches=[], intent=route.intent, usd=_spend(store, before))
        ordered = _pick(manual_id, query, route, order, sections) if len(order) > 1 else order

    matches = [
        Match(section=sections[section_id], score=round(max(0.1, 1.0 - 0.1 * i), 2))
        for i, section_id in enumerate(ordered[: MAX_MAIN + MAX_RELATED])
    ]
    response = AskResponse(matches=matches, intent=route.intent, usd=_spend(store, before))
    with _lock:
        _cache[key] = response
    return response

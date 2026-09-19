"""Question -> pages. Router (cheap, cached system prompt) -> index -> picker (ids only, server-validated).

Never returns prose: the answer is always a list of the manual's own sections.
Spec intents answer straight from the parsed Spec rows and never pay for a picker call.
"""

import os
import re
import threading
from collections import OrderedDict

import httpx
from pydantic import BaseModel

from . import llm
from .config import settings
from .models import AskResponse, Match, Section
from .search import get_index
from .store import get_store

KINDS = {"torque", "capacity", "clearance", "pressure", "grade", "size", "electrical", "other"}
INTENTS = {"procedure", "spec", "part", "unknown"}
MAX_MAIN = 4
MAX_RELATED = 2
SPEC_FLOOR = 0.5
SNIPPET = 220
CANDIDATES = 6
PICK_MARGIN = 0.85
CACHE_MAX = 500
EFFORT = "low"
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

Spelling. Riders type fast, one-handed, on a dirty phone. Silently correct obvious misspellings to the printed word
before you build the queries, and never repeat the misspelling: "tyre presure" -> tyre pressure, "brek pads" ->
brake pads, "chian" -> chain, "oli" -> oil, "engien" -> engine, "fuze" -> fuse, "headlite" -> headlight, "cooland"
-> coolant, "batery" -> battery, "flooid" -> fluid, "treed" -> tread, "remve" -> remove, "sparkplug" -> spark plug,
"pre-load" -> preload, "breaks" -> brakes, "tires"/"tyres" -> both spellings.

Language. Riders type in their own language; every manual in this app is printed in English. Translate the sentence
into English manual vocabulary first and emit English only, in components, in queries and in specName. Never echo a
foreign word back. The rule about keeping the rider's own decisive nouns then means the English translation of those
nouns. Guide:
- German: Reifendruck -> tyre pressure; Reifen -> tyre; Kettenspannung -> chain tension; Kette -> drive chain;
  Olwechsel / Olwechsel machen -> changing the engine oil and oil filter; Olstand -> engine oil level; Motorol ->
  engine oil; Bremsbelage -> brake pads; Bremsflussigkeit -> brake fluid; Batterie laden -> charging the battery;
  Vorderrad ausbauen -> removing the front wheel; Hinterrad -> rear wheel; Kuhlmittel -> coolant; Sicherung -> fuse;
  Scheinwerfer -> headlight; Profiltiefe -> tread depth; Federvorspannung -> spring preload; Anzugsdrehmoment ->
  tightening torque; Sitzbank -> seat; vorne -> front; hinten -> rear; prufen -> checking; einstellen -> adjusting;
  wechseln / tauschen -> changing; ausbauen -> removing; reinigen -> cleaning; nachfullen -> topping up.
- Spanish: presion de neumaticos -> tyre pressure; neumatico -> tyre; aceite del motor -> engine oil; cambiar el
  aceite -> changing the engine oil and oil filter; nivel de aceite -> engine oil level; pastillas de freno ->
  brake pads; liquido de frenos -> brake fluid; bateria -> battery; cadena -> drive chain; rueda delantera -> front
  wheel; rueda trasera -> rear wheel; fusible -> fuse; refrigerante -> coolant; faro -> headlight; par de apriete ->
  tightening torque; comprobar -> checking; ajustar -> adjusting; cambiar -> changing; quitar -> removing.
- French: pression des pneus -> tyre pressure; pneu -> tyre; huile moteur -> engine oil; niveau d'huile -> engine
  oil level; vidange -> changing the engine oil and oil filter; plaquettes de frein -> brake pads; liquide de frein
  -> brake fluid; batterie -> battery; chaine -> drive chain; roue avant -> front wheel; roue arriere -> rear wheel;
  fusible -> fuse; liquide de refroidissement -> coolant; phare -> headlight; couple de serrage -> tightening
  torque; verifier -> checking; regler -> adjusting; changer -> changing; demonter -> removing.
- Italian and Portuguese follow the same pattern: translate, then use the English manual word.

Out of scope. An owner manual covers operating, checking, adjusting, servicing and the printed technical data of
this one motorcycle. It does not cover riding technique, tuning, aftermarket parts, prices, dealers, insurance,
routes, weather, opinions, other vehicles, or small talk. Return intent "unknown" with an empty components list and
an empty queries list when the sentence is:
- a greeting or a courtesy ("hello", "hi", "thanks", "ok, cool"), or meaningless keyboard noise ("asdfgh")
- riding skill or technique ("how do I wheelie", "teach me to corner faster", "how do I do a stoppie", "launch it")
- shopping, tuning or styling ("best exhaust", "can I fit a turbo", "should I buy a Ducati instead", "what colour
  should I paint it", "where can I buy a helmet", "loudest slip-on")
- money, resale value, insurance, finance, dealers, travel, bookings, music, news, sport, the weather or jokes
- an opinion or a recommendation the manual does not print, or a task this app cannot do ("book me a hotel")
Never stretch such a sentence into a bike system: "best exhaust" is not the exhaust, "how much is it worth" is not
the technical data, "who won MotoGP" is not a component. For these, queries must be empty, not a best guess. Do not
use "unknown" for anything the manual does print, however casually or badly the rider types it, and never for a
sentence in another language that names a real bike system.

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
wheel", "front wheel removal quick-release axle", "take off front wheel"]; specName null; specKind null.
"brek pads worn on the back" -> intent procedure; components ["brake pad", "rear brake"]; queries ["checking rear
brake pad thickness", "rear brake lining thickness wear limit", "rear brake pad wear"]; specName null; specKind null.
"Reifendruck pruefen" -> intent spec; components ["tyre", "tyre pressure"]; queries ["checking tyre pressure", "tire
pressure front rear", "tyre pressure cold"]; specName "tyre pressure front"; specKind pressure.
"Vorderrad ausbauen" -> intent procedure; components ["front wheel", "wheel spindle"]; queries ["removing the front
wheel", "front wheel removal", "front wheel spindle"]; specName null; specKind null.
"cambiar el aceite del motor" -> intent procedure; components ["engine oil", "oil filter"]; queries ["changing the
engine oil and oil filter", "engine oil change oil drain plug", "replace oil filter"]; specName null; specKind null.
"tire pressure with passenger" -> intent spec; components ["tyre", "tyre pressure"]; queries ["tyre pressure with
passenger full payload", "tire pressure two-up rear", "checking tyre pressure"]; specName "tyre pressure with
passenger rear"; specKind pressure.
"how do I wheelie" -> intent unknown; components []; queries []; specName null; specKind null.
"best exhaust" -> intent unknown; components []; queries []; specName null; specKind null.
"hello" -> intent unknown; components []; queries []; specName null; specKind null.
"should I buy a Ducati instead" -> intent unknown; components []; queries []; specName null; specKind null."""

PICKER_SYSTEM = """You order candidate sections of a motorcycle owner manual for a rider who asked one question
while standing next to the bike. You never answer the question, never write prose, never explain, never warn. You
return ids only. The app renders the printed page you name; a wrong id sends the rider to the wrong page, and an
invented id shows the rider nothing at all.

The user message gives the rider's question, the components the router recognised, and a numbered candidate list.
Each candidate line is: id | printed section title | chapter | page range, followed by the first words of the
printed text of that section. Judge a candidate on its title and its printed text, not on its id.

Hard rules.
- Use only ids copied character for character from the candidate list. Never invent an id, never reword an id,
  never merge two ids, never return a title instead of an id.
- sectionIds: at most 4 ids, best first. The first id must be the one printed page the rider would open to deal
  with the sentence they typed. If exactly one candidate fits, return exactly one id.
- relatedIds: at most 2 ids the same rider would plausibly need next, and never an id already in sectionIds.
- Return an empty sectionIds list and an empty relatedIds list only when the rider's sentence is not about this
  motorcycle at all, or when every candidate is about a different system than the one the rider named. An empty
  list is then a correct answer, better than the least-bad candidate. It is the wrong answer whenever any
  candidate covers the system the rider asked about: a rider who names a real part of the bike always gets at
  least one id back.

Ordering rules.
- The rider wants to DO something: the procedure section leads, and the technical-data table is at most a related
  id. "Change the oil" leads with the oil-change procedure, not with the oil specification table.
- The rider wants a printed NUMBER or a rated value and one candidate is the technical-data table that prints it:
  the table leads, unless a procedure section prints the same value right where the rider is working, in which
  case the procedure leads and the table follows as a related id.
- The rider reports a SYMPTOM ("chain is loose", "pads are thin", "lever goes to the bar"): the checking or
  inspection section leads, and the adjusting, topping-up or replacing section follows.
- The rider asks WHICH consumable fits (which oil, which brake fluid, which plug, which battery, which fuse): the
  section that prints the designation or the specification leads. Owner manuals usually print the grade inside the
  procedure that uses it, so a checking or topping-up section that names the consumable in its printed text is a
  correct answer to a "which" question. Never answer a "which" question with an empty list because no candidate
  looks like a data table.
- Front and rear are different printed sections. If the rider said front, never lead with the rear section; if the
  rider said rear or back, never lead with the front section. If the rider named neither side, lead with the front
  section and offer the rear one as a related id.
- Checking a level and topping that level up are different printed sections. "Is my oil low" leads with the level
  check; "put some oil in" leads with the topping-up procedure.
- Cleaning, tensioning and adjusting a chain are three different printed sections. Take the one the rider's own
  verb names; if the rider only reports a noise or slack, lead with the tension check.
- Removing a wheel, adjusting a suspension and the torque table are different jobs. A removal job may carry the
  torque table as a related id, never the other way round.

Rejection rules.
- Drop a candidate that shares only a generic word with the question: fork oil for an engine-oil question, brake
  fluid for a brake-pad question, the service schedule for a job the rider is doing right now, a torque table for
  a question that names no fastener.
- Drop a candidate whose printed text is about a different system than the one the rider named, however similar
  the wording looks.
- Fewer, correct ids always beat a longer list. Two right ids are a better answer than four ids of which two are
  padding.

Worked examples, given a candidate list that contains the ids named.
- Question "chain is baggy" -> sectionIds ["chain-tension-check", "chain-tension-adjust"], relatedIds
  ["chassis-torques"]: the rider reports slack, so the check leads and the adjustment follows.
- Question "how many litres of oil does it take" with candidates for the oil-change procedure and the engine-oil
  data table -> sectionIds ["td-engine-oil", "engine-oil-topup"]: the rider wants the printed capacity.
- Question "pads look thin on the front" -> sectionIds ["brake-pads-front"], relatedIds ["brake-pads-rear"]: the
  rider said front, so the rear section can only be a related id.
- Question "which brake fluid does it take" with candidates for the front brake-fluid level check and for adding
  front brake fluid -> sectionIds ["front-brake-fluid-add", "front-brake-fluid-level"]: the adding procedure is
  where the manual prints DOT 4 / DOT 5.1, so it leads. An empty list here would be wrong.
- Question "best exhaust" against a candidate list of maintenance sections -> sectionIds [], relatedIds []: no
  candidate answers it, so both lists stay empty."""

_cache: "OrderedDict[tuple[str, str], AskResponse]" = OrderedDict()
_pages: dict[str, dict[int, str]] = {}
_lock = threading.RLock()
_WS = re.compile(r"[^a-z0-9]+")


def _norm(query: str) -> str:
    return _WS.sub(" ", query.lower()).strip()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(key: tuple[str, str]) -> AskResponse | None:
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
        return hit


def _remember(key: tuple[str, str], response: AskResponse) -> None:
    with _lock:
        _cache[key] = response
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


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
    """This ask only. The cost log is shared with ingest and identify, which may write while we run."""
    events = store.costs()
    return round(sum(e.usd for e in events[before:] if e.route.startswith("ask.")), 6)


def _route(query: str) -> Route:
    try:
        route = llm.structured(
            route="ask.router",
            model=settings.model_router,
            schema=Route,
            system=ROUTER_SYSTEM,
            user=query,
            reasoning=EFFORT,
        )
    except Exception:
        return Route(intent="procedure", components=[], queries=[query], specName=None, specKind=None)
    intent = route.intent if route.intent in INTENTS else "procedure"
    if intent == "unknown":
        return Route(intent="unknown", components=[], queries=[], specName=None, specKind=None)
    queries = [q.strip() for q in route.queries if q and q.strip()][:3]
    if query.strip() not in queries:
        queries.append(query.strip())
    kind = route.specKind if route.specKind in KINDS else None
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
            reasoning=EFFORT,
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
    return out


def _grounded(manual_id: str, spec) -> bool:
    """A spec row may only steer the answer if its quote is printed verbatim on the page it claims."""
    quote = " ".join(spec.quote.split())
    return bool(quote) and quote in _page_text(manual_id).get(spec.page, "")


def _by_spec(manual_id: str, route: Route, sections: dict[str, Section]) -> list[str]:
    if not route.specName:
        return []
    index = get_index()
    best: dict[str, float] = {}
    for hit in index.spec(manual_id, route.specName, route.specKind, k=8):
        section_id = hit.spec.sectionId
        if hit.score < SPEC_FLOOR or section_id not in sections or not _grounded(manual_id, hit.spec):
            continue
        if hit.score > best.get(section_id, 0.0):
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
    cached = _cached(key)
    if cached is not None:
        return cached.model_copy(update={"usd": 0.0})

    before = len(store.costs())
    sections = {s.id: s for s in manual.sections}
    route = _route(query)

    ordered: list[str] = []
    if route.intent == "spec":
        ordered = _by_spec(manual_id, route, sections)
    if route.intent != "unknown" and not ordered:
        hits = [h for h in get_index().query(manual_id, route.queries, route.components, k=CANDIDATES) if h.sectionId in sections]
        order = [h.sectionId for h in hits]
        decisive = len(order) <= 1 or hits[1].score <= PICK_MARGIN
        if decisive:
            ordered = order[:MAX_MAIN]
        else:
            # An empty pick means the candidate list was junk, not that the rider gets a blank screen:
            # the router already answers "is this about the bike at all", so fall back to the one best page.
            ordered = _pick(manual_id, query, route, order, sections) or order[:1]

    matches = [
        Match(section=sections[section_id], score=round(max(0.1, 1.0 - 0.1 * i), 2))
        for i, section_id in enumerate(ordered[: MAX_MAIN + MAX_RELATED])
    ]
    response = AskResponse(matches=matches, intent=route.intent, usd=_spend(store, before))
    _remember(key, response)
    return response

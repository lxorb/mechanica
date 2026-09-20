"""BM25 over section text + keywords, in memory, rebuilt from the store on first use.

Tokenisation starts from src/lib/match.ts (same phrases, stopwords, synonym groups, stemmer) so the backend
understands the rider vocabulary the client matcher understood, plus the page text it never had. On top of BM25:
a keyword bonus, a title-coverage bonus, a component bonus, a front/rear penalty because those are different
printed sections, and an absolute floor below which nothing in the manual is a real match.
"""

import re
import threading

from rank_bm25 import BM25Okapi

from ..models import Manual, Page, Spec
from . import Hit, SpecHit

PHRASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\btop(?:ping|ped)?[\s-]*up\b"), "refill"),
    (re.compile(r"\bfill(?:ing)?[\s-]*up\b"), "refill"),
    (re.compile(r"\banti[\s-]*freeze\b"), "antifreeze"),
    (re.compile(r"\bnewton[\s-]*met(?:er|re)s?\b"), "nm"),
    (re.compile(r"\bn[\s-]*m\b"), "nm"),
    (re.compile(r"\bhand[\s-]*bars?\b"), "handlebar"),
    (re.compile(r"\bhead[\s-]*light(?:s)?\b"), "headlight"),
    (re.compile(r"\bspark[\s-]*plug(?:s)?\b"), "sparkplug"),
    (re.compile(r"\bair[\s-]*filter(?:s)?\b"), "airfilter"),
    (re.compile(r"\bjump[\s-]*start(?:ing|ed|s)?\b"), "jumpstart"),
    (re.compile(r"\bquick[\s-]*release\b"), "quickrelease"),
    (re.compile(r"\bpre[\s-]*load\b"), "preload"),
    (re.compile(r"\btwo[\s-]*up\b"), "twoup"),
    (re.compile(r"\bone[\s-]*up\b"), "oneup"),
    (re.compile(r"\bhead[\s-]*lamp(?:s)?\b"), "headlight"),
    (re.compile(r"\bwheel[\s-]*spindle\b"), "spindle"),
]

STOP = set(
    (
        "a an the this that these those my your our their its it i me we you he she they them"
        " is are am was were be been being do does did done doing have has had"
        " how what when where why which who whose whom"
        " to of for on in at by with from up out off into onto about over under around again"
        " and or but not no nor so if then than as too also"
        " can could should would will shall may might must need needs needed want wants wanted please just"
        " go goes going make makes making take takes taking"
        " there here now much many any some all every each"
        " bike bikes motorcycle motorbike moto s t re ve ll"
    ).split(" ")
)

GROUPS: list[list[str]] = [
    ["oil"],
    ["lube", "lubricant", "lubrication", "lubricate", "grease", "spray"],
    ["tyre", "tire"],
    ["pad", "pads", "lining", "linings", "shoe"],
    ["slack", "tension", "tensioning", "play", "sag", "loose", "loosen"],
    ["refill", "fill", "top"],
    ["replace", "change", "swap", "renew", "new"],
    ["check", "inspect", "inspection", "examine", "verify", "look", "test"],
    ["torque", "tighten", "tightening", "nm"],
    ["coolant", "antifreeze"],
    ["battery", "charge", "charging", "charger"],
    ["fuse", "blown", "blow"],
    ["headlight", "headlamp", "bulb"],
    ["pressure", "psi", "bar", "inflate", "inflation"],
    ["wheel", "rim"],
    ["clutch"],
    ["front"],
    ["rear", "back"],
    ["chain", "drive", "sprocket"],
    ["brake", "braking"],
    ["engine", "motor"],
    ["adjust", "adjustment", "set", "setting"],
    ["remove", "removal", "detach", "dismount"],
    ["install", "installation", "mount", "fit", "refit"],
    ["clean", "cleaning", "wash"],
    ["level", "amount", "quantity"],
    ["wear", "worn", "thickness"],
    ["spindle", "axle"],
    ["bolt", "nut", "screw", "fastener"],
    ["preload", "spring", "suspension"],
    ["tread", "profile", "depth"],
    ["seat", "saddle"],
    ["jumpstart", "boost", "donor", "jumper"],
    ["capacity", "litre", "liter", "quart"],
    ["schedule", "interval"],
    ["overheat", "overheating", "radiator"],
    ["twoup", "pillion", "passenger", "luggage", "payload"],
    ["oneup", "solo"],
]


def stem(word: str) -> str:
    t = word
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("es"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    if len(t) > 3 and t.endswith("e"):
        t = t[:-1]
    return t


SYNONYM: dict[str, str] = {}
for _group in GROUPS:
    _head = stem(_group[0])
    for _word in _group:
        SYNONYM[stem(_word)] = _head

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    s = text.lower()
    for pattern, to in PHRASES:
        s = pattern.sub(to, s)
    return _NON_WORD.sub(" ", s).strip()


def canon(text: str) -> list[str]:
    out: list[str] = []
    for raw in normalize(text).split(" "):
        if not raw or raw in STOP:
            continue
        s = stem(raw)
        if not s:
            continue
        out.append(SYNONYM.get(s, s))
    return out


def contiguous(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if not n or n > len(hay):
        return False
    return any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


KEYWORD_BONUS = 0.3
COMPONENT_BONUS = 0.2
TITLE_COVER = 0.4
TITLE_EVIDENCE = 0.5
SIDE_PENALTY = 0.4
FLOOR = 1.2
TITLE_WEIGHT = 3
KEYWORD_WEIGHT = 2
SIDES = ("front", "rear")


def side_of(tokens) -> str | None:
    """front and rear are different printed sections; a token set naming both sides names neither."""
    found = [s for s in SIDES if s in tokens]
    return found[0] if len(found) == 1 else None


def evidence(query: str, title: str, keywords: list[str] | None = None) -> float:
    """How much of one section's own printed vocabulary the rider's sentence already carries, 0..1.

    Deliberately not a BM25 score. BM25 says which section wins the comparison between sections; this
    says whether the rider named the thing at all. A rider who says a keyword phrase this section was
    indexed under, word for word, has named it outright (1.0); otherwise it is the share of the printed
    title their own words cover. `ask.py` uses it to decide when a sentence needs no LLM to translate it.
    """
    spoken = f" {normalize(query)} "
    sequence = canon(query)
    for keyword in keywords or []:
        if f" {normalize(keyword)} " in spoken or contiguous(sequence, canon(keyword)):
            return 1.0
    words = set(canon(title))
    return len(set(sequence) & words) / len(words) if words else 0.0


class _Manual:
    def __init__(self, manual: Manual, pages: list[Page], specs: list[Spec]):
        by_page = {p.page: p.text for p in pages}
        self.ids: list[str] = []
        self.keywords: list[list[tuple[str, list[str]]]] = []
        self.titles: list[set[str]] = []
        self.sides: list[str | None] = []
        self.snippets: dict[str, str] = {}
        docs: list[list[str]] = []
        for section in manual.sections:
            body = " ".join(by_page.get(p, "") for p in range(section.pageStart, section.pageEnd + 1))
            blob = " ".join(
                [section.title] * TITLE_WEIGHT
                + [section.chapter]
                + [" ".join(section.keywords)] * KEYWORD_WEIGHT
                + [body]
            )
            docs.append(canon(blob))
            self.ids.append(section.id)
            self.keywords.append([(normalize(k), canon(k)) for k in section.keywords])
            title = set(canon(section.title))
            self.titles.append(title)
            self.sides.append(side_of(title))
            self.snippets[section.id] = " ".join(body.split())
        self.bm25 = BM25Okapi(docs) if docs else None
        self.specs = specs

    def snippet(self, section_id: str, chars: int = 300) -> str:
        return self.snippets.get(section_id, "")[:chars]


class LocalIndex:
    def __init__(self) -> None:
        self._built: dict[str, _Manual] = {}
        self._lock = threading.RLock()

    def index(self, manual: Manual, pages: list[Page], specs: list[Spec]) -> None:
        with self._lock:
            self._built[manual.id] = _Manual(manual, pages, specs)

    def remove(self, manual_id: str) -> None:
        with self._lock:
            self._built.pop(manual_id, None)

    def built(self, manual_id: str) -> _Manual | None:
        with self._lock:
            hit = self._built.get(manual_id)
        if hit is not None:
            return hit
        from ..store import get_store

        store = get_store()
        manual = store.manual(manual_id)
        if manual is None:
            return None
        self.index(manual, store.pages(manual_id), store.specs(manual_id))
        with self._lock:
            return self._built.get(manual_id)

    def query(self, manual_id: str, queries: list[str], components: list[str] | None = None, k: int = 8) -> list[Hit]:
        built = self.built(manual_id)
        if built is None or built.bm25 is None:
            return []
        clean = [q for q in queries if q and q.strip()]
        if not clean:
            return []

        totals = [0.0] * len(built.ids)
        peak = 0.0
        for query in clean:
            tokens = canon(query)
            if not tokens:
                continue
            scores = built.bm25.get_scores(tokens)
            top = max(scores) if len(scores) else 0.0
            if top <= 0:
                continue
            peak = max(peak, float(top))
            for i, s in enumerate(scores):
                totals[i] += max(0.0, float(s)) / top

        normalized = [normalize(q) for q in clean]
        sequences = [canon(q) for q in clean]
        asked: set[str] = set()
        for seq in sequences:
            asked.update(seq)
        component_tokens: set[str] = set()
        for component in components or []:
            component_tokens.update(canon(component))
        side = side_of(asked | component_tokens)

        evidence = False
        for i in range(len(built.ids)):
            for raw, seq in built.keywords[i]:
                if not seq:
                    continue
                if any(f" {raw} " in f" {n} " for n in normalized) or any(contiguous(s, seq) for s in sequences):
                    totals[i] += KEYWORD_BONUS
                    evidence = True
                    break
            title = built.titles[i]
            if title:
                cover = len(asked & title) / len(title)
                totals[i] += TITLE_COVER * cover
                evidence = evidence or cover >= TITLE_EVIDENCE
            if component_tokens:
                totals[i] += COMPONENT_BONUS * len(component_tokens & title)
            if side and built.sides[i] and built.sides[i] != side:
                totals[i] *= SIDE_PENALTY

        # A weak BM25 peak only means "no match" when the rider's own words match no printed title or
        # keyword either: one bare word ("torque") collapses the IDF of a word every section uses, and its
        # exact keyword hit must still get to vote. Components never rescue on their own: they are a router
        # guess, not something the manual prints.
        if peak < FLOOR and not evidence:
            return []
        best = max(totals) if totals else 0.0
        if best <= 0:
            return []
        ranked = sorted(
            (Hit(sectionId=built.ids[i], score=min(1.0, totals[i] / best)) for i in range(len(built.ids)) if totals[i] > 0),
            key=lambda h: -h.score,
        )
        return ranked[:k]

    def spec(self, manual_id: str, name: str, kind: str | None = None, k: int = 5) -> list[SpecHit]:
        built = self.built(manual_id)
        if built is None or not built.specs:
            return []
        wanted = set(canon(name))
        if not wanted and not kind:
            return []
        hits: list[SpecHit] = []
        for spec in built.specs:
            tokens = set(canon(spec.name))
            overlap = len(wanted & tokens)
            if wanted and not overlap:
                continue
            score = overlap / len(wanted) if wanted else 0.0
            if kind:
                score = score + 0.3 if spec.kind == kind else score * 0.7
            if score <= 0:
                continue
            hits.append(SpecHit(spec=spec, score=min(1.0, score)))
        hits.sort(key=lambda h: -h.score)
        return hits[:k]

    def snippet(self, manual_id: str, section_id: str, chars: int = 300) -> str:
        built = self.built(manual_id)
        return built.snippet(section_id, chars) if built else ""

"""BM25 over section text + keywords, in memory, rebuilt from the store on first use.

Tokenisation mirrors src/lib/match.ts (same phrases, stopwords, synonym groups, stemmer) so the backend
understands exactly the rider vocabulary the client matcher understood, plus the page text it never had.
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
    ["oil", "lube", "lubricant", "lubrication", "lubricate", "grease"],
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
    ["headlight", "headlamp", "beam", "light", "bulb"],
    ["pressure", "psi", "bar", "inflate", "inflation"],
    ["wheel", "rim"],
    ["clutch"],
    ["front"],
    ["rear", "back"],
    ["chain"],
    ["brake", "braking"],
    ["engine", "motor"],
    ["adjust", "adjustment", "set", "setting"],
    ["remove", "removal", "detach", "dismount"],
    ["install", "installation", "mount", "fit", "refit"],
    ["clean", "cleaning", "wash"],
    ["level", "amount", "quantity"],
    ["wear", "worn", "thickness"],
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
TITLE_WEIGHT = 3
KEYWORD_WEIGHT = 2


class _Manual:
    def __init__(self, manual: Manual, pages: list[Page], specs: list[Spec]):
        by_page = {p.page: p.text for p in pages}
        self.ids: list[str] = []
        self.keywords: list[list[tuple[str, list[str]]]] = []
        self.titles: list[set[str]] = []
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
            self.titles.append(set(canon(section.title)))
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
        for query in clean:
            tokens = canon(query)
            if not tokens:
                continue
            scores = built.bm25.get_scores(tokens)
            top = max(scores) if len(scores) else 0.0
            if top <= 0:
                continue
            for i, s in enumerate(scores):
                totals[i] += max(0.0, float(s)) / top

        normalized = [normalize(q) for q in clean]
        sequences = [canon(q) for q in clean]
        component_tokens: set[str] = set()
        for component in components or []:
            component_tokens.update(canon(component))

        for i in range(len(built.ids)):
            for raw, seq in built.keywords[i]:
                if not seq:
                    continue
                if any(f" {raw} " in f" {n} " for n in normalized) or any(contiguous(s, seq) for s in sequences):
                    totals[i] += KEYWORD_BONUS
                    break
            if component_tokens:
                totals[i] += COMPONENT_BONUS * len(component_tokens & built.titles[i])

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

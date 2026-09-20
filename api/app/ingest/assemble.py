"""Units -> Sections, Specs and Parts. Anything that is not printed on the page does not survive this file."""

import re
from itertools import zip_longest
from urllib.parse import quote_plus

import pymupdf

from ..models import Highlight, Link, Part, Section, Spec
from . import ground, pages as pagelib
from .ground import PageText
from .structure import UnitOut

SHOPS = (
    ("RevZilla", "https://www.revzilla.com/search?query={}"),
    ("Partzilla", "https://www.partzilla.com/search?q={}"),
    ("Amazon", "https://www.amazon.com/s?k={}"),
)

OEM_PATTERNS = (
    re.compile(r"\b\d{2}\s\d{2}\s\d\s\d{3}\s\d{3}\b"),
    re.compile(r"\b[A-Z]\d{9,12}\b"),
    re.compile(r"\b\d{9,12}\b"),
    re.compile(r"\b\d{2}[.-]\d{3}[.-]\d{3}[.-]\d{2,3}\b"),
)

MAX_SPAN = 5
MAX_RELATED = 4
MAX_PART_IDS = 6

_NUM_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")
_SKIP_WORDS = {"the", "a", "an", "of", "and", "for", "to", "in", "on", "with", "your", "its"}
_UNITS = {
    "nm", "lbf", "ft", "bar", "psi", "kpa", "mm", "cm", "in", "l", "ml", "qt", "oz", "fl",
    "v", "ah", "a", "w", "km", "mi", "kg", "lb", "min", "max", "approx",
}
_BRANDY = re.compile(r"[A-Z][A-Za-z]{2,}|[A-Za-z]+[0-9]|[0-9]+[A-Za-z]{2,}")
_MARKS = re.compile(r"[®™℠]")


def slug(text: str, limit: int = 52) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(out) <= limit:
        return out or "section"
    cut = out[:limit].rsplit("-", 1)[0]
    return (cut or out[:limit]).strip("-") or "section"


def short_id(title: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", title) if w and w.lower() not in _SKIP_WORDS]
    return slug(" ".join(words) or title)


def clean_title(title: str) -> str:
    return pagelib.clean(_NUM_PREFIX.sub("", title)).strip(" .:-")


class Built:
    def __init__(self) -> None:
        self.sections: list[Section] = []
        self.specs: list[Spec] = []
        self.parts: list[Part] = []


class _Draft:
    def __init__(self, unit: UnitOut, title: str) -> None:
        self.title = title
        self.kind = unit.kind
        self.start = unit.pageStart
        self.end = max(unit.pageEnd, unit.pageStart)
        self.quotes: list[str] = list(unit.quotes)
        self.components: set[str] = {c.strip().lower() for c in unit.components if len(c.strip()) > 2}
        self.specs = list(unit.specs)
        self.parts = list(unit.parts)

    def absorb(self, unit: UnitOut) -> None:
        self.end = max(self.end, unit.pageEnd, unit.pageStart)
        self.quotes.extend(unit.quotes)
        self.components.update(c.strip().lower() for c in unit.components if len(c.strip()) > 2)
        self.specs.extend(unit.specs)
        self.parts.extend(unit.parts)


def drafts(units: list[UnitOut], page_count: int, chaps: list[tuple[int, int, str]]) -> list[_Draft]:
    ordered: list[_Draft] = []
    for unit in units:
        title = clean_title(unit.title)
        if len(title) < 3 or len(title) > 120:
            continue
        unit.pageStart = max(1, min(unit.pageStart, page_count))
        unit.pageEnd = max(unit.pageStart, min(unit.pageEnd, page_count))
        last = ordered[-1] if ordered else None
        chapter = pagelib.chapter_of(chaps, unit.pageStart)
        echo = ground.norm(title) == ground.norm(clean_title(chapter))
        if last and unit.pageStart <= last.end + 1:
            same = ground.norm(last.title) == ground.norm(title)
            echo = echo and pagelib.chapter_of(chaps, last.start) == chapter
            if same or echo or (unit.continuesPrevious and ground.norm(title) in ground.norm(last.title)):
                last.absorb(unit)
                continue
            if unit.continuesPrevious:
                twin = next((d for d in reversed(ordered) if ground.norm(d.title) == ground.norm(title)), None)
                if twin and unit.pageStart <= twin.end + 1:
                    twin.absorb(unit)
                    continue
        if echo and not last:
            continue
        ordered.append(_Draft(unit, title))
    return ordered


_BOILERPLATE = re.compile(
    r"^\W*(warning|caution|note|info|danger|attention|risk of|danger of|environmental hazard|"
    r"possible consequence|preventive measure|condition|preparatory work|main work|finishing work|guideline)\b",
    re.I,
)


def _interleave(draft: "_Draft") -> list[str]:
    """Steps and printed values both deserve a marker; alternate so neither is squeezed out by the cap."""
    values = [q for pair in zip_longest([s.quote for s in draft.specs], [p.quote for p in draft.parts]) for q in pair if q]
    out: list[str] = []
    for i in range(max(len(draft.quotes), len(values))):
        if i < len(values):
            out.append(values[i])
        if i < len(draft.quotes):
            out.append(draft.quotes[i])
    return out


def _texts(cache: dict[int, PageText], doc: pymupdf.Document, page_no: int) -> PageText:
    if page_no not in cache:
        cache[page_no] = PageText(doc[page_no - 1])
    return cache[page_no]


def locate(cache, doc, quote: str, scope: range, heading: bool = False) -> tuple[Highlight, int] | None:
    for page_no in scope:
        if 1 <= page_no <= doc.page_count:
            hit = _texts(cache, doc, page_no).highlight(quote, heading)
            if hit:
                return hit, page_no
    return None


def _spec_value(spec) -> str:
    value = pagelib.clean(spec.value)
    unit = pagelib.clean(spec.unit or "")
    if unit and unit.lower() not in value.lower():
        value = f"{value} {unit}".strip()
    return value


def _oem(text: str) -> str | None:
    for pattern in OEM_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(0)
    return None


def _fragments(spec: str) -> list[str]:
    out = []
    for raw in re.split(r"[;,]|\s+-\s+", _MARKS.sub("", spec)):
        frag = pagelib.clean(raw).strip(" .;,:-")
        if len(frag) > 1 and frag not in out:
            out.append(frag)
    return out


def _brandy(fragment: str) -> int:
    score = 0
    for word in fragment.split():
        bare = word.strip("().,:;").lower()
        if not bare or bare in _UNITS or bare.replace(".", "").replace(",", "").isdigit():
            continue
        if _BRANDY.search(word.strip("().,:;")):
            score += 3 if word[:1].isupper() else 1
    return score


def _head_noun(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z]+", name) if len(w) > 2 and w.lower() not in _SKIP_WORDS]
    return words[-1].lower() if words else ""


def _query(name: str, spec: str, oem: str | None) -> str:
    if oem:
        return oem
    frags = _fragments(spec) or [pagelib.clean(name)]
    best = max(frags, key=lambda f: (_brandy(f), len(f)))
    if _brandy(best) == 0:
        best = f"{_MARKS.sub('', pagelib.clean(name))} {best}"
    words = best.split()[:7]
    noun = _head_noun(name)
    if noun and noun not in " ".join(words).lower():
        words.append(noun)
    return " ".join(words).strip()


def links(query: str) -> list[Link]:
    encoded = quote_plus(query)
    return [Link(shop=shop, url=url.format(encoded)) for shop, url in SHOPS]


class _PartRow:
    def __init__(self, name: str, spec: str, page: int, oem: str | None, tags: set[str]) -> None:
        self.name = name
        self.frags: list[tuple[str, int]] = [(f, page) for f in _fragments(spec)]
        self.page = page
        self.oem = oem
        self.tags = set(tags)

    def merge(self, name: str, spec: str, page: int, oem: str | None, tags: set[str]) -> None:
        if name[:1].isupper() and not self.name[:1].isupper():
            self.name = name
        known = {ground.norm(f) for f, _ in self.frags}
        for frag in _fragments(spec):
            if ground.norm(frag) not in known:
                self.frags.append((frag, page))
                known.add(ground.norm(frag))
        self.oem = self.oem or oem
        self.tags |= tags

    def part(self, part_id: str) -> Part | None:
        ranked = sorted(self.frags, key=lambda f: (-_brandy(f[0]), -len(f[0])))
        useful = [f for f in ranked if ground.norm(f[0]) != ground.norm(self.name)]
        chosen = useful or ranked
        if not chosen or (not useful and not self.oem):
            return None
        spec = "; ".join(dict.fromkeys(f for f, _ in chosen))[:160].strip("; ")
        return Part(
            id=part_id,
            name=self.name[:80],
            spec=spec,
            page=chosen[0][1],
            oem=self.oem,
            links=links(_query(self.name, spec, self.oem)),
        )


def _shared(a: set[str], b: set[str], rare: set[str]) -> int:
    return len(a & b & rare)


def build(doc: pymupdf.Document, units: list[UnitOut], chaps: list[tuple[int, int, str]], keyword_fn, progress=None) -> Built:
    """progress(done, total) is called while quotes are grounded; it is the longest stretch after the LLM pass."""
    out = Built()
    cache: dict[int, PageText] = {}
    page_count = doc.page_count
    kept: list[tuple[_Draft, Section]] = []
    rows: dict[str, _PartRow] = {}
    used_ids: dict[str, int] = {}

    todo = drafts(units, page_count, chaps)
    for index, draft in enumerate(todo, start=1):
        if progress:
            progress(index, len(todo))
        start = max(1, draft.start)
        scope = range(start, min(page_count, max(draft.end, start + 1), start + MAX_SPAN) + 1)
        highlights: list[Highlight] = []
        seen: set[str] = set()
        title_key = ground.norm(draft.title)
        for quote in [draft.title] + _interleave(draft):
            if _BOILERPLATE.match(quote.strip()):
                continue
            key = ground.norm(quote)
            if not key or key in seen:
                continue
            seen.add(key)
            if key != title_key and key.endswith(title_key):
                continue
            hit = locate(cache, doc, quote, scope, heading=key == title_key)
            if hit:
                highlights.append(hit[0])
        highlights = ground.cap(highlights)
        if not highlights:
            continue
        first = min(h.page for h in highlights)
        last = max(max(h.page for h in highlights), min(draft.end, first + MAX_SPAN))
        base = short_id(draft.title)
        used_ids[base] = used_ids.get(base, 0) + 1
        section_id = base if used_ids[base] == 1 else f"{base}-{first}"
        while any(s.id == section_id for _, s in kept):
            section_id = f"{section_id}-{used_ids[base]}"
        section = Section(
            id=section_id,
            title=draft.title,
            chapter=pagelib.chapter_of(chaps, first),
            pageStart=first,
            pageEnd=min(last, page_count),
            keywords=[],
            highlights=highlights,
            partIds=None,
            related=None,
        )
        kept.append((draft, section))

        for spec in draft.specs:
            value, name = _spec_value(spec), pagelib.clean(spec.name)
            if not name or not value:
                continue
            hit = locate(cache, doc, spec.quote, scope)
            if hit:
                out.specs.append(
                    Spec(
                        sectionId=section_id,
                        name=name[:80],
                        kind=spec.kind,
                        value=value[:80],
                        unit=pagelib.clean(spec.unit or "")[:24] or None,
                        page=hit[1],
                        quote=pagelib.clean(spec.quote)[:300],
                    )
                )

        for part in draft.parts:
            name, spec_text = pagelib.clean(part.name), pagelib.clean(part.spec)
            if len(name) < 3 or not spec_text:
                continue
            hit = locate(cache, doc, part.quote, scope)
            if not hit:
                continue
            oem = _oem(pagelib.clean(part.quote)) or _oem(spec_text)
            tags = {ground.norm(name)} | {c for c in draft.components if _touches(c, name)}
            key = f"{ground.norm(name)}|{oem or ''}"
            if key in rows:
                rows[key].merge(name, spec_text, hit[1], oem, tags)
            else:
                rows[key] = _PartRow(name, spec_text, hit[1], oem, tags)

    part_ids: dict[str, str] = {}
    for key, row in rows.items():
        base = slug(f"{row.name}-{row.oem[-4:]}" if row.oem else row.name, 40)
        candidate, n = base, 1
        while candidate in part_ids.values():
            n += 1
            candidate = f"{base}-{n}"
        built = row.part(candidate)
        if built:
            part_ids[key] = candidate
            out.parts.append(built)

    out.sections = sections = [s for _, s in kept]
    for section, words in zip(sections, keyword_fn([s.title for s in sections])):
        section.keywords = words or [ground.norm(section.title)]

    freq: dict[str, int] = {}
    for draft, _ in kept:
        for component in draft.components:
            freq[component] = freq.get(component, 0) + 1
    ceiling = max(3, len(kept) // 8)
    rare = {c for c, n in freq.items() if n <= ceiling}

    tables = [(d, s) for d, s in kept if d.kind == "spec_table"]
    procedures = [(d, s) for d, s in kept if d.kind != "spec_table"]
    for draft, section in kept:
        pool = procedures if draft.kind == "spec_table" else tables
        scored = [
            (_shared(draft.components, other_draft.components, rare), -abs(other.pageStart - section.pageStart), other.id)
            for other_draft, other in pool
            if other.id != section.id
        ]
        related = [r[2] for r in sorted(scored, reverse=True) if r[0] > 0][:MAX_RELATED]
        section.related = related or None
        owned = [
            (len(rows[key].tags & draft.components & rare), part_id)
            for key, part_id in part_ids.items()
            if rows[key].tags & draft.components & rare or _touches(ground.norm(rows[key].name), draft.title)
        ]
        section.partIds = [p for _, p in sorted(owned, reverse=True)][:MAX_PART_IDS] or None
    return out


def _touches(component: str, text: str) -> bool:
    words = {w for w in re.split(r"[^a-z0-9]+", ground.norm(text)) if len(w) > 2}
    needle = {w for w in re.split(r"[^a-z0-9]+", ground.norm(component)) if len(w) > 2}
    return bool(needle) and needle <= words

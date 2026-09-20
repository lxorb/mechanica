"""PDF -> Page models, outline, cover title. Nothing here calls an LLM."""

import re
import unicodedata

import pymupdf

from ..models import Block, OutlineNode, Page

_WS = re.compile(r"\s+")
_TOC_CHAPTER = re.compile(r"table of contents|^contents$|^index$|^inhalt", re.I)


def clean(text: str) -> str:
    return _WS.sub(" ", text.replace(r"\&", "&").replace("­", "")).strip()


def extract_pages(doc: pymupdf.Document, manual_id: str, progress=None) -> list[Page]:
    out: list[Page] = []
    for n, page in enumerate(doc, start=1):
        w, h = page.rect.width or 1.0, page.rect.height or 1.0
        matrix = page.rotation_matrix
        boxes = [
            (b[4].strip(), (pymupdf.Rect(b[0], b[1], b[2], b[3]) * matrix).normalize())
            for b in page.get_text("blocks")
            if len(b) > 6 and b[6] == 0 and b[4].strip()
        ]
        blocks = [
            Block(
                text=text,
                x=round(min(max(r.x0 / w, 0.0), 1.0), 4),
                y=round(min(max(r.y0 / h, 0.0), 1.0), 4),
                w=round(min(r.width / w, 1.0), 4),
                h=round(min(r.height / h, 1.0), 4),
            )
            for text, r in boxes
        ]
        out.append(Page(manualId=manual_id, page=n, width=round(w, 2), height=round(h, 2), text=page.get_text(), blocks=blocks))
        if progress and n % 10 == 0:
            progress(n)
    if progress:
        progress(len(out))
    return out


def toc(doc: pymupdf.Document) -> list[tuple[int, str, int]]:
    items: list[tuple[int, str, int]] = []
    for entry in doc.get_toc() or []:
        level, title, page = int(entry[0]), clean(str(entry[1])), int(entry[2])
        if title and page >= 1:
            items.append((level, title, min(page, doc.page_count)))
    return items


def outline(items: list[tuple[int, str, int]]) -> list[OutlineNode]:
    roots: list[OutlineNode] = []
    stack: list[tuple[int, OutlineNode]] = []
    for level, title, page in items:
        node = OutlineNode(title=title, page=page)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            parent.children = (parent.children or []) + [node]
        else:
            roots.append(node)
        stack.append((level, node))
    return roots


MIN_CHAPTERS = 3
_EXTENSION = re.compile(r"\.(pdf|docx?|indd|ai|xml|txt)$", re.I)


def filename_like(title: str) -> bool:
    """Honda and GM ship outlines whose only top node is the production filename. It must never reach a rider."""
    text = " ".join((title or "").split())
    if not text:
        return True
    if _EXTENSION.search(text):
        return True
    digits = sum(c.isdigit() for c in text)
    if " " not in text and ("_" in text or digits >= 4):
        return True
    longest = max((len(w) for w in text.split()), default=0)
    return digits >= 8 and longest >= 12


def _ranges(entries: list[tuple[int, str]], page_count: int) -> list[tuple[int, int, str]]:
    ordered = sorted(entries, key=lambda x: x[0])
    out = []
    for i, (page, title) in enumerate(ordered):
        end = ordered[i + 1][0] - 1 if i + 1 < len(ordered) else page_count
        out.append((page, max(end, page), title))
    return out


def chapters(items: list[tuple[int, str, int]], page_count: int) -> list[tuple[int, int, str]]:
    """(pageStart, pageEnd, title) per chapter, taken from the shallowest outline level that is actually usable.

    Level 1 is the right answer for a normal manual. When it is a single filename node (Honda scooters, GM cars)
    or too thin to group anything, the printed structure is one level down, so drop to it rather than invent one.
    Sorted by page throughout: Honda's US outlines end with a broken 'Index' pointing at page 1, and in document
    order that entry would claim the whole manual.
    """
    for level in (1, 2, 3):
        entries = [(p, t) for lvl, t, p in items if lvl == level]
        if len(entries) < MIN_CHAPTERS or any(filename_like(t) for _, t in entries):
            continue
        return _ranges(entries, page_count)
    clean = [(p, t) for _, t, p in items if not filename_like(t)]
    return _ranges(clean, page_count) if len(clean) >= MIN_CHAPTERS else []


_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.)]?\s+([A-Z][^\d].{2,58})$")
_CALLOUT = re.compile(r"\(\s*\d+\s*\)")
MAX_HEADING = 60


def _headingish(line: str) -> bool:
    """A figure's callout list is set in the same type as a heading on some pages: '(2) Adjusting nut (4) Brake arm'."""
    return (
        4 <= len(line) <= MAX_HEADING
        and len(_CALLOUT.findall(line)) == 0
        and not filename_like(line)
        and not _BOILER.match(line)
        and not garbled(line)
    )


def text_chapters(doc: pymupdf.Document) -> list[tuple[int, int, str]]:
    """No usable outline: read the chapter titles the manual prints, biggest type first. Never an LLM call."""
    tops: list[tuple[int, float, str]] = []
    for n in range(doc.page_count):
        best: tuple[float, str] | None = None
        for size, text in _candidates(doc[n]):
            line = " ".join(text.split())
            if _headingish(line):
                best = (size, line)
                break
        if best:
            tops.append((n + 1, best[0], best[1]))
    if not tops:
        return []

    numbered = [(p, m.group(2).strip()) for p, _, t in tops if (m := _NUMBERED.match(t))]
    if len(numbered) >= MIN_CHAPTERS:
        return _ranges(_dedupe(numbered), doc.page_count)

    # Not the biggest type in the book - the type that carries the most distinct chapter names (the running head).
    buckets: dict[float, list[tuple[int, str]]] = {}
    for page, size, title in tops:
        buckets.setdefault(round(size, 1), []).append((page, title))
    best = max(
        (_dedupe(entries) for entries in buckets.values()),
        key=lambda entries: (min(len(entries), 40), -entries[0][0]),
        default=[],
    )
    return _ranges(best, doc.page_count) if len(best) >= MIN_CHAPTERS else []


def _dedupe(entries: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """A chapter starts once: a heading repeated as a running head on every page is not a new chapter."""
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    for page, title in sorted(entries, key=lambda x: x[0]):
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((page, title))
    return out


def chapter_of(chaps: list[tuple[int, int, str]], page: int) -> str:
    best = ""
    for start, end, title in chaps:
        if start <= page <= end:
            best = title
    return best


def headings_for(items: list[tuple[int, str, int]], start: int, end: int) -> list[str]:
    return [f"{t} (p{p})" for lvl, t, p in items if start <= p <= end and lvl > 1][:12]


MAX_SKIP = 0.6


def skip_pages(items: list[tuple[int, str, int]], chaps: list[tuple[int, int, str]], page_count: int) -> set[int]:
    """Front matter, table of contents and index: never worth an LLM call.

    A malformed outline must never cost us the manual, so if the chapter-based skips would swallow most of
    the book the outline is not trusted and only the front matter is dropped.
    """
    front = {p for p in range(1, min(min((p for _, _, p in items), default=1), 5)) if p >= 1}
    dead = set(front)
    for start, end, title in chaps:
        if _TOC_CHAPTER.search(title):
            dead.update(range(start, end + 1))
    dead = {p for p in dead if 1 <= p <= page_count}
    if page_count and len(dead) > MAX_SKIP * page_count:
        return {p for p in front if 1 <= p <= page_count}
    return dead


COVER_PAGES = 6
MAX_TITLE = 90

_BOILER = re.compile(
    r"^(warning|caution|danger|notice|attention|important|hazard|foreword|preface|introduction|intro"
    r"|welcome|congratulations|contents?|table of contents|index|imprint|disclaimer|copyright|notes?"
    r"|safety|read this|before you ride|proposition 65|california)\b",
    re.I,
)
_WEIRD = re.compile(r"[^0-9A-Za-zÀ-ɏ\s'‘’\-./,()&+:;®™°#]")
_ARTNO = re.compile(r"\s*\b(art(icle)?\.?\s*no\.?|part\s*no\.?|item\s*no\.?|p/?n)\b\s*:?.*$", re.I)
_TOKEN = re.compile(r"[A-Za-z0-9]+")


MANUALISH = {"manual", "manuals", "handbook", "instruction", "instructions", "booklet", "guide"}


def _tokens(text: str) -> list[str]:
    """Accent-folded: a cover prints 'Ténéré 700' where the registry says 'Tenere 700'."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return [t.lower() for t in _TOKEN.findall(folded)]


def _squash(text: str) -> str:
    """'MTN690 (MT-07)' and 'MT07' have to compare equal: covers print the model with its own punctuation."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return "".join(c for c in folded.lower() if c.isalnum())


GENERIC = {
    "a", "s", "the", "and", "for", "owner", "owners", "rider", "riders", "driver", "manual", "manuals",
    "handbook", "instruction", "instructions", "book", "booklet", "motorcycle", "motorcycles", "motorbike",
    "vehicle", "english", "en", "original", "operating", "operation", "user", "guide", "edition",
}


def garbled(text: str) -> bool:
    """A cover set in a symbol font extracts as noise: 'HF4\"64?<9BEA<4'. Never show that to a rider."""
    if not text:
        return True
    if len(_WEIRD.findall(text)) / len(text) > 0.10:
        return True
    words = [w.lower() for w in _TOKEN.findall(text) if len(w) >= 4 and w.isalpha()]
    return bool(words) and not any(set(w) & set("aeiouy") for w in words)


def generic(text: str, make: str) -> bool:
    """'OWNER'S MANUAL' names no bike: five Honda manuals carried that same header."""
    rest = {t for t in _tokens(text) if t not in GENERIC and not re.fullmatch(r"(19|20)\d{2}", t)}
    return not (rest - set(_tokens(make)))


def _candidates(page: pymupdf.Page) -> list[tuple[float, str]]:
    spans = [
        (round(s["size"], 1), s["text"], round(s["bbox"][1], 1), s["bbox"][0])
        for b in page.get_text("dict")["blocks"]
        if b.get("type") == 0
        for line in b["lines"]
        for s in line["spans"]
        if s["text"].strip()
    ]
    if not spans:
        return []
    out: list[tuple[float, str]] = []
    for size in sorted({s[0] for s in spans}, reverse=True)[:3]:
        picked = sorted((s for s in spans if abs(s[0] - size) <= 0.6), key=lambda s: (s[2], s[3]))
        text = _ARTNO.sub("", clean(" ".join(s[1] for s in picked))).strip(" .-|")
        if text:
            out.append((size, text))
    return out


def _usable(text: str) -> bool:
    return 4 <= len(text) <= MAX_TITLE and bool(re.search(r"[A-Za-z]", text)) and not garbled(text) and not _BOILER.match(text)


def cover_title(doc: pymupdf.Document, make: str, model: str, year: int) -> str:
    """The title printed on the cover, never a warning block, never font noise, never the same for two bikes."""
    want = [t for t in _tokens(model) if t not in {"the", "and"}]
    maker = _tokens(make)[:1]
    squashed = _squash(model)

    def scores(text: str) -> tuple[bool, int]:
        got = set(_tokens(text))
        has_model = bool(want) and sum(1 for t in want if t in got) >= max(1, (len(want) + 1) // 2)
        if not has_model and len(squashed) >= 4:
            has_model = squashed in _squash(text)
        score = (4 if has_model else 0) + (2 if got & MANUALISH else 0)
        score += 1 if str(year) in got else 0
        score += 1 if maker and maker[0] in got else 0
        return has_model, score

    def namelike(text: str) -> bool:
        """Without the model, a cover line is only a title if it says whose manual it is: 'Canada' is not one."""
        got = set(_tokens(text))
        return bool(got & MANUALISH) or bool(maker and maker[0] in got)

    best: tuple[int, float, str, bool] | None = None
    for n in range(min(COVER_PAGES, doc.page_count)):
        page = doc[n]
        found = [(size, text) for size, text in _candidates(page) if _usable(text)]
        for size, text in found:
            has_model, score = scores(text)
            joined, joined_model = text, has_model
            if not has_model:
                for other_size, other in found:
                    if other is not text and other_size >= size * 0.3 and scores(other)[0]:
                        joined = clean(f"{text} {other}")[:MAX_TITLE].strip()
                        joined_model = True
                        score += 4
                        break
            if not joined_model and (n > 1 or not namelike(joined)):
                continue  # past the cover it is a chapter heading; on it, a line naming nothing is not a title
            if best is None or (score, size) > (best[0], best[1]):
                best = (score, size, joined, joined_model)
        if best is not None and best[0] >= 4:
            break

    fallback = clean(f"{make} {model} {year} Owner's Manual".replace(" 0 ", " "))[:MAX_TITLE].strip()
    if best is None:
        meta = clean(doc.metadata.get("title") or "")
        if _usable(meta) and not generic(meta, make):
            return meta[:MAX_TITLE]
        return fallback if (make or model) else "Owner's Manual"
    text = best[2]
    if generic(text, make) and (make or model):
        return fallback
    return text

"""PDF -> Page models, outline, cover title. Nothing here calls an LLM."""

import re

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
        blocks = [
            Block(
                text=b[4].strip(),
                x=round(b[0] / w, 4),
                y=round(b[1] / h, 4),
                w=round((b[2] - b[0]) / w, 4),
                h=round((b[3] - b[1]) / h, 4),
            )
            for b in page.get_text("blocks")
            if len(b) > 6 and b[6] == 0 and b[4].strip()
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


def chapters(items: list[tuple[int, str, int]], page_count: int) -> list[tuple[int, int, str]]:
    """(pageStart, pageEnd, title) for every top-level outline entry."""
    tops = [(p, t) for lvl, t, p in items if lvl == 1]
    out = []
    for i, (page, title) in enumerate(tops):
        end = tops[i + 1][0] - 1 if i + 1 < len(tops) else page_count
        out.append((page, max(end, page), title))
    return out


def chapter_of(chaps: list[tuple[int, int, str]], page: int) -> str:
    best = ""
    for start, end, title in chaps:
        if start <= page <= end:
            best = title
    return best


def headings_for(items: list[tuple[int, str, int]], start: int, end: int) -> list[str]:
    return [f"{t} (p{p})" for lvl, t, p in items if start <= p <= end and lvl > 1][:12]


def skip_pages(items: list[tuple[int, str, int]], chaps: list[tuple[int, int, str]], page_count: int) -> set[int]:
    """Front matter, table of contents and index: never worth an LLM call."""
    dead: set[int] = set()
    first = min((p for _, _, p in items), default=1)
    dead.update(range(1, min(first, 5)))
    for start, end, title in chaps:
        if _TOC_CHAPTER.search(title):
            dead.update(range(start, end + 1))
    return {p for p in dead if 1 <= p <= page_count}


def cover_title(doc: pymupdf.Document, make: str, model: str, year: int) -> str:
    for n in range(min(3, doc.page_count)):
        spans = [
            (round(s["size"], 1), s["text"], s["bbox"][1], s["bbox"][0])
            for b in doc[n].get_text("dict")["blocks"]
            if b.get("type") == 0
            for line in b["lines"]
            for s in line["spans"]
            if s["text"].strip()
        ]
        if not spans:
            continue
        top = max(s[0] for s in spans)
        picked = [s for s in spans if s[0] >= top - 0.6]
        picked.sort(key=lambda s: (round(s[2], 1), s[3]))
        title = clean(" ".join(s[1] for s in picked))
        title = re.sub(r"\s*\b(art\.?\s*no\.?|part\s*no\.?)\b.*$", "", title, flags=re.I).strip(" .-|")
        if len(title) >= 4 and len(title) <= 90 and re.search(r"[A-Za-z]", title):
            return title
    meta = clean(doc.metadata.get("title") or "")
    return meta if 4 <= len(meta) <= 90 else f"{make} {model} {year}".strip()

"""Every highlight must come from the PDF text layer. A quote that cannot be found is dropped."""

import re

import pymupdf

from ..models import Highlight

PAD = 0.004
MAX_H = 0.15
MAX_PER_PAGE = 4

_WS = re.compile(r"\s+")
_FOLD = {
    0x00AD: "",
    0x200B: "",
    0x00A0: " ",
    0x2010: "-",
    0x2011: "-",
    0x2012: "-",
    0x2013: "-",
    0x2014: "-",
    0x2212: "-",
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
    0x02BC: "'",
}
_TRIM = " \t\r\n.:;,-*•–—»«>|"


def fold(text: str) -> str:
    return _WS.sub(" ", text.translate(_FOLD)).strip()


def norm(text: str) -> str:
    return fold(text).lower()


def displayed(rect, matrix: pymupdf.Matrix) -> pymupdf.Rect:
    """Text extraction reports the unrotated page. pdf.js renders the rotated one, so highlights live there."""
    return (pymupdf.Rect(rect) * matrix).normalize()


class PageText:
    """Line index of one page, built once and reused for every quote."""

    def __init__(self, page: pymupdf.Page):
        self.page = page
        self.matrix = page.rotation_matrix
        self.width = page.rect.width or 1.0
        self.height = page.rect.height or 1.0
        self.lines: list[tuple[str, pymupdf.Rect]] = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line.get("spans", []))
                if text.strip():
                    self.lines.append((text, displayed(line["bbox"], self.matrix)))
        spans: list[tuple[int, int, pymupdf.Rect]] = []
        parts: list[str] = []
        pos = 0
        for text, rect in self.lines:
            piece = norm(text)
            if not piece:
                continue
            if parts:
                pos += 1
            spans.append((pos, pos + len(piece), rect))
            pos += len(piece)
            parts.append(piece)
        self.spans = spans
        self.flat = " ".join(parts)

    def find(self, quote: str) -> list[pymupdf.Rect]:
        needle = fold(quote).strip(_TRIM)
        if len(needle) < 4:
            return []
        for variant in self._variants(needle):
            try:
                hits = self.page.search_for(variant)
            except Exception:
                hits = []
            if hits:
                return [displayed(h, self.matrix) for h in hits]
        return self._substring(needle)

    def _variants(self, needle: str):
        yield needle
        stripped = needle.rstrip(".;:,")
        if stripped != needle and len(stripped) >= 4:
            yield stripped
        if len(needle) > 70:
            cut = needle[:70].rsplit(" ", 1)[0]
            if len(cut) >= 20:
                yield cut

    def _substring(self, needle: str) -> list[pymupdf.Rect]:
        low = needle.lower()
        start = self.flat.find(low)
        if start < 0 and len(low) > 40:
            head = low[:40].rsplit(" ", 1)[0]
            start = self.flat.find(head)
            if start >= 0:
                low = head
        if start < 0:
            return []
        end = start + len(low)
        return [rect for a, b, rect in self.spans if a < end and b > start]

    def rect_for(self, quote: str, heading: bool = False) -> pymupdf.Rect | None:
        return block_rect(self.find(quote), self.height, heading)

    def highlight(self, quote: str, heading: bool = False) -> Highlight | None:
        rect = self.rect_for(quote, heading)
        return to_highlight(rect, self.page.number + 1, self.width, self.height) if rect else None


def _overlap(a: float, b: float, c: float, d: float) -> float:
    return min(b, d) - max(a, c)


def block_rect(rects: list[pymupdf.Rect], page_height: float, heading: bool = False) -> pymupdf.Rect | None:
    """search_for returns one rect per line fragment. Fuse them into the tightest run of lines.

    heading=True picks the run set in the biggest type, so a title never lands on the same words in the body.
    """
    rects = [r for r in rects if r.width > 0.5 and r.height > 0.5]
    if not rects:
        return None
    rects.sort(key=lambda r: (round(r.y0, 1), r.x0))
    lines: list[pymupdf.Rect] = []
    for r in rects:
        if lines and _overlap(lines[-1].y0, lines[-1].y1, r.y0, r.y1) > 0.4 * min(lines[-1].height, r.height):
            lines[-1] |= r
        else:
            lines.append(pymupdf.Rect(r))
    runs: list[list[pymupdf.Rect]] = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        gap = cur.y0 - prev.y1
        same_column = _overlap(prev.x0, prev.x1, cur.x0, cur.x1) > 0
        if same_column and -2.0 <= gap <= 1.0 * max(prev.height, cur.height):
            runs[-1].append(cur)
        else:
            runs.append([cur])
    best = max(runs, key=lambda run: max(r.height for r in run)) if heading else max(runs, key=len)
    rect = pymupdf.Rect(best[0])
    for r in best[1:]:
        rect |= r
    if rect.height > MAX_H * page_height:
        rect = pymupdf.Rect(best[0])
    return rect


def to_highlight(rect: pymupdf.Rect, page_no: int, width: float, height: float) -> Highlight:
    """Fractions of the rendered page, always inside 0..1: the viewer draws them straight."""
    x0 = min(max(rect.x0 / width, 0.0), 1.0)
    x1 = min(max(rect.x1 / width, 0.0), 1.0)
    y0 = min(max(rect.y0 / height - PAD, 0.0), 1.0)
    y1 = min(max(rect.y1 / height + PAD, 0.0), 1.0)
    return Highlight(
        page=page_no,
        x=round(x0, 4),
        y=round(y0, 4),
        w=round(min(x1 - x0, 1.0 - x0), 4),
        h=round(min(y1 - y0, MAX_H, 1.0 - y0), 4),
    )


def _iou(a: Highlight, b: Highlight) -> float:
    ix = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    iy = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    return inter / (a.w * a.h + b.w * b.h - inter)


def cap(highlights: list[Highlight]) -> list[Highlight]:
    kept: list[Highlight] = []
    per_page: dict[int, int] = {}
    for h in highlights:
        if h.w <= 0.005 or h.h <= 0.002 or h.h > MAX_H:
            continue
        if per_page.get(h.page, 0) >= MAX_PER_PAGE:
            continue
        if any(o.page == h.page and _iou(o, h) > 0.45 for o in kept):
            continue
        kept.append(h)
        per_page[h.page] = per_page.get(h.page, 0) + 1
    return sorted(kept, key=lambda h: (h.page, h.y, h.x))

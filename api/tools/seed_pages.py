"""Build Page + Spec rows for every manual already in the store.

Pages: PyMuPDF text and blocks, bboxes as fractions of the page.
Specs: values parsed out of the text under each section highlight.

Run: api/.venv/Scripts/python tools/seed_pages.py [manual_id ...]
"""

import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.models import Block, Manual, Page, Spec  # noqa: E402
from app.store import get_store  # noqa: E402

UNIT_KIND: dict[str, str] = {
    "nm": "torque",
    "lbf ft": "torque",
    "kgm": "torque",
    "l": "capacity",
    "ml": "capacity",
    "qt": "capacity",
    "cm³": "capacity",
    "bar": "pressure",
    "psi": "pressure",
    "kpa": "pressure",
    "mm": "clearance",
    "cm": "clearance",
    "in": "clearance",
    '"': "size",
    "a": "electrical",
    "ah": "electrical",
    "v": "electrical",
    "w": "electrical",
}

UNITS = sorted(UNIT_KIND, key=len, reverse=True)
VALUE = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(u) for u in UNITS) + r")(?![\w./-])",
    re.IGNORECASE,
)
GRADE = re.compile(r"\b(SAE\s?\d+W[\s/-]?\d+|DOT\s?\d(?:\.\d)?|API\s?[A-Z]{2}|JASO\s?[A-Z]{2}\d?|NGK\s?[A-Z0-9­-]+)", re.IGNORECASE)
TYRE = re.compile(r"\b(\d{2,3}/\d{2,3}\s?(?:[ZR]\s?)?\d{2}\b|\d\.\d{1,2}\"\s?[x×]\s?\d{2}\")")
THREAD = re.compile(r"^M\d+(\s?[x×]\s?[\d.]+)*$", re.IGNORECASE)
NOISE = re.compile(r"^[\s•■�–\-—(),.:;]*$")
POSITION = {"front", "rear", "left", "right", "solo", "both", "each"}


def fractional_blocks(page: pymupdf.Page) -> list[Block]:
    w, h = page.rect.width or 1.0, page.rect.height or 1.0
    out: list[Block] = []
    for x0, y0, x1, y1, text, _no, kind in page.get_text("blocks"):
        if kind != 0:
            continue
        clean = " ".join(text.split())
        if not clean:
            continue
        out.append(
            Block(
                text=clean,
                x=round(x0 / w, 4),
                y=round(y0 / h, 4),
                w=round((x1 - x0) / w, 4),
                h=round((y1 - y0) / h, 4),
            )
        )
    return out


def build_pages(manual: Manual, doc: pymupdf.Document) -> list[Page]:
    pages: list[Page] = []
    for i, page in enumerate(doc):
        pages.append(
            Page(
                manualId=manual.id,
                page=i + 1,
                width=round(page.rect.width, 2),
                height=round(page.rect.height, 2),
                text=page.get_text("text"),
                blocks=fractional_blocks(page),
            )
        )
    return pages


def highlight_text(doc: pymupdf.Document, page_no: int, x: float, y: float, w: float, h: float) -> str:
    if page_no < 1 or page_no > doc.page_count:
        return ""
    page = doc[page_no - 1]
    r = page.rect
    clip = pymupdf.Rect(x * r.width, y * r.height, (x + w) * r.width, (y + h) * r.height)
    return page.get_text("text", clip=clip)


def _join(label: list[str]) -> str:
    text = ""
    for line in label:
        if text.endswith("-"):
            text = text[:-1] + line
        elif text:
            text += " " + line
        else:
            text = line
    return " ".join(text.split()).strip(" ,.:;")


def parse_specs(section_id: str, title: str, page_no: int, text: str) -> list[Spec]:
    out: list[Spec] = []
    label: list[str] = []
    carry: list[str] = []
    fresh = True
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or NOISE.match(line):
            continue
        values: list[tuple[str, str, str]] = []
        for m in VALUE.finditer(line):
            unit = m.group(2)
            values.append((m.group(1).replace(",", "."), unit, UNIT_KIND[unit.lower()]))
        for m in GRADE.finditer(line):
            values.append((m.group(1), "", "grade"))
        for m in TYRE.finditer(line):
            values.append((m.group(1), "", "size"))
        if not values:
            if THREAD.match(line):
                continue
            if not fresh:
                carry = [ln for ln in label if len(ln.split()) > 2]
                label = []
                fresh = True
            label.append(line)
            continue
        if fresh and carry and line and _join(label).lower().strip(",.") in POSITION:
            label = carry + label
        fresh = False
        name = _join(label) or title
        for value, unit, kind in values:
            out.append(
                Spec(
                    sectionId=section_id,
                    name=name[:120],
                    kind=kind,  # type: ignore[arg-type]
                    value=f"{value} {unit}".strip(),
                    unit=unit or None,
                    page=page_no,
                    quote=line[:200],
                )
            )
    return out


def build_specs(manual: Manual, doc: pymupdf.Document) -> list[Spec]:
    seen: set[tuple[str, str, int]] = set()
    out: list[Spec] = []
    for section in manual.sections:
        for hl in section.highlights:
            text = highlight_text(doc, hl.page, hl.x, hl.y, hl.w, hl.h)
            for spec in parse_specs(section.id, section.title, hl.page, text):
                key = (spec.name.lower(), spec.value.lower(), spec.page)
                if key in seen:
                    continue
                seen.add(key)
                out.append(spec)
    return out


def seed(manual: Manual) -> tuple[int, int]:
    path = settings.data_dir / "pdf" / f"{manual.id}.pdf"
    if not path.exists():
        print(f"  no pdf at {path}")
        return 0, 0
    store = get_store()
    with pymupdf.open(path) as doc:
        pages = build_pages(manual, doc)
        specs = build_specs(manual, doc)
    store.put_pages(manual.id, pages)
    store.put_specs(manual.id, specs)
    return len(pages), len(specs)


def main() -> None:
    store = get_store()
    wanted = set(sys.argv[1:])
    manuals = [m for m in store.manuals() if not wanted or m.id in wanted]
    for manual in manuals:
        n_pages, n_specs = seed(manual)
        print(f"{manual.id}: {n_pages} pages, {n_specs} specs")
    if manuals:
        from app.search import get_index

        index = get_index()
        for manual in manuals:
            index.index(manual, store.pages(manual.id), store.specs(manual.id))


if __name__ == "__main__":
    main()

"""Recompute the cover title and the chapter of manuals already in the store. No re-ingest, no LLM call.

    python -m tools.retitle                       # titles: show what would change
    python -m tools.retitle --write               # titles: write them
    python -m tools.retitle --chapters            # chapters: show what would change
    python -m tools.retitle --chapters --write    # chapters: write them
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402

from app import ingest  # noqa: E402
from app.ingest import pages as pagelib  # noqa: E402
from app.store import get_store  # noqa: E402


def bike_of(manual):
    store = get_store()
    for bike_id in manual.bikeIds:
        bike = store.bike(bike_id)
        if bike is not None:
            return bike.make, bike.model, bike.year
    return "", "", 0


def unusable(chapters: list[str], sections: int) -> bool:
    """A chapter set nobody can navigate: the production filename, or one bucket holding the whole manual."""
    distinct = {c for c in chapters if c}
    if any(pagelib.filename_like(c) for c in distinct):
        return True
    return sections >= 10 and len(distinct) < 3


def rechapter(store, only: list[str], write: bool) -> int:
    fixed = 0
    for manual in store.manuals():
        if only and not any(o.lower() in manual.id for o in only):
            continue
        path = ingest.pdf_path(manual.id)
        if not path.exists() or not manual.sections:
            continue
        current = [s.chapter for s in manual.sections]
        if not unusable(current, len(manual.sections)):
            continue
        doc = pymupdf.open(path)
        chaps = pagelib.chapters(pagelib.toc(doc), doc.page_count) or pagelib.text_chapters(doc)
        doc.close()
        fresh = [pagelib.chapter_of(chaps, s.pageStart) for s in manual.sections]
        if len({c for c in fresh if c}) <= len({c for c in current if c}) or any(pagelib.filename_like(c) for c in fresh if c):
            print(f"-   {manual.id:<44} no better grouping found")
            continue
        fixed += 1
        was, now = sorted({c for c in current if c})[:1], sorted({c for c in fresh if c})
        print(f"{'+' if write else '~'}   {manual.id:<44} {len({c for c in current if c})} -> {len(set(now))} chapters  {was} -> {now[:3]}")
        if write:
            sections = [s.model_copy(update={"chapter": c}) for s, c in zip(manual.sections, fresh)]
            store.put_manual(manual.model_copy(update={"sections": sections}))
    print(f"\n{fixed} manuals {'re-chaptered' if write else 'would be re-chaptered'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="tools.retitle")
    p.add_argument("--write", action="store_true")
    p.add_argument("--chapters", action="store_true")
    p.add_argument("--only", action="append", default=[])
    args = p.parse_args(argv)

    store = get_store()
    if args.chapters:
        return rechapter(store, args.only, args.write)
    changed = 0
    for manual in store.manuals():
        if args.only and not any(o.lower() in manual.id for o in args.only):
            continue
        path = ingest.pdf_path(manual.id)
        if not path.exists():
            print(f"-   {manual.id}: no PDF")
            continue
        make, model, year = bike_of(manual)
        doc = pymupdf.open(path)
        title = pagelib.cover_title(doc, make, model, year)
        doc.close()
        if title == manual.title:
            print(f"=   {manual.id:<40} {manual.title!r}")
            continue
        changed += 1
        print(f"{'+' if args.write else '~'}   {manual.id:<40} {manual.title!r} -> {title!r}")
        if args.write:
            store.put_manual(manual.model_copy(update={"title": title}))
    print(f"\n{changed} titles {'written' if args.write else 'would change'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Recompute the cover title of manuals already in the store. Nothing else about them changes.

    python -m tools.retitle              # show what would change
    python -m tools.retitle --write      # write the new titles
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


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="tools.retitle")
    p.add_argument("--write", action="store_true")
    p.add_argument("--only", action="append", default=[])
    args = p.parse_args(argv)

    store = get_store()
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

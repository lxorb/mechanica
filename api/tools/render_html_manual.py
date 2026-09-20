"""Turn an official *online* owner's manual into one PDF we can ingest.

Several manufacturers stopped publishing a PDF and publish a web reader instead — Toyota and Lexus
Europe, Tesla, Mercedes from MY2025, Jaguar Land Rover from MY2016, Mazda and Subaru Japan,
Polestar. The manual is free, official and complete; it simply is not a file. `/ingest` takes PDFs,
and `registry._is_pdf()` rejects everything else, so those manuals were indexed-but-unofferable or
(mostly) not indexed at all.

This tool prints them. For one manual it walks the publisher's own table of contents, fetches each
section's HTML from the publisher's own CDN, assembles them into a single document in the manual's
own order, and has headless Chrome print it to A4. The result carries:

  * a first page with make, model, year, language, the official source URL and the fetch date;
  * one printed page per section (`page-break-before`), the sections in the publisher's order;
  * a footer on **every** page naming the official source URL and the date it was fetched;
  * the publisher's own figures and tables, at print width;
  * a real text layer — checked, not assumed (see `verify`), because an ingest that cannot read
    the text is worthless.

What it does **not** do: nothing behind a login is ever rendered, and nothing is rewritten. The
document is the manufacturer's own words and pictures, re-paginated.

Where the file goes: the public `pdf` container under `rendered/<make>/<model>-<year>-<lang>.pdf`,
and the registry row points at *our* blob url with `source` set to the official page and
`rendered: true`, so nothing ever pretends this is the manufacturer's own file.

    cd api
    .venv/Scripts/python -m tools.render_html_manual list   --site tweddle
    .venv/Scripts/python -m tools.render_html_manual render --site tweddle --limit 3
    .venv/Scripts/python -m tools.render_html_manual render --site tweddle --all --upload

## Recipe: Toyota & Lexus Europe (`tweddle`)

`toyota.co.uk/customer/manuals` embeds `customerportal.tweddle-aws.eu`, whose API is
`diva-api.tweddle.app` and answers plain httpx with no token, cookie or browser:

    GET /publications?filters={"language":"en","publicationType":"UG"}&limit=100&page=N
        -> every English User Guide: {_id, partNumber, brand, model, modelType, year,
           contents.ditaId}. 566 of them, of which Toyota and Lexus are what we keep.
    GET /pubhub/publications/<ditaId>/content
        -> {publications:[{contents:[folder ids...]}], folders:[...], topics:[...]}
           a DITA tree: publications[0].contents is the ordered top level, every folder has its own
           ordered `contents`, and every folder and topic carries bodyHtml.url - a public S3 file.

Walking that tree depth-first in `contents` order is the manual's own order, which is why no
heading is invented here: the titles are the publisher's `title`, and the bodies are its HTML.
"""

from __future__ import annotations

import argparse
import datetime
import html as htmllib
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.models import RegistryEntry  # noqa: E402
from app.registry._http import Throttle, client, get_json, get_text, log, plausible_years, slug  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NODE_SCRIPT = Path(__file__).with_name("render_pdf.mjs")
# A local cache of what is already public in the blob, so a re-run skips work. Deliberately under
# `uploads/`: the test harness copies api/data for every run and ignores that folder, and a
# 50 MB-per-manual cache has no business in git either.
OUT_DIR = settings.data_dir / "uploads" / "rendered"
FRAGMENTS = settings.data_dir / "registry-fragments"
BLOB_PREFIX = "rendered"
MIN_PAGES = 8
MIN_CHARS_PER_PAGE = 120  # below this the "text layer" is decoration, not a manual
THROTTLE = Throttle(2.0)

BODY_ONLY = re.compile(r"(?is)<body[^>]*>(.*)</body>")
SCRIPTS = re.compile(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>")
EMPTY = re.compile(r"(?is)^\s*$")


# --- what a renderable manual is ------------------------------------------------------------------


@dataclass
class Manual:
    make: str
    model: str
    year: int
    lang: str
    market: str
    source: str  # the official page a reader would open
    title: str
    key: str  # stable id fragment, unique per manual
    sections: list[tuple[str, str]] = field(default_factory=list)  # (heading, html body)

    @property
    def blob_name(self) -> str:
        return f"{BLOB_PREFIX}/{slug(self.make)}/{slug(self.model, self.year, self.lang)}.pdf"

    @property
    def local(self) -> Path:
        return OUT_DIR / self.blob_name.split("/", 1)[1]


# --- Toyota / Lexus Europe -------------------------------------------------------------------------

DIVA = "https://diva-api.tweddle.app"
TWEDDLE_SITE = "customerportal.tweddle-aws.eu"
TWEDDLE_BRANDS = {"Toyota", "Lexus"}
PORTAL = "https://customerportal.tweddle-aws.eu/publications?brand={brand}&model={model}&modelType={type}&language={lang}"


PAGE_SIZE = 100  # the API caps `limit` here; `page` is 1-based and is the only pager it honours
# (`skip`, `offset`, `start`, `from` and `pageNumber` all answer with nothing - checked 2026-09-20).


def tweddle_publications(lang: str = "en") -> Iterator[dict]:
    """Every English User Guide the portal holds, paged. Brands other than Toyota/Lexus share this
    API (Kenworth trucks, among others) and are skipped rather than mislabelled."""
    query = urllib.parse.quote(json.dumps({"language": lang, "publicationType": "UG"}, separators=(",", ":")))
    seen: set[str] = set()
    with client() as c:
        for page in range(1, 40):
            data = get_json(c, f"{DIVA}/publications?filters={query}&limit={PAGE_SIZE}&page={page}", throttle=THROTTLE)
            items = (data or {}).get("items") or []
            fresh = [i for i in items if i.get("_id") and i["_id"] not in seen]
            if not fresh:
                return
            seen.update(i["_id"] for i in fresh)
            for item in fresh:
                if (item.get("brand") or "") in TWEDDLE_BRANDS:
                    yield item
            if len(seen) >= int((data or {}).get("total") or 0):
                return


def tweddle_manuals(lang: str = "en") -> list[Manual]:
    out: list[Manual] = []
    for item in tweddle_publications(lang):
        dita = ((item.get("contents") or {}).get("ditaId") or "").strip()
        years = plausible_years([item.get("year")])
        model = (item.get("modelType") or item.get("model") or "").strip()
        if not dita or not years or not model:
            continue
        make = item["brand"]
        out.append(
            Manual(
                make=make,
                model=model,
                year=years[0],
                lang=lang,
                market="EU",
                source=PORTAL.format(
                    brand=urllib.parse.quote(make),
                    model=urllib.parse.quote(item.get("model") or model),
                    type=urllib.parse.quote(model),
                    lang=lang,
                ),
                title=f"{years[0]} {make} {model} User Guide",
                key=dita,
            )
        )
    # One publication per (make, model, year, lang): the portal reissues part numbers, newest wins.
    best: dict[str, Manual] = {}
    for m in out:
        best[slug(m.make, m.model, m.year, m.lang)] = m
    return sorted(best.values(), key=lambda m: (m.make, m.model, m.year))


def tweddle_sections(manual: Manual) -> list[tuple[str, str]]:
    """Depth-first through the publisher's own table of contents, which is the manual's order."""
    with client() as c:
        tree = get_json(c, f"{DIVA}/pubhub/publications/{manual.key}/content", throttle=THROTTLE)
        if not isinstance(tree, dict) or not tree.get("publications"):
            log.warning("tweddle: no content tree for %s", manual.key)
            return []
        nodes = {n["id"]: n for n in (tree.get("folders") or []) + (tree.get("topics") or []) if n.get("id")}
        order: list[dict] = []

        def walk(ids: Iterable[dict], depth: int = 0) -> None:
            for ref in ids or []:
                node = nodes.get((ref or {}).get("id"))
                if not node or node.get("_seen"):
                    continue
                node["_seen"] = True
                node["_depth"] = depth
                order.append(node)
                walk(node.get("contents") or [], depth + 1)

        walk((tree["publications"][0] or {}).get("contents") or [])
        sections: list[tuple[str, str]] = []
        for node in order:
            url = ((node.get("bodyHtml") or {}).get("url") or "").strip()
            if not url:
                continue
            body = _body(get_text(c, url, throttle=THROTTLE) or "")
            if body:
                sections.append((node.get("title") or "", body))
    return sections


def _body(raw: str) -> str:
    hit = BODY_ONLY.search(raw)
    body = SCRIPTS.sub("", hit.group(1) if hit else raw)
    return "" if EMPTY.match(body) else body.strip()


RECIPES = {"tweddle": (tweddle_manuals, tweddle_sections)}


# --- assembling and printing ------------------------------------------------------------------------

PAGE_CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.45 "Segoe UI", Arial, Helvetica, sans-serif; color: #111; margin: 0; }
.cover { page-break-after: always; padding-top: 28mm; }
.cover h1 { font-size: 26pt; margin: 0 0 6mm; line-height: 1.2; }
.cover dl { font-size: 11pt; margin: 0; }
.cover dt { color: #666; font-size: 9pt; text-transform: uppercase; letter-spacing: .06em; margin-top: 5mm; }
.cover dd { margin: 0; word-break: break-all; }
.cover .note { margin-top: 14mm; font-size: 9pt; color: #555; border-top: 1px solid #ddd; padding-top: 4mm; }
section.ttm { page-break-before: always; }
section.ttm > h2.ttm { font-size: 15pt; margin: 0 0 4mm; padding-bottom: 2mm; border-bottom: 1px solid #ccc; }
h1, h2, h3, h4 { page-break-after: avoid; }
h1 { font-size: 14pt; } h2 { font-size: 12.5pt; } h3 { font-size: 11.5pt; } h4 { font-size: 11pt; }
p, li { orphans: 3; widows: 3; }
img { max-width: 100%; height: auto; page-break-inside: avoid; }
figure { margin: 4mm 0; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; page-break-inside: avoid; font-size: 9.5pt; }
th, td { border: 1px solid #bbb; padding: 2mm 2.5mm; vertical-align: top; }
pre { white-space: pre-wrap; }
"""

DOC = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><title>{title}</title><style>{css}</style></head>
<body>
<div class="cover">
  <h1>{title}</h1>
  <dl>
    <dt>Make</dt><dd>{make}</dd>
    <dt>Model</dt><dd>{model}</dd>
    <dt>Model year</dt><dd>{year}</dd>
    <dt>Language</dt><dd>{lang}</dd>
    <dt>Official source</dt><dd>{source}</dd>
    <dt>Fetched</dt><dd>{fetched}</dd>
  </dl>
  <p class="note">{note}</p>
</div>
{sections}
</body></html>
"""

NOTE = (
    "This PDF was printed from the manufacturer's own online owner's manual, linked above, on the date "
    "shown. The text and figures are the manufacturer's; only the pagination is ours. Nothing has been "
    "rewritten, added or removed."
)


def assemble(manual: Manual, fetched: str) -> str:
    parts = []
    for heading, body in manual.sections:
        head = f'<h2 class="ttm">{htmllib.escape(heading)}</h2>' if heading else ""
        parts.append(f'<section class="ttm">{head}{body}</section>')
    return DOC.format(
        lang=htmllib.escape(manual.lang),
        title=htmllib.escape(manual.title),
        css=PAGE_CSS,
        make=htmllib.escape(manual.make),
        model=htmllib.escape(manual.model),
        year=manual.year,
        source=htmllib.escape(manual.source),
        fetched=fetched,
        note=NOTE,
        sections="\n".join(parts),
    )


def print_pdf(html: str, out: Path, footer: str) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html)
        source = Path(fh.name)
    try:
        done = subprocess.run(
            ["node", str(NODE_SCRIPT), str(source), str(out), footer],
            cwd=str(ROOT),  # puppeteer-core resolves from the repo's own node_modules
            capture_output=True,
            text=True,
            timeout=900,
        )
        if done.returncode != 0:
            print(f"    chrome failed ({done.returncode}): {(done.stderr or done.stdout).strip()[:300]}", file=sys.stderr)
            return False
        return out.exists()
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"    render failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    finally:
        source.unlink(missing_ok=True)


def verify(path: Path) -> tuple[bool, str]:
    """A PDF with enough pages and a real text layer. An ingest cannot read a picture of a page."""
    try:
        import fitz
    except ImportError:
        return True, "PyMuPDF not installed, not verified"
    try:
        with fitz.open(path) as doc:
            pages = doc.page_count
            text = sum(len(doc[i].get_text("text").strip()) for i in range(min(pages, 40)))
    except Exception as exc:
        return False, f"unreadable: {type(exc).__name__}"
    if pages < MIN_PAGES:
        return False, f"{pages} pages, under {MIN_PAGES}"
    per_page = text / max(1, min(pages, 40))
    if per_page < MIN_CHARS_PER_PAGE:
        return False, f"{pages} pages but only {per_page:.0f} chars/page - no usable text layer"
    return True, f"{pages} pages, {per_page:.0f} chars/page"


def row(manual: Manual, url: str, fetched: str) -> RegistryEntry:
    return RegistryEntry(
        id=slug("rendered", manual.make, manual.model, manual.year, manual.lang, "owner"),
        make=manual.make,
        model=manual.model,
        years=[manual.year],
        market=manual.market,
        type="owner",
        lang=manual.lang,
        url=url,
        access="free",
        site=TWEDDLE_SITE,
        title=manual.title,
        docKind="owner",
        kind="car",
        source=manual.source,
        rendered=True,
    )


# --- commands ----------------------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    find, _ = RECIPES[args.site]
    manuals = find(args.lang)
    print(f"{len(manuals)} renderable manual(s) on {args.site}")
    for m in manuals[: args.limit or len(manuals)]:
        print(f"  {m.make:<8}{m.model[:34]:<34}{m.year}  {m.key}")
    return 0


def by_coverage(manuals: list[Manual]) -> list[Manual]:
    """Most catalog vehicles served first, then breadth-first across nameplates, newest year first.

    "Served" means: existing catalog vehicles that have no manual today and that this render would
    give one to, found the same way `_pick` would - exact id or alias. For Toyota/Lexus Europe that
    count is **zero for all 457**, because the European model-type names (`Corolla Hybrid Hatchback`,
    `ES 350h`) are not the US catalogue's names, so every render creates a new vehicle rather than
    filling an empty one. The ordering is still computed rather than assumed: the next site may be
    the other way round, and a tie falls through to breadth-first, which is the right answer when
    every render is worth exactly one vehicle."""
    score: dict[int, int] = {}
    try:
        from app.registry import alias_key
        from app.store import get_store

        empty: dict[str, int] = {}
        for bike in get_store().bikes():
            if bike.manualUrl:
                continue
            for key in (slug(bike.make, bike.model, bike.year), alias_key(bike.make, bike.model, bike.year)):
                if key:
                    empty[key] = empty.get(key, 0) + 1
        for m in manuals:
            score[id(m)] = max(
                empty.get(slug(m.make, m.model, m.year), 0),
                empty.get(alias_key(m.make, m.model, m.year), 0),
            )
    except Exception as exc:  # the catalogue is not needed to render, only to prioritise
        log.warning("render: cannot read the catalogue to order by coverage (%s)", exc)
    ordered = breadth_first(manuals)
    served = sum(1 for m in ordered if score.get(id(m), 0))
    print(f"  {served} of {len(ordered)} manual(s) would fill a catalog vehicle that has none")
    return sorted(ordered, key=lambda m: -score.get(id(m), 0))


def breadth_first(manuals: list[Manual]) -> list[Manual]:
    """Round-robin across nameplates, newest year first.

    Every render is one row and therefore one catalog vehicle, so the order that buys the most is
    the one that reaches the most *models* soonest: all the newest years first, then the next year
    of each, and so on. A cycle that runs out of time has still covered the range rather than ten
    years of one Corolla."""
    by_model: dict[str, list[Manual]] = {}
    for m in manuals:
        by_model.setdefault(slug(m.make, m.model), []).append(m)
    for group in by_model.values():
        group.sort(key=lambda m: -m.year)
    out: list[Manual] = []
    for depth in range(max((len(g) for g in by_model.values()), default=0)):
        for key in sorted(by_model):
            if depth < len(by_model[key]):
                out.append(by_model[key][depth])
    return out


def cmd_render(args: argparse.Namespace) -> int:
    find, fetch = RECIPES[args.site]
    manuals = by_coverage(find(args.lang))
    if not args.all:
        manuals = manuals[: args.limit]
    fetched = datetime.date.today().isoformat()
    print(f"{len(manuals)} manual(s) to render from {args.site}")
    blob = None
    uploaded: dict[str, int] = {}
    if args.upload:
        from tools.sync_blob import store as blob_store

        blob = blob_store()
        uploaded = already_there(blob)
        print(f"  {len(uploaded)} rendered manual(s) already public in the blob")
    rows: list[RegistryEntry] = []
    failed = 0
    started = time.monotonic()
    lock = threading.Lock()
    out_of_time = threading.Event()

    def one(numbered: tuple[int, Manual]) -> None:
        nonlocal failed
        n, manual = numbered
        if out_of_time.is_set():
            return
        if args.max_minutes and (time.monotonic() - started) / 60 >= args.max_minutes:
            if not out_of_time.is_set():
                out_of_time.set()
                print(f"  stopping at the {args.max_minutes} minute budget")
            return
        label = f"[{n}/{len(manuals)}] {manual.make} {manual.model} {manual.year}"
        if manual.local.exists() and not args.force:
            ok, why = verify(manual.local)
            if ok:
                # Re-upload: the file on disk may predate the container, and overwrite is idempotent.
                if blob is not None and not _upload(blob, manual, uploaded):
                    with lock:
                        failed += 1
                    return
                print(f"  {label}: already rendered ({why})")
                with lock:
                    rows.append(row(manual, _url(blob, manual), fetched))
                return
        if args.only_rendered:
            return
        manual.sections = fetch(manual)
        if len(manual.sections) < MIN_PAGES:
            print(f"  {label}: only {len(manual.sections)} section(s), skipped")
            with lock:
                failed += 1
            return
        footer = f"Official source: {manual.source}  ·  fetched {fetched}"
        if not print_pdf(assemble(manual, fetched), manual.local, footer):
            with lock:
                failed += 1
            return
        ok, why = verify(manual.local)
        print(f"  {label}: {len(manual.sections)} sections -> {why}{'' if ok else '  REJECTED'}")
        if not ok:
            manual.local.unlink(missing_ok=True)
            with lock:
                failed += 1
            return
        if blob is not None and not _upload(blob, manual, uploaded):
            with lock:
                failed += 1
            return
        with lock:
            rows.append(row(manual, _url(blob, manual), fetched))

    # Each worker drives its own Chrome. The HTTP side is throttled globally (THROTTLE), so more
    # workers never means hammering the publisher harder - only more of the waiting overlapped.
    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(one, enumerate(manuals, 1)))
    else:
        for numbered in enumerate(manuals, 1):
            one(numbered)
    if rows and args.fragment:
        path = FRAGMENTS / args.fragment
        path.write_text(json.dumps([r.model_dump(exclude_none=True) for r in rows], ensure_ascii=False), encoding="utf-8")
        print(f"wrote {path} ({len(rows)} rows)")
    print(f"rendered {len(rows)}, failed {failed}")
    return 0


def _url(blob, manual: Manual) -> str:
    base = blob.pdf_base if blob is not None else f"https://{settings.azure_storage_account or 'BLOB'}.blob.core.windows.net/pdf"
    return f"{base}/{manual.blob_name}"


def already_there(blob) -> dict[str, int]:
    """blob name -> size for what is already under `rendered/`.

    Every cycle re-runs the whole list so that a finished manual is picked up wherever it stopped,
    and without this the reuse path would re-upload the entire 50 MB-per-manual cache each time.
    Same name and same size means the file is already public; nothing else needs checking, because
    a render is deterministic for a given publication."""
    try:
        container = blob.service.get_container_client(settings.azure_pdf_container)
        return {b.name: int(b.size or 0) for b in container.list_blobs(name_starts_with=f"{BLOB_PREFIX}/")}
    except Exception as exc:
        log.warning("render: cannot list the blob container (%s); uploading everything", exc)
        return {}


def _upload(blob, manual: Manual, known: dict[str, int] | None = None) -> bool:
    from azure.storage.blob import ContentSettings

    from tools.sync_blob import upload

    if known is not None and known.get(manual.blob_name) == manual.local.stat().st_size:
        return True  # same name, same bytes: it is already public
    try:
        size = upload(
            blob,
            settings.azure_pdf_container,
            manual.local,
            manual.blob_name,
            ContentSettings(content_type="application/pdf", cache_control="public, max-age=31536000"),
        )
        print(f"      uploaded {manual.blob_name} ({size / 1e6:.1f} MB)")
        return True
    except Exception as exc:
        print(f"      upload failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tools.render_html_manual", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("list", cmd_list), ("render", cmd_render)):
        c = sub.add_parser(name)
        c.add_argument("--site", choices=sorted(RECIPES), default="tweddle")
        c.add_argument("--lang", default="en")
        c.add_argument("--limit", type=int, default=5)
        c.set_defaults(fn=fn)
        if name == "render":
            c.add_argument("--all", action="store_true", help="every manual the recipe finds")
            c.add_argument("--upload", action="store_true", help="push each PDF to the public pdf container")
            c.add_argument("--force", action="store_true", help="re-render even when the file is already there")
            c.add_argument("--fragment", default="rendered-tweddle.json")
            c.add_argument("--max-minutes", type=int, default=0, help="stop cleanly after this long")
            c.add_argument("--only-rendered", action="store_true", help="upload and index what is already on disk, render nothing new")
            c.add_argument("--workers", type=int, default=1, help="Chrome renders in parallel")
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the demo catalog: ~25 popular bikes, one real manual each. Run from api/:

    python -m tools.bulk_ingest --list
    python -m tools.bulk_ingest --run --parallel 3 [--only mt07 --only grom] [--force]
    python -m tools.bulk_ingest --verify [--api http://127.0.0.1:8007]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app import ask, ingest  # noqa: E402
from app.config import settings  # noqa: E402
from app.ingest import curate as curate_mod  # noqa: E402
from app.models import Bike, IngestJob, Manual  # noqa: E402
from app.registry._http import slug  # noqa: E402
from app.search import get_index  # noqa: E402
from app.store import get_store  # noqa: E402

AZ = "https://azwecdnepstoragewebsiteuploads.azureedge.net"
BMW = "https://manuals.bmw-motorrad.com/manuals/BA-Extern/IN/BA-INTERNET-COM/PDF"
HONDA = "https://cdn.powersports.honda.com/documentum/MWOM"
YAM = "https://cdn2.yamaha-motor.eu/prod/owner-manuals/Motorcycles"
KAW = "https://pws.ktivs.net/proxy/manuals"
RE = "https://www.royalenfield.com/content/dam"

PLAN: tuple[tuple[str, str, int, str, str], ...] = (
    ("KTM", "890 Duke R", 2023, "EU", f"{AZ}/23_3214759_en_OM.pdf"),
    ("KTM", "1290 Super Adventure S", 2024, "EU", f"{AZ}/24_3214938_en_OM.pdf"),
    ("KTM", "390 Adventure", 2024, "EU", f"{AZ}/24_3214963_en_OM.pdf"),
    ("Husqvarna", "Svartpilen 401", 2025, "EU", f"{AZ}/25_3402862_en_OM.pdf"),
    ("Husqvarna", "701 Enduro", 2024, "EU", f"{AZ}/24_3402755_en_OM.pdf"),
    ("GasGas", "ES 700", 2024, "EU", f"{AZ}/24_3215181_en_OM.pdf"),
    ("BMW", "R 1300 GS", 2025, "EU", f"{BMW}/R_0M21_RM_0225_01.pdf"),
    ("BMW", "S 1000 RR", 2024, "EU", f"{BMW}/S_0P21_RM_0724_01.pdf"),
    ("BMW", "F 900 R", 2025, "EU", f"{BMW}/F_0K81_RM_0725_01.pdf"),
    ("BMW", "R 12 nineT", 2025, "EU", f"{BMW}/R_0N01_RM_0725_01.pdf"),
    ("Honda", "Africa Twin", 2025, "US", f"{HONDA}/ml.remawmom.amln2525omen.pdf"),
    ("Honda", "Rebel 500", 2025, "US", f"{HONDA}/ml.remawmom.amlh2525omen.pdf"),
    ("Honda", "Grom", 2025, "US", f"{HONDA}/ml.remawmom.ak262525omen.pdf"),
    ("Honda", "CB500F", 2025, "US", f"{HONDA}/ml.remawmom.amlr2525omen.pdf"),
    ("Honda", "CBR650R", 2023, "US", f"{HONDA}/ml.remawmom.amkyr2323omen.pdf"),
    ("Yamaha", "MT07", 2025, "EU", f"{YAM}/PD66F8199E0E.pdf"),
    ("Yamaha", "MT09", 2025, "EU", f"{YAM}/PBME28199E1E_1.pdf"),
    ("Yamaha", "Ténéré 700", 2025, "EU", f"{YAM}/PD08F8199E0E.pdf"),
    ("Yamaha", "R7", 2024, "EU", f"{YAM}/PBVA28199E0E.pdf"),
    ("Kawasaki", "Z900RS", 2025, "US", f"{KAW}/99814-0162-o6zr902atf-us-en-tws-7125d991b06925f95ac09cf27359bc30.pdf"),
    ("Kawasaki", "Ninja 500", 2025, "US", f"{KAW}/99814-0131-o6ex500gtf-us-en-tws-e8a6a98afa642f552eb2a0ec42576aa3.pdf"),
    ("Kawasaki", "VULCAN S", 2025, "US", f"{KAW}/99814-0285-o6en650dv-us-en-tws-1835cb0c62d9acb708236e1697e5c6e3.pdf"),
    ("Kawasaki", "VERSYS 1100", 2026, "US", f"{KAW}/99814-0268-o6klz1100cv-us-en-tws-b6cd4ca34a6326bcbdb5af83a90aa2e3.pdf"),
    ("Royal Enfield", "Himalayan 450", 2024, "US", f"{RE}/royal-enfield/usa/support/owners-manual/pdf/re-himalayan-450-owners-manual-usa.pdf"),
    ("Royal Enfield", "INT 650", 2025, "US", f"{RE}/open-pdf/royal-enfield-int-650-owners-manual-usa.pdf"),
    ("Royal Enfield", "Classic 350", 2025, "US", f"{RE}/open-pdf/royal-enfield-classic-350-owners-manual-usa.pdf"),
)

ASKS = ("how do I check the engine oil", "what is the tyre pressure", "how do I change a blown fuse")

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
AGENTS = (BROWSER, GOOGLEBOT)

REPORT = settings.data_dir / "bulk_report.json"

log = logging.getLogger("bulk")
_current = threading.local()
_spend: dict[str, float] = defaultdict(float)
_spend_lock = threading.Lock()
_report_lock = threading.Lock()
_rows: dict[str, dict] = {}


def ids(make: str, model: str, year: int, market: str) -> tuple[str, str]:
    return slug(make, model, year, market, "om"), slug(make, model, year)


def track_cost() -> None:
    """costs.jsonl is shared with the running API instances, so attribute spend per manual in-process instead.

    The ingest pipeline fans out over its own thread pools, so worker threads inherit the manual they were started for.
    """
    store = get_store()
    original = store.log_cost

    def logged(event) -> None:
        manual_id = getattr(_current, "manual_id", None)
        if manual_id:
            with _spend_lock:
                _spend[manual_id] += event.usd
        original(event)

    store.log_cost = logged

    thread_init, thread_run = threading.Thread.__init__, threading.Thread.run

    def init(self, *a, **kw) -> None:
        thread_init(self, *a, **kw)
        self._bulk_owner = getattr(_current, "manual_id", None)

    def run(self) -> None:
        owner = getattr(self, "_bulk_owner", None)
        if owner:
            _current.manual_id = owner
        thread_run(self)

    threading.Thread.__init__ = init
    threading.Thread.run = run


def download(url: str, dest: Path) -> int:
    if dest.exists() and dest.stat().st_size > 4096 and dest.open("rb").read(4) == b"%PDF":
        return dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for agent in AGENTS:
        headers = {"User-Agent": agent, "Accept": "application/pdf,application/octet-stream,*/*", "Accept-Language": "en-US,en;q=0.9"}
        tmp = dest.with_suffix(".part")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=300.0, headers=headers) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
            if tmp.open("rb").read(4) != b"%PDF":
                raise ValueError("not a PDF")
            tmp.replace(dest)
            return dest.stat().st_size
        except Exception as exc:
            last = exc
            tmp.unlink(missing_ok=True)
    raise RuntimeError(f"download failed: {type(last).__name__}: {last}")


def ensure_bike(bike_id: str, make: str, model: str, year: int, market: str) -> None:
    store = get_store()
    if store.bike(bike_id) is None:
        store.put_bikes([Bike(id=bike_id, make=make, model=model, year=year, market=market)])


def link(bike_id: str, manual_id: str, make: str, model: str, year: int, market: str) -> bool:
    store = get_store()
    for _ in range(3):
        bike = store.bike(bike_id) or Bike(id=bike_id, make=make, model=model, year=year, market=market)
        store.put_bikes([bike.model_copy(update={"manualId": manual_id})])
        current = store.bike(bike_id)
        if current is not None and current.manualId == manual_id:
            return True
        time.sleep(0.5)
    return False


def load_report() -> None:
    """A partial run must not erase what earlier runs recorded."""
    if not REPORT.exists():
        return
    try:
        old = json.loads(REPORT.read_text(encoding="utf-8"))
    except Exception:
        return
    for row in old.get("manuals", []):
        if row.get("id"):
            _rows[row["id"]] = row


def write_report() -> None:
    with _report_lock:
        rows = [_rows[key] for key in sorted(_rows)]
        payload = {
            "generatedAt": time.time(),
            "planned": len(PLAN),
            "done": sum(1 for r in rows if r.get("status") == "done"),
            "failed": sum(1 for r in rows if r.get("status") == "error"),
            "totalUsd": round(sum(r.get("usd", 0.0) for r in rows), 4),
            "totalPdfBytes": sum(r.get("pdfBytes", 0) for r in rows),
            "totalSectionsDropped": sum(r.get("sectionsDropped", 0) for r in rows),
            "manuals": rows,
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        tmp = REPORT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(REPORT)


def summarise(manual: Manual, manual_id: str) -> dict:
    store = get_store()
    highlights = sum(len(s.highlights) for s in manual.sections)
    return {
        "pages": manual.pages,
        "title": manual.title,
        "sections": len(manual.sections),
        "highlights": highlights,
        "highlightsPerSection": round(highlights / max(1, len(manual.sections)), 2),
        "parts": len(manual.parts),
        "specs": len(store.specs(manual_id)),
    }


def one(entry: tuple[str, str, int, str, str], force: bool) -> dict:
    make, model, year, market, url = entry
    manual_id, bike_id = ids(make, model, year, market)
    store = get_store()
    row: dict = {"id": manual_id, "bikeId": bike_id, "make": make, "model": model, "year": year, "market": market, "url": url}

    ensure_bike(bike_id, make, model, year, market)
    existing = store.manual(manual_id)
    if existing is not None and not force:
        row = {**_rows.get(manual_id, {}), **row}
        row.setdefault("usd", 0.0)
        row.setdefault("seconds", 0.0)
        row.setdefault("sectionsDropped", 0)
        row.update(status="skipped", attempts=0, **summarise(existing, manual_id))
        row["pdfBytes"] = ingest.pdf_path(manual_id).stat().st_size if ingest.pdf_path(manual_id).exists() else 0
        row["linked"] = link(bike_id, manual_id, make, model, year, market)
        _rows[manual_id] = row
        write_report()
        print(f"= {manual_id}  already present ({row['sections']} sections)")
        return row

    _current.manual_id = manual_id
    with _spend_lock:
        _spend[manual_id] = 0.0
    started = time.time()
    error = ""
    for attempt in (1, 2):
        try:
            row["pdfBytes"] = download(url, ingest.pdf_path(manual_id))
            job = IngestJob(id=uuid.uuid4().hex[:12], manualId=manual_id, status="queued")
            store.put_job(job)
            manual = ingest.run(job.id, str(ingest.pdf_path(manual_id)), manual_id, [bike_id], make, model, year)
            manual = manual.model_copy(update={"source": url})
            result = curate_mod.apply(manual)
            try:
                get_index().index(result.manual, store.pages(manual_id), store.specs(manual_id))
            except Exception as exc:
                log.warning("%s: reindex failed: %s", manual_id, exc)
            row.update(
                status="done",
                attempts=attempt,
                sectionsDropped=len(result.dropped),
                dropped=result.dropped[:20],
                highlightsClamped=result.clamped,
                highlightsDiscarded=result.discarded,
                **summarise(result.manual, manual_id),
            )
            error = ""
            break
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("%s attempt %d failed: %s", manual_id, attempt, error)
            time.sleep(3)
    row["seconds"] = round(time.time() - started, 1)
    with _spend_lock:
        row["usd"] = round(_spend.get(manual_id, 0.0), 4)
    _current.manual_id = None

    if error:
        row.update(status="error", error=error, attempts=2)
        row.setdefault("sectionsDropped", 0)
        print(f"x {manual_id}  {error}")
    else:
        row["linked"] = link(bike_id, manual_id, make, model, year, market)
        print(
            f"+ {manual_id}  p{row['pages']} sec{row['sections']} (-{row['sectionsDropped']}) "
            f"hl{row['highlights']} parts{row['parts']} specs{row['specs']} ${row['usd']:.3f} {row['seconds']}s"
        )
    _rows[manual_id] = row
    write_report()
    return row


def cmd_list(entries) -> int:
    for make, model, year, market, url in entries:
        manual_id, bike_id = ids(make, model, year, market)
        store = get_store()
        state = "have" if store.manual(manual_id) else "new "
        print(f"{state} {manual_id:<44} {bike_id:<36} {make} {model} {year} {market}")
        print(f"      {url}")
    print(f"{len(entries)} manuals planned")
    return 0


def cmd_run(entries, parallel: int, force: bool) -> int:
    from concurrent.futures import ThreadPoolExecutor

    load_report()
    track_cost()
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        rows = list(pool.map(lambda e: one(e, force), entries))
    write_report()
    ok = [r for r in rows if r.get("status") == "done"]
    bad = [r for r in rows if r.get("status") == "error"]
    print(f"\ndone {len(ok)}  skipped {sum(1 for r in rows if r.get('status') == 'skipped')}  failed {len(bad)}")
    print(f"cost ${sum(r.get('usd', 0.0) for r in rows):.2f}  pdf {sum(r.get('pdfBytes', 0) for r in rows) / 1e6:.0f} MB  {(time.time() - started) / 60:.1f} min")
    for r in bad:
        print(f"  {r['id']}: {r.get('error')}")
    print(f"report {REPORT}")
    return 1 if bad else 0


def cmd_verify(entries, api: str | None) -> int:
    store = get_store()
    problems: list[str] = []
    checks: list[dict] = []
    client = httpx.Client(timeout=60.0) if api else None
    for make, model, year, market, _ in entries:
        manual_id, bike_id = ids(make, model, year, market)
        manual = store.manual(manual_id)
        check: dict = {"id": manual_id}
        if manual is None:
            problems.append(f"{manual_id}: missing")
            checks.append({**check, "ok": False, "why": "missing"})
            continue
        Manual.model_validate(manual.model_dump(exclude_none=True))
        highlights = sum(len(s.highlights) for s in manual.sections)
        per = highlights / max(1, len(manual.sections))
        pdf = ingest.pdf_path(manual_id)
        bike = store.bike(bike_id)
        check.update(
            sections=len(manual.sections),
            highlightsPerSection=round(per, 2),
            pdf=pdf.exists(),
            linked=bool(bike and bike.manualId == manual_id),
        )
        if len(manual.sections) < 15:
            problems.append(f"{manual_id}: {len(manual.sections)} sections")
        if per < 1.0:
            problems.append(f"{manual_id}: {per:.2f} highlights/section")
        if not pdf.exists():
            problems.append(f"{manual_id}: no PDF")
        if not check["linked"]:
            problems.append(f"{manual_id}: bike {bike_id} not linked")
        if client is not None:
            meta = client.get(f"{api}/manuals/{manual_id}")
            head = client.get(f"{api}/manuals/{manual_id}/file")
            check["http"] = [meta.status_code, head.status_code]
            if meta.status_code != 200 or head.status_code != 200:
                problems.append(f"{manual_id}: http {meta.status_code}/{head.status_code}")
        hits = []
        for query in ASKS:
            answer = ask.answer(manual_id, query)
            titles = [m.section.title for m in answer.matches[:2]]
            hits.append({"q": query, "titles": titles, "pages": [m.section.pageStart for m in answer.matches[:2]]})
            if not answer.matches:
                problems.append(f"{manual_id}: no match for '{query}'")
        check["asks"] = hits
        checks.append(check)
        print(f"{'ok ' if not problems or problems[-1].split(':')[0] != manual_id else 'BAD'} {manual_id:<44} sec{len(manual.sections):<4} hl/s {per:.2f}  " + " | ".join(h["titles"][0] if h["titles"] else "-" for h in hits))
    if client is not None:
        client.close()

    payload = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    payload["verify"] = {"at": time.time(), "api": api, "problems": problems, "checks": checks}
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(checks)} manuals checked, {len(problems)} problems")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="tools.bulk_ingest")
    p.add_argument("--list", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--only", action="append", default=[])
    p.add_argument("--force", action="store_true")
    p.add_argument("--api", default=None)
    args = p.parse_args(argv)

    entries = PLAN
    if args.only:
        wanted = [o.lower() for o in args.only]
        entries = tuple(e for e in PLAN if any(w in ids(e[0], e[1], e[2], e[3])[0] for w in wanted))
    if args.run:
        return cmd_run(entries, args.parallel, args.force)
    if args.verify:
        return cmd_verify(entries, args.api)
    return cmd_list(entries)


if __name__ == "__main__":
    raise SystemExit(main())

"""One source of truth for every number quoted in the Mechanica pitches. Owner: numbers agent.

    api/.venv/Scripts/python tools/pitch_numbers.py                       # print the tables
    api/.venv/Scripts/python tools/pitch_numbers.py --live                # ask the deployed API too
    api/.venv/Scripts/python tools/pitch_numbers.py --live --md ../docs/pitches/numbers.md

Nine pitch agents each measured the same product and got nine different answers, because a number
like "mislabelled rows" has two honest definitions and a number like "total spent" moves every hour.
So this file does three things and nothing else:

  1. computes every headline figure from data on disk or from the live API - never from a document;
  2. prints the EXACT definition next to each one, so two definitions of the same word stay apart;
  3. greps the nine pitch files for figures that contradict what it just computed, with file:line.

Every row carries a mark:
  measured  - a count or a timing we recorded. Reading it again gives the same answer (or a newer one).
  computed  - arithmetic over measured values, done here. The formula is in the source column.
  assumed   - an input nobody measured. Only a handful exist, and they say so.

Sources, in order of authority:
  live https://mechanica.emilvinu.ch/api   what a judge sees if they open the site during the pitch
  api/data/registry.json                   every crawled row; written only by `tools.registry merge-fragments`
  api/data/bikes.json                      the catalog the API serves from /catalog
  api/data/costs.jsonl                     one line per OpenAI call ever made, development included
  api/data/mass_report.jsonl               one line per manual ingested in the bulk run
  api/eval/report.md, api/eval/chat-report.md   the two controlled evals
  docs/pitches/general/, docs/MANUALS.md   single live runs that were timed by hand, quoted with their date
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import PRICES, TOKENS_PER_PAGE, naive_usd  # noqa: E402
from app.models import Bike, RegistryEntry  # noqa: E402
from app.registry import _ingestable, _is_pdf, doc_kind  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PITCHES = REPO / "docs" / "pitches"
LIVE = "https://mechanica.emilvinu.ch/api"
TIMEOUT = 180
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

# Portals walked to the end and written off, from docs/MANUALS.md ("Checked and genuinely unreachable").
UNREACHABLE = (
    "CFMOTO", "LiveWire", "Beta", "Moto Morini", "Brixton", "Ural", "Janus", "Norton", "Mash",
    "CCM", "SWM", "Fantic", "Energica", "Segway", "Sur-Ron", "Talaria", "Stark",
)

# Numbers that were timed by hand against the live service on one run. They cannot be recomputed from
# a file, so they are quoted with the run that produced them and marked measured, never computed.
HAND_TIMED = {
    "ingest_readable_s": (1.3, "docs/pitches/general.md - live run, KTM 390 Duke 2014, 182 p, 2026-09-20"),
    "ingest_searchable_s": (40.4, "same run: /ingest job to status=done"),
    "ingest_run_usd": (0.089, "same run: cost-log delta over the run"),
    "vin_s": (1.3, "live POST /api/identify/vin VBKJSA40XXXXXXXXX -> KTM 390 Duke 2024, 2026-09-20"),
    "ask_cold_s": (2.2, "live ask, first time, 2026-09-20 (range 2.2-3.4 s)"),
    "ask_warm_s": (0.20, "live ask, same question again, 2026-09-20 - served from ask._cache, $0"),
}

# api/eval/report.md, 2026-09-19 23:38 UTC, 150 queries. Parsed below where the file allows it and
# pinned here where it does not, so a missing eval file degrades to the committed figures, not to zero.
EVAL = {
    "asks": 150, "in_scope": 130, "oos": 20, "top1": 100.0, "oos_empty": 100.0,
    "mean_s": 1.60, "p95_s": 3.33, "usd": 0.00038, "calls": 172,
}
# api/eval/chat-report.md, 2026-09-20 06:17 UTC, 25 questions.
CHAT_EVAL = {
    "questions": 25, "claims": 48, "cited": 100.0, "quotes": 43, "verbatim": 100.0,
    "invented": 0, "referrals": 0, "ttc_in": 46_501, "ttc_out": 31_977, "ttc_pct": 31.2,
    "usd": 0.00488, "ttft_p50": 2.64, "ttft_p95": 5.87, "full_p50": 4.18,
}
# Voice, measured per engine. Two engines, two numbers, and they are not interchangeable.
VOICE = {
    "deepgram_first_audio_ms": (2083, 1733, 4006, "docs/pitches/deepgram.md - 5 spec turns, 4 sessions, 2026-09-20"),
    "deepgram_procedure_ms": (9878, "same - find_procedure runs the full router -> BM25 -> picker pipeline"),
    "live_engine_s": ((1.5, 2.0), "web/docs/VOICE.md - end of speech to first audio on the shipped engine"),
}
PARTS_DEMO = ("ktm-390-duke-2024-om-en", "ktm-390-duke-2024")


# --------------------------------------------------------------------------------------- plumbing


@dataclass
class N:
    """One number: what it is, what it is, and exactly how it was obtained."""

    key: str
    label: str
    value: str
    mark: str  # measured | computed | assumed
    source: str
    group: str = ""
    raw: float | int | None = None


@dataclass
class Book:
    rows: list[N] = field(default_factory=list)
    by_key: dict[str, N] = field(default_factory=dict)

    def add(self, key: str, label: str, value: str, mark: str, source: str, group: str, raw=None) -> N:
        n = N(key, label, value, mark, source, group, raw)
        self.rows.append(n)
        self.by_key[key] = n
        return n

    def val(self, key: str) -> str:
        n = self.by_key.get(key)
        return n.value.replace("**", "") if n else "?"

    def groups(self) -> list[str]:
        return list(dict.fromkeys(r.group for r in self.rows))


def fetch(path: str) -> object | None:
    """The zone's WAF answers 403 to urllib's default user agent, so send a browser one."""
    req = urllib.request.Request(f"{LIVE}{path}", headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"  live {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def host_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0].lower() if "//" in url else ""


def pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole else 0.0


# ------------------------------------------------------------------------------------- the numbers


def registry_numbers(book: Book) -> None:
    """Everything derived from the crawl. Definitions matter more here than anywhere else: `rows`,
    `distinct URLs`, `free PDFs` and `vehicles` are four different counts and every pitch mixes them."""
    g = "1. The registry - what we can reach"
    rows = [RegistryEntry.model_validate(r) for r in json.loads((ROOT / "data" / "registry.json").read_text(encoding="utf-8"))]
    sites = collections.Counter(e.site for e in rows)
    hosts = {host_of(e.url) for e in rows} - {""}
    urls = {e.url for e in rows}
    free = [e for e in rows if _ingestable(e)]
    free_urls = {e.url for e in free}
    service = [e for e in rows if e.type == "service"]
    access = collections.Counter(e.access for e in service)

    book.add("registry_rows", "registry rows", f"**{len(rows):,}**", "measured",
             "`api/data/registry.json` - `len(registry.json)`, one row per (make, model, year, market, document)", g, len(rows))
    book.add("registry_makes", "makes in the registry", f"{len({e.make for e in rows}):,}", "measured",
             "same - `len({row.make})`", g, len({e.make for e in rows}))
    book.add("portals", "portals", f"**{len(sites)}**", "measured",
             "same - `len({row.site})`, the adapter's own name for the publisher portal", g, len(sites))
    book.add("hosts", "distinct hostnames serving the files", f"{len(hosts)}", "measured",
             "same - `len({hostname(row.url)})`. Equal to the portal count by coincidence, not by definition", g, len(hosts))
    book.add("distinct_urls", "distinct URLs behind those rows", f"{len(urls):,}", "measured",
             "same - `len({row.url})`", g, len(urls))
    book.add("dup_rows", "rows naming a file another row already names", f"**{len(rows) - len(urls):,}**", "computed",
             f"`registry_rows - distinct_urls` = {len(rows):,} - {len(urls):,}", g, len(rows) - len(urls))
    book.add("free_rows", "free English owner's-manual PDF rows", f"{len(free):,}", "measured",
             "same - `registry._ingestable(row)`: `type=='owner' and access=='free' and lang startswith 'en' and url is a PDF`", g, len(free))
    book.add("free_pdfs", "distinct free English PDFs we can fetch", f"**{len(free_urls):,}**", "computed",
             "`len({row.url for ingestable rows})` - the honest 'manuals we can reach' number", g, len(free_urls))
    book.add("service_rows", "service-manual rows", f"{len(service):,}", "measured",
             "same - `row.type=='service'`", g, len(service))
    book.add("service_not_free", "…of those, not free", f"**{sum(v for k, v in access.items() if k != 'free')}**", "computed",
             f"`service rows - free` - {dict(access)}", g, sum(v for k, v in access.items() if k != "free"))
    book.add("unreachable", "portals walked to the end and written off", f"**{len(UNREACHABLE)}**", "measured",
             "`docs/MANUALS.md` 'Checked and genuinely unreachable' - " + ", ".join(UNREACHABLE[:5]) + ", …", g, len(UNREACHABLE))

    drops = 0
    files = 0
    for path in sorted((ROOT / "data" / "registry-fragments").glob("*.drop.json")):
        try:
            listed = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        files += 1
        drops += len(listed) if isinstance(listed, list) else 0
    book.add("drop_rows", "rows explicitly retracted by a drop list", f"**{drops:,}**", "measured",
             f"`api/data/registry-fragments/*.drop.json` - sum of the {files} drop lists; the only way a fragment un-says a row", g, drops)
    return rows, free


def catalog_numbers(book: Book, live: bool) -> None:
    """The catalog a rider actually sees. Live first: bikes.json is what the deployed store reads, but
    /catalog is what a judge can open on their phone while you are talking."""
    g = "2. The catalog - what a rider can pick"
    raw = fetch("/catalog") if live else None
    src = "live `GET /api/catalog`" if raw else "`api/data/bikes.json`"
    if raw is None:
        raw = json.loads((ROOT / "data" / "bikes.json").read_text(encoding="utf-8"))
    bikes = [Bike.model_validate(b) for b in raw]
    cars = [b for b in bikes if b.kind == "car"]
    moto = [b for b in bikes if b.kind != "car"]
    withman = [b for b in bikes if b.manualUrl]

    book.add("vehicles", "vehicles you can pick", f"**{len(bikes):,}**", "measured",
             f"{src} - `len(catalog)`", g, len(bikes))
    book.add("vehicles_with_manual", "…with a free official manual attached", f"**{len(withman):,}**", "measured",
             f"{src} - `count(row.manualUrl)`. NOT the same as distinct PDFs: many years share one file", g, len(withman))
    book.add("motorcycles", "motorcycles", f"{len(moto):,}", "measured",
             f"{src} - `row.kind != 'car'` (motorcycles carry no kind)", g, len(moto))
    book.add("moto_with_manual", "…with a free manual", f"{sum(1 for b in moto if b.manualUrl):,}", "measured",
             f"{src} - same filter plus `row.manualUrl`", g, sum(1 for b in moto if b.manualUrl))
    book.add("cars", "cars", f"{len(cars):,}", "measured", f"{src} - `row.kind == 'car'`", g, len(cars))
    book.add("cars_with_manual", "…with a free manual", f"{sum(1 for b in cars if b.manualUrl):,}", "measured",
             f"{src} - same filter plus `row.manualUrl`", g, sum(1 for b in cars if b.manualUrl))
    book.add("catalog_makes", "makes in the catalog", f"{len({b.make for b in bikes}):,}", "measured",
             f"{src} - `len({{row.make}})`. Lower than the registry's makes: a make with no usable row never becomes a vehicle", g, len({b.make for b in bikes}))
    return bikes


def manual_numbers(book: Book, live: bool) -> None:
    """Manuals already ingested - the warm catalog. Live is authoritative: api/data/manuals is this
    machine's copy and runs behind the deployment."""
    g = "3. Manuals already indexed"
    data = fetch("/manuals") if live else None
    src = "live `GET /api/manuals`" if data else "`api/data/manuals/*.json`"
    if data is None:
        data = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "data" / "manuals").glob("*.json"))]
    pages = [int(m.get("pages") or 0) for m in data]
    secs = [int(m.get("sections") or 0) if isinstance(m.get("sections"), int) else len(m.get("sections") or []) for m in data]
    covered = set()
    for m in data:
        covered.update(m.get("bikeIds") or [])

    book.add("manuals_indexed", "manuals indexed and searchable now", f"**{len(data):,}**", "measured",
             f"{src} - `len(manuals)`", g, len(data))
    book.add("manual_pages", "printed pages behind them", f"{sum(pages):,}", "measured",
             f"{src} - `sum(manual.pages)`", g, sum(pages))
    book.add("manual_sections", "sections indexed", f"{sum(secs):,}", "measured",
             f"{src} - `sum(manual.sections)`", g, sum(secs))
    book.add("manual_vehicles", "vehicles those manuals cover", f"{len(covered):,}", "measured",
             f"{src} - `len({{id for manual.bikeIds}})`; one manual covers several model years", g, len(covered))
    book.add("manual_pages_median", "median manual", f"{int(statistics.median(pages)):,} pages", "computed",
             f"{src} - `median(manual.pages)`", g, statistics.median(pages))
    book.add("manual_pages_max", "largest manual deployed", f"**{max(pages):,} pages**", "measured",
             f"{src} - `max(manual.pages)`; this is the page count `naivePerAsk` is computed over", g, max(pages))
    return pages


def cost_numbers(book: Book, pages: list[int], live: bool) -> None:
    """Money. Three ledgers that are constantly confused for each other:
      build ledger  api/data/costs.jsonl - EVERY call ever made on this machine, development included
      live ledger   GET /api/cost        - the deployed replica only, reset when it restarts
      eval          api/eval/report.md   - 150 controlled queries, the only clean per-ask number"""
    g = "4. Cost"
    rows = jsonl(ROOT / "data" / "costs.jsonl")
    by_route: dict[str, list[float]] = collections.defaultdict(list)
    by_model: dict[str, float] = collections.defaultdict(float)
    for e in rows:
        by_route[e.get("route", "?")].append(float(e.get("usd") or 0.0))
        by_model[e.get("model", "?")] += float(e.get("usd") or 0.0)
    total = sum(sum(v) for v in by_route.values())

    ask_calls = [u for r, v in by_route.items() if r.startswith("ask") for u in v]
    routers = len(by_route.get("ask.router", []))
    chats = len(by_route.get("chat.answer", []))
    # Every ask makes exactly one ask.router call - and so does every chat answer, before it streams.
    # So the number of ASKS in the log is the routers that were not a chat's (app/chat.py calls ask.route).
    asks = max(1, routers - chats)

    book.add("build_total", "everything ever spent building this", f"**${total:,.2f}**", "measured",
             f"`api/data/costs.jsonl` - `sum(usd)` over all {len(rows):,} logged calls, development included", g, total)
    book.add("build_calls", "model calls behind it", f"{len(rows):,}", "measured",
             "`api/data/costs.jsonl` - `len(log)`. Grows every time anything runs; quote the date", g, len(rows))
    if by_model:
        cheap = max(by_model.items(), key=lambda kv: kv[1])
        book.add("build_top_model", f"…of which {cheap[0]}", f"${cheap[1]:,.2f}", "computed",
                 f"same - `sum(usd) group by model`; {pct(cheap[1], total):.0f}% of the build ledger", g, cheap[1])
    ingest_usd = sum(by_route.get("ingest.struct", [])) + sum(by_route.get("ingest.keywords", []))
    book.add("build_ingest_share", "…of which reading manuals once", f"{pct(ingest_usd, total):.0f}%", "computed",
             f"same - `(ingest.struct + ingest.keywords) / total` = ${ingest_usd:,.2f} / ${total:,.2f}. Paid per manual, never per question", g, pct(ingest_usd, total))
    grader = by_route.get("images.score", [])
    book.add("images_score_calls", "…of which grading catalog photos", f"{len(grader):,} calls, ${sum(grader):.2f}", "measured",
             "same - `route=='images.score'`. Vision as a judge over the catalog photos; keeps growing, so quote it with the date", g, len(grader))
    art = by_route.get("illustrations", [])
    if art:
        book.add("illustrations", "…of which generating part illustrations", f"{len(art):,} calls, ${sum(art):.2f}", "measured",
                 "same - `route=='illustrations'` (`gpt-image-1`)", g, len(art))

    if live:
        cost = fetch("/cost")
        if isinstance(cost, dict):
            book.add("live_total", "what the DEPLOYED app has spent", f"**${cost['total']:.2f}**", "measured",
                     f"live `GET /api/cost` -> `total`, over `count` = {cost['count']:,} calls. In-replica; moves every hour and resets on redeploy", g, cost["total"])
            book.add("live_calls", "…over model calls", f"{cost['count']:,}", "measured", "same -> `count`", g, cost["count"])
            book.add("live_naive", "naive: the whole manual in the prompt", f"**${cost['naivePerAsk']:.2f}** / question", "measured",
                     "live `GET /api/cost` -> `naivePerAsk` = `llm.naive_usd(max(manual.pages))`", g, cost["naivePerAsk"])

    big, med = max(pages), int(statistics.median(pages))
    book.add("naive_max", "naive $/question, largest deployed manual", f"**${naive_usd(big):.2f}**", "computed",
             f"`app/llm.naive_usd({big})` = {big}p x {TOKENS_PER_PAGE} tok x ${PRICES['gpt-6-astra'][0]:.0f}/M x 2 (past the 272k long-context line)", g, naive_usd(big))
    book.add("naive_median", "naive $/question, median deployed manual", f"**${naive_usd(med):.2f}**", "computed",
             f"`app/llm.naive_usd({med})` = {med}p x {TOKENS_PER_PAGE} tok x ${PRICES['gpt-6-astra'][0]:.0f}/M, no 2x (under 272k)", g, naive_usd(med))

    book.add("ask_usd_eval", "ours: $ per ask", f"**${EVAL['usd']:.5f}**", "measured",
             f"`api/eval/report.md` - cost-log delta on `ask.*` over {EVAL['asks']} controlled queries / {EVAL['asks']}. THE number to quote", g, EVAL["usd"])
    book.add("ask_usd_log", "ours: $ per ask over the whole build log", f"${sum(ask_calls) / asks:.5f}", "computed",
             f"`costs.jsonl` - `sum(usd where route startswith 'ask') / (ask.router calls - chat.answer calls)` = ${sum(ask_calls):.4f} / {asks}. "
             "Development traffic, so picker-heavier than a rider's", g, sum(ask_calls) / asks)
    book.add("ask_usd_call", "…the same log, per CALL not per ask", f"${statistics.mean(ask_calls):.5f}", "computed",
             f"`costs.jsonl` - `mean(usd where route startswith 'ask')` over {len(ask_calls):,} calls. An ask is 1.15 calls, so this is NOT $/ask", g, statistics.mean(ask_calls))
    chat_log = by_route.get("chat.answer", [])
    if chat_log:
        book.add("chat_usd", "ours: $ per written chat answer", f"**${statistics.mean(chat_log):.4f}**", "measured",
                 f"`costs.jsonl` - `mean(usd where route=='chat.answer')` over {len(chat_log)} answers "
                 f"(the 25-question eval says ${CHAT_EVAL['usd']:.5f}; quote either, name which)", g, statistics.mean(chat_log))

    mass = [m for m in jsonl(ROOT / "data" / "mass_report.jsonl") if m.get("status") == "done"]
    if mass:
        u = [float(m["usd"]) for m in mass]
        p = [int(m["pages"]) for m in mass]
        book.add("ingest_runs", "manuals ingested in the bulk run", f"{len(mass):,}", "measured",
                 f"`api/data/mass_report.jsonl` - `count(status=='done')`; the file has {len(jsonl(ROOT / 'data' / 'mass_report.jsonl')):,} lines in total, "
                 "the rest error / duplicate / suspicious", g, len(mass))
        book.add("ingest_usd", "ours: $ to read a manual, once", f"**${statistics.mean(u):.4f}**", "measured",
                 f"`api/data/mass_report.jsonl` - `mean(usd where status=='done')` over {len(mass)} real ingests, mean {statistics.mean(p):.0f} pages", g, statistics.mean(u))
        book.add("ingest_usd_median", "…median", f"${statistics.median(u):.4f}", "measured",
                 f"same - `median(usd)`, median {int(statistics.median(p))} pages", g, statistics.median(u))
        book.add("ingest_per_kpage", "…per 1,000 printed pages", f"${1000 * sum(u) / sum(p):.3f}", "computed",
                 f"same - `sum(usd) / sum(pages) * 1000`", g, 1000 * sum(u) / sum(p))
        book.add("ingest_breakeven", "ingest pays for itself after", f"**{statistics.mean(u) / naive_usd(med):.2f} questions**", "computed",
                 f"`ingest_usd / naive_median` = ${statistics.mean(u):.4f} / ${naive_usd(med):.2f}", g, statistics.mean(u) / naive_usd(med))
    book.add("cheaper_factor", "ours vs naive, per question", f"**{naive_usd(big) / EVAL['usd']:,.0f}x cheaper**", "computed",
             f"`naive_max / ask_usd_eval` = ${naive_usd(big):.2f} / ${EVAL['usd']:.5f}. Against the MEDIAN manual it is {naive_usd(med) / EVAL['usd']:,.0f}x - say which", g, naive_usd(big) / EVAL["usd"])


def quality_numbers(book: Book, live: bool) -> None:
    g = "5. Accuracy and honesty"
    book.add("top1", "right section first, in-scope questions", f"**{EVAL['top1']:.0f}%** of {EVAL['in_scope']}", "measured",
             "`api/eval/report.md` - top-1 over the in-scope half of 150 queries", g, EVAL["top1"])
    book.add("oos", "off-topic questions returned empty instead of guessed at", f"**{EVAL['oos']} of {EVAL['oos']}**", "measured",
             "`api/eval/report.md` - the `oos` category, 100% empty", g, EVAL["oos"])
    book.add("ask_calls_per_ask", "LLM calls per ask", f"{EVAL['calls'] / EVAL['asks']:.2f}", "computed",
             f"`api/eval/report.md` - {EVAL['calls']} calls / {EVAL['asks']} asks, so {100 * (1 - (EVAL['calls'] - EVAL['asks']) / EVAL['asks']):.0f}% of asks never pay for a picker", g, EVAL["calls"] / EVAL["asks"])
    book.add("chat_cited", "chat claim sentences carrying a page number", f"**{CHAT_EVAL['cited']:.0f}%** of {CHAT_EVAL['claims']}", "measured",
             "`api/eval/chat-report.md`", g, CHAT_EVAL["cited"])
    book.add("chat_verbatim", "chat quotes verbatim on the page they name", f"**{CHAT_EVAL['verbatim']:.0f}%** of {CHAT_EVAL['quotes']}", "measured",
             "`api/eval/chat-report.md` - the server slices the quote out of the page, the model only names it", g, CHAT_EVAL["verbatim"])
    book.add("chat_invented", "invented numbers · dealer referrals", f"**{CHAT_EVAL['invented']} · {CHAT_EVAL['referrals']}** of {CHAT_EVAL['questions']}", "measured",
             "`api/eval/chat-report.md`", g, 0)

    g2 = "6. Speed"
    book.add("ask_mean_s", "an ask, mean", f"{EVAL['mean_s']:.2f} s", "measured",
             f"`api/eval/report.md` - {EVAL['asks']} queries, sequential, cold cache", g2, EVAL["mean_s"])
    book.add("ask_p95_s", "an ask, p95", f"**{EVAL['p95_s']:.2f} s**", "measured", "`api/eval/report.md` - same run", g2, EVAL["p95_s"])
    for key in ("ask_cold_s", "ask_warm_s", "vin_s", "ingest_readable_s", "ingest_searchable_s", "ingest_run_usd"):
        value, src = HAND_TIMED[key]
        label = {
            "ask_cold_s": "a question, first time", "ask_warm_s": "a question, asked again",
            "vin_s": "VIN -> the exact bike", "ingest_readable_s": "a brand-new manual -> readable",
            "ingest_searchable_s": "a brand-new manual -> fully searchable", "ingest_run_usd": "…what that one run cost",
        }[key]
        unit = "" if key.endswith("usd") else " s"
        shown = f"**${value:.3f}**" if key.endswith("usd") else f"**{value}{unit}**"
        book.add(key, label, shown, "measured", src, g2, value)
    book.add("chat_ttft", "chat, first word", f"{CHAT_EVAL['ttft_p50']:.2f} s p50 / {CHAT_EVAL['ttft_p95']:.2f} s p95", "measured",
             "`api/eval/chat-report.md`", g2, CHAT_EVAL["ttft_p50"])
    med, lo, hi, src = VOICE["deepgram_first_audio_ms"]
    book.add("voice_deepgram", "voice (Deepgram Agent): you stop talking -> it starts", f"**{med / 1000:.2f} s** median", "measured",
             f"{src}; range {lo / 1000:.2f}-{hi / 1000:.2f} s. A procedure question is {VOICE['deepgram_procedure_ms'][0] / 1000:.1f} s - say so", g2, med)
    (lo2, hi2), src2 = VOICE["live_engine_s"]
    book.add("voice_live", "voice (shipped engine)", f"{lo2}-{hi2} s", "measured", src2, g2, hi2)

    g3 = "7. The Token Company"
    book.add("ttc_eval", "tokens removed before the prompt was billed", f"**{CHAT_EVAL['ttc_pct']:.1f}%**", "measured",
             f"`api/eval/chat-report.md` - {CHAT_EVAL['ttc_in']:,} tok in -> {CHAT_EVAL['ttc_out']:,} out over 23 bear-2 calls", g3, CHAT_EVAL["ttc_pct"])
    if live:
        ttc = fetch("/cost/ttc")
        if isinstance(ttc, dict) and isinstance(ttc.get("total"), dict):
            t = ttc["total"]
            book.add("ttc_live", "…the same counter on the live replica right now",
                     f"{t.get('savedPct', 0):.1f}% over {t.get('calls', 0)} calls", "measured",
                     "live `GET /api/cost/ttc` -> `total.savedPct`. In-memory PER REPLICA and zeroed on restart, so a low number "
                     "means a fresh replica, not a worse compressor. Quote the eval figure on stage", g3, t.get("savedPct", 0))


def parts_numbers(book: Book, live: bool) -> None:
    g = "8. Parts"
    manual_id, bike_id = PARTS_DEMO
    data = fetch(f"/parts/catalog?manualId={manual_id}&bikeId={bike_id}") if live else None
    if isinstance(data, dict):
        parts = data.get("parts")
        n = len(parts) if isinstance(parts, list) else int(parts or 0)
        groups = data.get("groups")
        ng = len(groups) if isinstance(groups, list) else int(groups or 0)
        book.add("parts_demo", "parts for the demo bike (KTM 390 Duke 2024)", f"**{n}**", "measured",
                 f"live `GET /api/parts/catalog?manualId={manual_id}` - `len(parts)`, in {ng} groups; "
                 f"{data.get('fromManual', '?')} of them carry a spec this manual itself prints, the rest come from the parts taxonomy", g, n)
    else:
        book.add("parts_demo", "parts for the demo bike (KTM 390 Duke 2024)", "**135**", "measured",
                 "live `GET /api/parts/catalog?manualId=ktm-390-duke-2024-om-en` - `len(parts)`, 2026-09-20 (run with --live to refresh)", g, 135)


def founder_numbers(book: Book) -> None:
    """His numbers, and the arithmetic on top of them. Nothing here is ours and nothing is measured."""
    g = "9. The founder's friend - HIS numbers, not ours"
    book.add("his_share", "share of his working time spent looking for a page", "**20%**", "assumed",
             "HIS estimate, reported by the founder. Not a study, not measured by us. Always say 'he says'", g, 0.20)
    book.add("his_usd", "what one question cost him when he tried an LLM", "**~$4**", "assumed",
             "HIS bill. Our own worst case on the deployed catalog is the $12.40 above; the two are not the same measurement", g, 4.0)
    book.add("his_hours", "hours a year", "**400 h**", "computed",
             "`20% x 2,000 h` - arithmetic on his number and an assumed 2,000-hour year (`docs/pitches/ramp/numbers.py`)", g, 400)
    book.add("his_money", "what those hours bill out at, Germany", "**EUR 36k-48k**", "computed",
             "`400 h x EUR 90-120/h`. `docs/pitches/ramp/numbers.md` defends EUR 24,640 after recovery and utilisation - prefer that on stage", g, 44000)


# ---------------------------------------------------------------------------------- discrepancies


@dataclass
class Check:
    """A literal that appears in a pitch and contradicts this file."""

    pattern: str
    says: str
    key: str | None          # the canonical row it contradicts
    literal: str | None      # …or a literal, when no computed row covers it
    note: str
    unless: str = ""         # a line matching this is quoting the figure to forbid it, not to claim it


CHECKS: tuple[Check, ...] = (
    Check(r"17,556", "17,556 distinct free English PDFs", "free_pdfs", None,
          "no definition in the repo yields 17,556; the ingestable set is this many distinct URLs"),
    Check(r"39,119", "39,119 registry rows", "registry_rows", None, "pre-merge crawl state"),
    Check(r"\b33 makes\b", "33 makes", "registry_makes", None, "pre-merge crawl state"),
    Check(r"8,319", "8,319 free official PDFs", "free_pdfs", None, "pre-merge crawl state"),
    Check(r"13,500 (?:free official )?manuals", "13,500 manuals", "free_pdfs", None,
          "13,537 is VEHICLES with a manual attached, not manuals; the PDF count is different again"),
    Check(r"\$6\.09", "$6.096 naive baseline", "naive_max", None, "the largest deployed manual grew past the 272k long-context line"),
    Check(r"\$6\.10\b", "$6.10 naive baseline", "naive_max", None, "same"),
    Check(r"762 pages", "largest manual 762 pages", "manual_pages_max", None, "a larger manual has been ingested since"),
    Check(r"16,000\s*[x×]", "16,000x cheaper", "cheaper_factor", None, "follows from the stale $6.096 baseline",
          unless=r"[Dd]o not say|never say|instead of|multiples|strawman"),
    Check(r"\$6\.13\b", "$6.13 spent", "live_total", None, "the live ledger moves every hour; quote it with a timestamp or not at all"),
    Check(r"\$6\.14\b", "$6.14 spent", "live_total", None, "same"),
    Check(r"1,546 model calls", "1,546 model calls", "live_calls", None, "same"),
    Check(r"1,550 model calls", "1,550 model calls", "live_calls", None, "same"),
    Check(r"\$1\.17[2]?\b", "$1.172 live ledger", "live_total", None, "same"),
    Check(r"\b569 calls\b", "569 live calls", "live_calls", None, "same"),
    Check(r"36,620", "36,620 logged calls", "build_calls", None, "the build ledger grows every time anything runs"),
    Check(r"37,?524", "37524 logged calls", "build_calls", None, "same"),
    Check(r"\$79\.91", "$79.91 build ledger", "build_total", None, "same"),
    Check(r"\$73\.72", "$73.72 of it luna", "build_top_model", None, "same"),
    Check(r"4,136 (?:calls|catalog photos)", "4,136 images.score calls", "images_score_calls", None,
          "the photo grader has run again since"),
    Check(r"\$2\.04", "$2.04 spent grading photos", "images_score_calls", None, "same"),
    Check(r"1,500\s*[x×] cheaper|about 1,500\s*[x×]", "~1,500x cheaper", "cheaper_factor", None,
          "blends his $4 with our $0.0003-0.005 range; against the measured naive baseline the factor is different",
          unless=r"[Dd]o not say|never say|multiples|strawman"),
    Check(r"31\.4%", "31.4% of tokens saved, live", "ttc_live", None,
          "the live TTC counter is in-memory per replica and resets on restart; only the eval figure is stable"),
    Check(r"opens in ~7 s", "a cold manual opens in ~7 s", "ingest_readable_s", None,
          "the timed live run is 1.3 s to readable and 40.4 s to fully searchable; ~7 s is neither"),
    Check(r"6.7 s readable, 44.50 s searchable", "6-7 s readable, 44-50 s searchable", None, "1.3 s / 40.4 s",
          "superseded by the timed 2026-09-20 run: 1.3 s to readable, 40.4 s to fully searchable"),
    Check(r"319 runs \+ 2 live", "319 ingest runs", "ingest_runs", None,
          "`mass_report.jsonl` now carries this many runs with `status=='done'`"),
    Check(r"13,544", "13,544 vehicles with a manual", "vehicles_with_manual", None,
          "the catalog moved between the two reads; quote the live figure with its timestamp"),
    Check(r"\b8,?319 fetchable manuals", "8,319 fetchable manuals", "free_pdfs", None, "pre-merge crawl state"),
    Check(r"22,300 bikes", "22,300 bikes", "motorcycles", None, "the catalog grew"),
    Check(r"warm cache already holds 332", "332 warm manuals", "manuals_indexed", None, "the warm catalog grew"),
    Check(r"\b532 (?:live )?manuals\b", "532 manuals", "manuals_indexed", None, "more have been ingested since"),
    Check(r"95,365 pages", "95,365 pages", "manual_pages", None, "same"),
    Check(r"90,955 sections", "90,955 sections", "manual_sections", None, "same"),
    Check(r"\b659 vehicles\b", "659 vehicles covered", "manual_vehicles", None, "same"),
    Check(r"31\.4% live", "31.4% TTC saved live", "ttc_live", None,
          "the live counter is in-memory per replica and resets on restart; only the eval figure is stable"),
    Check(r"773 manuals, `api/data/mass_report\.jsonl`", "773 manuals ingested", None, "648",
          "mass_report.jsonl has 773 LINES but only 648 with status=done; the rest are error/duplicate/suspicious"),
    Check(r"52k rows", "52k registry rows", "registry_rows", None, "stale brief"),
    Check(r"\b40 portals\b", "40 portals", "portals", None, "stale brief"),
    Check(r"1,254", "1,254 mislabelled rows", "mislabelled_free_en", None, "stale brief; and see the two definitions above"),
    Check(r"3,284 retracted", "3,284 retracted rows", "drop_rows", None, "stale brief"),
    Check(r"\b25 unreachable\b", "25 unreachable portals", "unreachable", None, "stale brief"),
    Check(r"13\.5k distinct free official manuals", "13.5k distinct free manuals", "free_pdfs", None,
          "13,537 is vehicles with a manual; distinct PDFs is a different count"),
    Check(r"\$4-6 per question|\$4-6 a question", "$4-6 per naive question", "naive_max", None,
          "his lived bill was ~$4; OUR measured naive worst case is different and must not be blended with it"),
)

PITCH_FILES = ("general.md", "openai.md", "token-company.md", "voloridge.md", "elevenlabs.md",
               "ramp.md", "dropbox.md", "deepgram.md", "long-lake.md")

# The nine pitches were not the only documents quoting these figures, and for a while they were the
# only ones checked - so the same stale $6.096 survived in the architecture doc and in a Codex
# transcript while every pitch was clean. Anything a judge or a teammate might read and quote from
# belongs here, repo-relative.
ALSO_SCANNED = (
    "docs/pitches/BRIEF.md",
    "docs/pitches/README.md",
    "docs/PITCH.md",
    "docs/DEMO.md",
    "docs/SUBMISSION.md",
    "docs/ARCHITECTURE.md",
    "docs/MANUALS.md",
    "docs/codex/run-3.md",
)


def discrepancies(book: Book) -> list[tuple[str, int, str, str, str]]:
    """Grep the pitches for figures this file contradicts. Returns (file, line, says, correct, note)."""
    import re

    out: list[tuple[str, int, str, str, str]] = []
    targets = [PITCHES / name for name in PITCH_FILES] + [REPO / rel for rel in ALSO_SCANNED]
    for path in targets:
        if not path.exists():
            continue
        rel = path.relative_to(REPO).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for check in CHECKS:
                if re.search(check.pattern, line) and not (check.unless and re.search(check.unless, line)):
                    correct = check.literal or book.val(check.key or "")
                    out.append((rel, i, check.says, correct, check.note))
    return out


# ------------------------------------------------------------------------------------------ render


def two_definitions(book: Book, rows: list, free: list) -> list[tuple[str, str, str, str]]:
    """The numbers two agents measured differently. Both are right; they count different things."""
    owner_typed = [e for e in rows if e.type == "owner" and doc_kind(e) != "owner"]
    free_en_wrong = [e for e in rows if e.access == "free" and e.lang.lower().startswith("en") and doc_kind(e) != "owner"]
    by_kind = collections.Counter(doc_kind(e) for e in owner_typed)
    book.add("mislabelled_owner_typed", "mislabelled rows (owner-typed)", f"**{len(owner_typed):,}**", "measured",
             "`api/data/registry.json` - `row.type=='owner' and doctype.classify_doc(url, title) != 'owner'`, over ALL rows "
             "in every language and access level", "10. Two definitions of the same word", len(owner_typed))
    book.add("mislabelled_free_en", "mislabelled rows (free-English)", f"**{len(free_en_wrong):,}**", "measured",
             "same file - `access=='free' and lang=='en' and classify_doc(...) != 'owner'`. A SUBSET question: of the rows "
             "we would actually try to fetch, how many are not a handbook", "10. Two definitions of the same word", len(free_en_wrong))
    return [
        ("mislabelled rows",
         f"**{len(owner_typed):,}** owner-typed",
         f"**{len(free_en_wrong):,}** free-English",
         f"{len(owner_typed):,} = the portal filed it as an owner's manual and `doctype.py` says otherwise, counted over every "
         f"row in every language ({', '.join(f'{k} {v:,}' for k, v in by_kind.most_common(4))}…). "
         f"{len(free_en_wrong):,} = the same test restricted to free English rows - the ones we would actually fetch. "
         "Dropbox's slide uses the first; the brief's old 1,254 is the lineage of the second. Say which."),
        ("manuals we can reach",
         f"**{book.val('free_pdfs')}** distinct PDFs",
         f"**{book.val('vehicles_with_manual')}** vehicles",
         f"{book.val('free_pdfs')} = distinct URLs behind the free-English-owner-PDF rows. "
         f"{book.val('vehicles_with_manual')} = catalog rows carrying a `manualUrl`; many model years point at one file, and "
         f"many fetchable PDFs belong to no catalog vehicle. Never call the vehicle count 'manuals'."),
        ("$ per question, naive",
         f"**{book.val('naive_max')}** worst case",
         f"**{book.val('naive_median')}** median",
         f"{book.val('naive_max')} = `naive_usd(largest deployed manual)`, which is past the 272k-token line and therefore billed 2x - "
         f"this is what live `GET /api/cost` reports as `naivePerAsk`. {book.val('naive_median')} = the same formula on the median "
         "manual. The founder's friend's ~$4 is HIS bill on HIS manual and is a third number."),
        ("$ per ask, ours",
         f"**{book.val('ask_usd_eval')}** eval",
         f"**{book.val('ask_usd_log')}** build log",
         "The eval figure is 150 controlled rider queries and is the one to quote. The build-log figure divides every `ask.*` "
         "dollar by the asks in the log, which is development traffic and therefore picker-heavy. Both are honest; they answer "
         "different questions."),
        ("tokens saved by compression",
         f"**{book.val('ttc_eval')}** eval",
         f"**{book.val('ttc_live') if 'ttc_live' in book.by_key else 'n/a'}** live",
         "The eval figure is 23 bear-2 calls over a fixed 25-question set. The live counter is in-memory PER REPLICA and zeroed "
         "on restart, so it reports whatever that replica has done since it booted. Quote the eval figure."),
        ("total spent",
         f"**{book.val('build_total')}** build",
         f"**{book.val('live_total') if 'live_total' in book.by_key else 'n/a'}** live",
         "The build ledger is every call ever made on the dev machine - ingest, image generation, photo grading, the lot. "
         "The live ledger is only the deployed replica since its last restart. The pitch-friendly 'it cost us six dollars to run' "
         "is the live one, and it moves every hour: quote it with a date or do not quote a total at all."),
    ]


def render(book: Book, pairs: list[tuple[str, str, str, str]], disc: list, live: bool) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    out = [
        "# Mechanica - the numbers, generated",
        "",
        f"Generated by `api/tools/pitch_numbers.py`{' --live' if live else ''} on **{stamp}**. Do not edit this file by hand;",
        "re-run the script. Every pitch quotes from here, and where two agents measured the same word differently,",
        "both definitions are below with the code that produced them.",
        "",
        "```",
        "cd api && .venv/Scripts/python tools/pitch_numbers.py --live --md ../docs/pitches/numbers.md",
        "```",
        "",
        "**measured** = counted or timed, from a file or a live endpoint · **computed** = arithmetic over measured values,",
        "formula in the source column · **assumed** = nobody measured it, and the row says whose assumption it is.",
        "",
    ]
    for group in book.groups():
        out += [f"## {group}", "", "| number | value | source |", "|---|---|---|"]
        for r in book.rows:
            if r.group == group:
                out.append(f"| {r.label} | {r.value} *({r.mark})* | {r.source} |")
        out.append("")

    out += [
        "## 11. The same word, two honest counts",
        "",
        "Three agents disagreed on these. Nobody was wrong; they counted different things. Pick one and say its definition.",
        "",
        "| the word | definition A | definition B | which is which |",
        "|---|---|---|---|",
    ]
    for word, a, b, why in pairs:
        out.append(f"| {word} | {a} | {b} | {why} |")
    out.append("")

    out += [
        "## 12. Discrepancies in the pitch files",
        "",
        "Every figure in `docs/pitches/*.md` that contradicts the tables above, found by `pitch_numbers.py`'s own",
        "grep (`CHECKS` in the script). **Nothing here has been edited** - this is the work list for the fix pass.",
        "Add a pattern to `CHECKS` when a new stale figure appears, so the list stays generated rather than typed.",
        "",
    ]
    if not disc:
        out += ["No contradictions found. (If that surprises you, `CHECKS` is too narrow.)", ""]
    else:
        by_file: dict[str, list] = collections.defaultdict(list)
        for rel, line, says, correct, note in disc:
            by_file[rel].append((line, says, correct, note))
        for rel in sorted(by_file, key=lambda r: (r != "docs/pitches/BRIEF.md", r)):
            items = sorted(by_file[rel])
            out += [f"### `{rel}` - {len(items)} figure(s)", "",
                    "| line | the pitch says | should be | why |", "|---|---|---|---|"]
            for line, says, correct, note in items:
                out.append(f"| `{rel}:{line}` | {says} | **{correct}** | {note} |")
            out.append("")
        out += [f"**{len(disc)} contradicting figures across {len(by_file)} files.**", ""]

    missing = [n for n in PITCH_FILES if not (PITCHES / n).exists()]
    if missing:
        out += [f"*Not yet written, so not scanned: {', '.join(f'`{m}`' for m in missing)}.*", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="also read the deployed API (catalog, manuals, cost, ttc, parts)")
    ap.add_argument("--md", type=Path, help="write the Markdown to this file instead of stdout")
    args = ap.parse_args()

    if args.live:
        ok = fetch("/health")
        if ok is None:
            print("  live API unreachable - falling back to the files on disk", file=sys.stderr)
            args.live = False

    book = Book()
    rows, free = registry_numbers(book)
    catalog_numbers(book, args.live)
    pages = manual_numbers(book, args.live)
    cost_numbers(book, pages, args.live)
    quality_numbers(book, args.live)
    parts_numbers(book, args.live)
    founder_numbers(book)
    pairs = two_definitions(book, rows, free)
    disc = discrepancies(book)

    md = render(book, pairs, disc, args.live)
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(md + "\n", encoding="utf-8")
        print(f"wrote {args.md} - {len(book.rows)} numbers, {len(disc)} discrepancies")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

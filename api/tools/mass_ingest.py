"""Ingest every free English owner's manual PDF in the registry, most useful first, without babysitting.

    python -m tools.mass_ingest --plan                 # build data/mass_plan.json (dedupe + priority)
    python -m tools.mass_ingest --bench                # coverage per model/batch on the two reference manuals
    python -m tools.mass_ingest --run --hours 12       # foreground until plan exhausted / budget hit
    python -m tools.mass_ingest --status               # what the running job is doing

One manual id per unique PDF, linked to every bike the registry rows covered. The structure pass is spread over
several models because OpenAI rate limits are per model; each manual is routed to the bucket with the most headroom.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app import ingest, llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.ingest import curate as curate_mod, structure  # noqa: E402
from app.models import Bike, IngestJob, Manual  # noqa: E402
from app.ondemand import is_pdf as _is_pdf, slug  # noqa: E402
from app.store import get_store  # noqa: E402

DATA = settings.data_dir
PLAN_PATH = DATA / "mass_plan.json"
STATE_PATH = DATA / "mass_state.json"
REPORT_PATH = DATA / "mass_report.jsonl"
HASH_PATH = DATA / "mass_hashes.json"

BUDGET_USD = float(os.getenv("MASS_BUDGET_USD", "900"))
PDF_CAP_BYTES = int(float(os.getenv("MASS_PDF_CAP_GB", "20")) * 1e9)
MAX_PDF_BYTES = 80 * 1024 * 1024
DOWNLOAD_SLOTS = 8
DOWNLOAD_RETRIES = 3
STATE_EVERY = 30.0
DISK_PAUSE_GIVEUP = 20 * 60.0
TOKENS_PER_MANUAL = 75_000
AVG_MINUTES = 2.5

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
AGENTS = (BROWSER, GOOGLEBOT)

# tokens/min, requests/min as the API reports them (gpt-5-mini / gpt-5-nano send no headers: assume the small tier)
LIMITS: dict[str, tuple[int, int]] = {
    "gpt-5.6-luna": (500_000, 500),
    "gpt-5.4-mini": (200_000, 500),
    "gpt-5-mini": (200_000, 500),
    "gpt-5.4-nano": (200_000, 500),
    "gpt-5-nano": (200_000, 500),
}
BASELINE_MODEL = "gpt-5.6-luna"
REFERENCES = ("ktm-390-duke-2024-om-en", "bmw-r12gs-2025-rm-en")

log = logging.getLogger("mass")
_tl = threading.local()


# ---------------------------------------------------------------- rate limits


class Bucket:
    """Token + request bucket for one model. Halves itself on 429 and creeps back on success."""

    def __init__(self, model: str, tpm: int, rpm: int):
        self.model = model
        self.tpm = float(tpm)
        self.rpm = float(rpm)
        self.scale = 1.0
        self.tokens = float(tpm)
        self.reqs = float(rpm)
        self.ts = time.monotonic()
        self.lock = threading.Lock()
        self.used = 0
        self.calls = 0
        self.usd = 0.0
        self.throttles = 0
        self.manuals = 0

    def _refill(self) -> None:
        now = time.monotonic()
        dt, self.ts = now - self.ts, now
        self.tokens = min(self.tpm * self.scale, self.tokens + self.tpm * self.scale * dt / 60.0)
        self.reqs = min(self.rpm * self.scale, self.reqs + self.rpm * self.scale * dt / 60.0)

    def headroom(self) -> float:
        with self.lock:
            self._refill()
            return min(self.tokens / self.tpm, self.reqs / self.rpm)

    def acquire(self, est: int) -> None:
        est = min(est, int(self.tpm * 0.9))
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= est and self.reqs >= 1:
                    self.tokens -= est
                    self.reqs -= 1
                    return
                per_sec_t = self.tpm * self.scale / 60.0
                per_sec_r = self.rpm * self.scale / 60.0
                wait = max((est - self.tokens) / per_sec_t if self.tokens < est else 0.0,
                           (1 - self.reqs) / per_sec_r if self.reqs < 1 else 0.0)
            time.sleep(min(5.0, max(0.05, wait)))

    def settle(self, est: int, actual: int) -> None:
        with self.lock:
            self.tokens -= max(0, actual - est)
            self.used += actual
            self.calls += 1

    def penalize(self) -> None:
        with self.lock:
            self.scale = max(0.2, self.scale * 0.5)
            self.tokens = min(self.tokens, 0.0)
            self.throttles += 1

    def recover(self) -> None:
        if self.scale < 1.0:
            with self.lock:
                self.scale = min(1.0, self.scale * 1.05)


BUCKETS: dict[str, Bucket] = {}
_spend = 0.0
_spend_lock = threading.Lock()
_per_manual: dict[str, float] = defaultdict(float)


def install_buckets(models: list[str]) -> None:
    for m in models:
        tpm, rpm = LIMITS.get(m, (200_000, 500))
        BUCKETS[m] = Bucket(m, tpm, rpm)


def pick_model() -> str:
    return max(BUCKETS.values(), key=lambda b: b.headroom()).model


def _status_of(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status"):
        code = getattr(exc, attr, None)
        if isinstance(code, int):
            return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def patch_llm() -> None:
    """Every OpenAI call goes through llm.structured; wrap it with the bucket, the backoff and the cost ledger."""
    original_structured = llm.structured
    original_log = llm.log

    def structured(route, model, schema, system, user, reasoning=None):
        text = user if isinstance(user, str) else " ".join(p.get("text", "") for p in user if isinstance(p, dict))
        est = int((len(system) + len(text)) / 3.6) + 1800
        bucket = BUCKETS.get(model)
        delay = 1.5
        last: Exception | None = None
        for attempt in range(5):
            if bucket:
                bucket.acquire(est)
            _tl.est = est
            try:
                out = original_structured(route, model, schema, system, user, reasoning)
                if bucket:
                    bucket.recover()
                return out
            except Exception as exc:
                last = exc
                code = _status_of(exc)
                rate = code == 429 or "rate limit" in str(exc).lower()
                if bucket and rate:
                    bucket.penalize()
                transient = rate or (code or 0) >= 500 or code in (408, 409) or isinstance(exc, httpx.TransportError)
                if attempt == 4 or not transient:
                    raise
                time.sleep(delay + random.random())
                delay = min(45.0, delay * 2)
        raise last or RuntimeError("structured failed")

    def logged(route, model, usage):
        cost = original_log(route, model, usage)
        total = int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "output_tokens", 0) or 0)
        bucket = BUCKETS.get(model)
        if bucket:
            bucket.settle(int(getattr(_tl, "est", 0) or 0), total)
            with bucket.lock:
                bucket.usd += cost
        global _spend
        with _spend_lock:
            _spend += cost
            owner = getattr(_tl, "manual_id", None)
            if owner:
                _per_manual[owner] += cost
        return cost

    llm.structured = structured
    llm.log = logged


def inherit_manual_id() -> None:
    """structure.py fans out over its own pool; worker threads must keep the manual they were started for."""
    thread_init, thread_run = threading.Thread.__init__, threading.Thread.run

    def init(self, *a, **kw):
        thread_init(self, *a, **kw)
        self._mass_owner = getattr(_tl, "manual_id", None)

    def run(self):
        owner = getattr(self, "_mass_owner", None)
        if owner:
            _tl.manual_id = owner
        thread_run(self)

    threading.Thread.__init__ = init
    threading.Thread.run = run


class NoIndex:
    """4k manuals of BM25 will not fit in RAM and the API rebuilds the index from the store anyway."""

    def index(self, manual, pages, specs) -> None:
        return None

    def remove(self, manual_id) -> None:
        return None

    def query(self, *a, **kw):
        return []

    def spec(self, *a, **kw):
        return []


def quiet_store() -> None:
    """jobs.json is a UI progress file; rewriting it hundreds of times per manual would serialise the whole run."""
    import app.search as search_mod

    search_mod._index = NoIndex()
    store = get_store()
    store.put_job = lambda job: None
    store.job = lambda job_id: None


# ---------------------------------------------------------------- plan


NOT_A_PDF = ("_ebook",)  # Kawasaki's ebook viewer: the URL passes _is_pdf but serves HTML


def load_rows() -> list[dict]:
    rows = json.loads((DATA / "registry.json").read_text(encoding="utf-8"))
    return [
        r
        for r in rows
        if r.get("type") == "owner"
        and r.get("access") == "free"
        and str(r.get("lang", "")).lower().startswith("en")
        and r.get("url")
        and _is_pdf(r["url"])
        and not any(bad in r["url"] for bad in NOT_A_PDF)
    ]


def build_plan(bench: dict | None = None) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in load_rows():
        groups[row["url"].strip()].append(row)

    taken: set[str] = set()
    entries: list[dict] = []
    for url in sorted(groups):  # stable ids: a rebuild must not hand a manual id to a different PDF
        rows = groups[url]
        years = sorted({y for r in rows for y in (r.get("years") or [])})
        primary = max(rows, key=lambda r: (max(r.get("years") or [0]), len(r.get("model") or "")))
        make, model, market = primary["make"], primary["model"], primary["market"]
        year = max(years) if years else 0
        manual_id = slug(make, model, year or "", market, "om")
        if manual_id in taken:
            manual_id = f"{manual_id}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"
        taken.add(manual_id)
        bikes: dict[str, list] = {}
        for r in rows:
            for y in r.get("years") or []:
                bikes.setdefault(slug(r["make"], r["model"], y), [r["make"], r["model"], y, r["market"]])
        entries.append(
            {
                "manualId": manual_id,
                "url": url,
                "make": make,
                "model": model,
                "year": year,
                "market": market,
                "rows": len(rows),
                "bikeIds": sorted(bikes),
                "bikes": [bikes[k] for k in sorted(bikes)],
            }
        )

    by_brand: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_brand[e["make"]].append(e)
    for brand in by_brand.values():
        brand.sort(key=lambda e: (-e["year"], e["model"].lower()))

    ordered: list[dict] = []
    for tier in (0, 1):
        queues = {
            make: deque(e for e in rows if (0 if e["year"] >= 2015 else 1) == tier)
            for make, rows in by_brand.items()
        }
        while any(queues.values()):
            for make in sorted(queues, key=lambda m: -len(queues[m])):
                if queues[make]:
                    ordered.append(queues[make].popleft())
    for i, e in enumerate(ordered):
        e["priority"] = i

    plan = {
        "generatedAt": time.time(),
        "dataDir": str(DATA),
        "registryRows": sum(len(v) for v in groups.values()),
        "uniqueUrls": len(groups),
        "bikesCovered": len({b for e in ordered for b in e["bikeIds"]}),
        "byBrand": {m: len(v) for m, v in sorted(by_brand.items(), key=lambda kv: -len(kv[1]))},
        "byYear": dict(sorted(((str(y), sum(1 for e in ordered if e["year"] == y)) for y in {e["year"] for e in ordered}), reverse=True)),
        "models": bench or (load_plan() or {}).get("models", {}),
        "entries": ordered,
    }
    write_json(PLAN_PATH, plan)
    return plan


def load_plan() -> dict | None:
    if not PLAN_PATH.exists():
        return None
    try:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- bench


def norm_title(title: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in title.lower()).split())


def matched(reference: str, produced: set[str]) -> bool:
    want = norm_title(reference)
    if not want:
        return False
    if want in produced:
        return True
    words = set(want.split())
    for got in produced:
        if want in got or got in want:
            return True
        other = set(got.split())
        if words and len(words & other) / len(words) >= 0.8:
            return True
    return False


def bench_one(manual_id: str, model: str, size: int) -> dict:
    import pymupdf

    from app.ingest import pages as pagelib

    reference = json.loads((Path(__file__).resolve().parents[2] / "src" / "data" / "manuals" / f"{manual_id}.json").read_text(encoding="utf-8"))
    titles = [s["title"] for s in reference["sections"]]
    spans = [(s["pageStart"], s["pageEnd"]) for s in reference["sections"]]
    wanted = {p for a, b in spans for p in range(a, b + 1)}

    store = get_store()
    page_models = store.pages(manual_id)
    doc = pymupdf.open(ingest.pdf_path(manual_id))
    toc = pagelib.toc(doc)
    chaps = pagelib.chapters(toc, doc.page_count)
    cover = pagelib.cover_title(doc, "", "", 0)
    skip = pagelib.skip_pages(toc, chaps, doc.page_count)

    windows = [w for w in structure.batches(page_models, skip, size) if any(p.page in wanted for p in w)]
    prompts = [
        structure.prompt(w, cover, "", pagelib.chapter_of(chaps, w[0].page), pagelib.headings_for(toc, w[0].page, w[-1].page))
        for w in windows
    ]
    before_usd, before_calls = (BUCKETS[model].usd, BUCKETS[model].calls) if model in BUCKETS else (0.0, 0)
    started = time.time()
    results = structure.run_batches(prompts, model=model, workers=8)
    doc.close()
    produced = {norm_title(u.title) for group in results for u in group if u.title}
    hits = sum(1 for t in titles if matched(t, produced))
    bucket = BUCKETS.get(model)
    return {
        "manual": manual_id,
        "sections": len(titles),
        "found": hits,
        "coverage": round(hits / max(1, len(titles)), 4),
        "calls": len(prompts),
        "seconds": round(time.time() - started, 1),
        "usd": round((bucket.usd - before_usd) if bucket else 0.0, 4),
        "callsMade": (bucket.calls - before_calls) if bucket else 0,
    }


def cmd_bench(models: list[str], sizes: list[int]) -> int:
    install_buckets(list(LIMITS))
    patch_llm()
    quiet_store()
    jobs = [(m, s) for m in models for s in (sizes if m == BASELINE_MODEL else [sizes[0]])]
    out: dict[str, dict] = {}

    def one(job):
        model, size = job
        runs = [bench_one(ref, model, size) for ref in REFERENCES]
        found = sum(r["found"] for r in runs)
        total = sum(r["sections"] for r in runs)
        return f"{model}@{size}", {
            "model": model,
            "batch": size,
            "coverage": round(found / max(1, total), 4),
            "found": found,
            "of": total,
            "usd": round(sum(r["usd"] for r in runs), 4),
            "seconds": round(sum(r["seconds"] for r in runs), 1),
            "runs": runs,
        }

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        for key, value in pool.map(one, jobs):
            out[key] = value
            print(f"{key:<22} coverage {value['coverage']:.1%}  ({value['found']}/{value['of']})  ${value['usd']:.3f}  {value['seconds']}s")

    base_key = f"{BASELINE_MODEL}@{sizes[0]}"
    base = out.get(base_key, {}).get("coverage", 1.0) or 1.0
    enabled = [v["model"] for k, v in out.items() if v["batch"] == sizes[0] and v["coverage"] >= 0.90 * base]
    batch = sizes[0]
    for size in sizes[1:]:
        key = f"{BASELINE_MODEL}@{size}"
        if key in out and out[key]["coverage"] >= 0.95 * base:
            batch = size
    bench = {
        "measuredAt": time.time(),
        "baseline": base_key,
        "baselineCoverage": base,
        "results": out,
        "enabled": enabled,
        "batch": batch,
        "limits": {m: {"tokensPerMin": LIMITS.get(m, (200_000, 500))[0], "requestsPerMin": LIMITS.get(m, (200_000, 500))[1]} for m in enabled},
    }
    plan = load_plan() or build_plan()
    plan["models"] = bench
    write_json(PLAN_PATH, plan)
    print(f"\nenabled {enabled}  batch {batch}  -> {PLAN_PATH}")
    return 0


# ---------------------------------------------------------------- download


_disk_cache = [0.0, 0]


def pdf_bytes_local() -> int:
    now = time.time()
    if now - _disk_cache[0] < 20:
        return int(_disk_cache[1])
    folder = DATA / "pdf"
    total = sum(e.stat().st_size for e in os.scandir(folder) if e.is_file()) if folder.exists() else 0
    _disk_cache[0], _disk_cache[1] = now, total
    return total


def download(url: str, dest: Path) -> int:
    if dest.exists() and dest.stat().st_size > 4096 and dest.open("rb").read(4) == b"%PDF":
        return dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = "?"
    for attempt in range(DOWNLOAD_RETRIES):
        agent = AGENTS[min(attempt, len(AGENTS) - 1)]
        headers = {"User-Agent": agent, "Accept": "application/pdf,application/octet-stream,*/*", "Accept-Language": "en-US,en;q=0.9"}
        tmp = dest.with_suffix(f".part{attempt}")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=180.0, headers=headers) as r:
                r.raise_for_status()
                declared = int(r.headers.get("content-length") or 0)
                if declared > MAX_PDF_BYTES:
                    raise ValueError(f"too big: {declared / 1e6:.0f} MB")
                size = 0
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        size += len(chunk)
                        if size > MAX_PDF_BYTES:
                            raise ValueError("too big: over 80 MB")
                        f.write(chunk)
            if tmp.open("rb").read(4) != b"%PDF":
                raise ValueError("not a PDF")
            tmp.replace(dest)
            return dest.stat().st_size
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"[:200]
            tmp.unlink(missing_ok=True)
            if "too big" in last or "not a PDF" in last:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed: {last}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- run


WARM_FROM = 2021
WARM_TO = 2026


def warm_entries(plan: dict) -> list[dict]:
    """The bikes a judge might actually own: newest model year first, brands round-robin inside each year."""
    picked = [e for e in plan["entries"] if WARM_FROM <= e["year"] <= WARM_TO]
    out: list[dict] = []
    for year in range(WARM_TO, WARM_FROM - 1, -1):
        brands: dict[str, deque] = defaultdict(deque)
        for e in picked:
            if e["year"] == year:
                brands[e["make"]].append(e)
        while any(brands.values()):
            for make in sorted(brands, key=lambda m: -len(brands[m])):
                if brands[make]:
                    out.append(brands[make].popleft())
    return out


class Run:
    def __init__(self, plan: dict, hours: float, concurrency: int | None, limit: int | None, entries: list[dict] | None = None):
        self.plan = plan
        self.deadline = time.time() + hours * 3600
        self.started = time.time()
        self.lock = threading.Lock()
        self.report_lock = threading.Lock()
        self.links: dict[str, list] = {}
        self.links_lock = threading.Lock()
        self.downloads = threading.Semaphore(DOWNLOAD_SLOTS)
        self.stop = threading.Event()
        self.stop_reason = ""
        self.in_progress: dict[str, float] = {}
        self.done = 0
        self.failed: list[dict] = []
        self.dups = 0
        self.skipped = 0
        self.disk_paused_since = 0.0
        self.session_usd = 0.0

        models = plan.get("models", {})
        self.enabled = models.get("enabled") or [BASELINE_MODEL]
        self.batch = int(models.get("batch") or structure.BATCH)
        install_buckets(self.enabled)

        state = self.load_state()
        self.prior_usd = float(state.get("usd", 0.0))
        done_ids = set(state.get("doneIds", []))
        have = {p.stem for p in (DATA / "manuals").glob("*.json")}
        self.hashes: dict[str, str] = json.loads(HASH_PATH.read_text(encoding="utf-8")) if HASH_PATH.exists() else {}
        self.done_ids = done_ids

        scope = entries if entries is not None else plan["entries"]
        pending = [e for e in scope if e["manualId"] not in done_ids and e["manualId"] not in have]
        for e in scope:
            if e["manualId"] in have or e["manualId"] in done_ids:
                self.skipped += 1
                self.queue_links(e)
        if limit:
            pending = pending[:limit]
        self.pending = deque(pending)
        self.planned = len(scope)

        tpm = sum(LIMITS.get(m, (200_000, 500))[0] for m in self.enabled)
        rate = tpm / TOKENS_PER_MANUAL
        self.concurrency = concurrency or max(4, min(64, int(rate * AVG_MINUTES * 1.4)))
        self.workers = max(2, min(structure.WORKERS, 192 // max(1, self.concurrency)))

    # ---- state

    def load_state(self) -> dict:
        if not STATE_PATH.exists():
            return {}
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def snapshot(self) -> dict:
        elapsed = max(1e-6, (time.time() - self.started) / 60.0)
        rate = self.done / elapsed
        left = len(self.pending) + len(self.in_progress)
        with _spend_lock:
            spend = _spend
        return {
            "updatedAt": time.time(),
            "startedAt": self.started,
            "dataDir": str(DATA),
            "planned": self.planned,
            "pending": len(self.pending),
            "done": self.done,
            "skippedAlreadyHad": self.skipped,
            "duplicatePdf": self.dups,
            "failed": len(self.failed),
            "inProgress": sorted(self.in_progress),
            "manualsPerMin": round(rate, 2),
            "etaHours": round(left / rate / 60.0, 2) if rate > 0 else None,
            "usd": round(spend + self.prior_usd, 4),
            "usdThisSession": round(spend, 4),
            "usdPerManual": round(spend / self.done, 4) if self.done else None,
            "budgetUsd": BUDGET_USD,
            "batch": self.batch,
            "concurrency": self.concurrency,
            "pdfBytesLocal": pdf_bytes_local(),
            "pdfCapBytes": PDF_CAP_BYTES,
            "diskPaused": bool(self.disk_paused_since),
            "stopReason": self.stop_reason,
            "models": {
                b.model: {
                    "manuals": b.manuals,
                    "calls": b.calls,
                    "tokens": b.used,
                    "usd": round(b.usd, 4),
                    "throttles": b.throttles,
                    "scale": round(b.scale, 3),
                    "headroom": round(b.headroom(), 3),
                    "manualsPerMin": round(b.manuals / elapsed, 2),
                }
                for b in BUCKETS.values()
            },
            "failedList": self.failed[-200:],
            "doneIds": sorted(self.done_ids),
        }

    def write_state(self) -> None:
        write_json(STATE_PATH, self.snapshot())

    def report(self, row: dict) -> None:
        with self.report_lock:
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with REPORT_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---- bikes

    def queue_links(self, entry: dict, manual_id: str | None = None) -> None:
        target = manual_id or entry["manualId"]
        with self.links_lock:
            for bike_id, (make, model, year, market) in zip(entry["bikeIds"], entry["bikes"]):
                self.links[bike_id] = [target, make, model, int(year), market]

    def flush_links(self) -> int:
        with self.links_lock:
            pending, self.links = self.links, {}
        if not pending:
            return 0
        store = get_store()
        current = {b.id: b for b in store.bikes()}
        out: list[Bike] = []
        for bike_id, (manual_id, make, model, year, market) in pending.items():
            bike = current.get(bike_id)
            if bike is None:
                out.append(Bike(id=bike_id, make=make, model=model, year=year, market=market, manualId=manual_id))
            elif bike.manualId != manual_id:
                out.append(bike.model_copy(update={"manualId": manual_id}))
        if out:
            store.put_bikes(out)
        return len(out)

    # ---- guards

    def budget_left(self) -> bool:
        with _spend_lock:
            return _spend + self.prior_usd < BUDGET_USD

    def wait_for_disk(self) -> bool:
        if pdf_bytes_local() < PDF_CAP_BYTES:
            self.disk_paused_since = 0.0
            return True
        if not self.disk_paused_since:
            self.disk_paused_since = time.time()
            log.warning("local PDFs over %.1f GB: downloads paused", PDF_CAP_BYTES / 1e9)
        while not self.stop.is_set():
            if pdf_bytes_local() < PDF_CAP_BYTES:
                self.disk_paused_since = 0.0
                return True
            if time.time() - self.disk_paused_since > DISK_PAUSE_GIVEUP:
                self.halt(f"local PDFs over {PDF_CAP_BYTES / 1e9:.0f} GB for {DISK_PAUSE_GIVEUP / 60:.0f} min; waiting for the blob sync")
                return False
            self.stop.wait(20)
        return False

    def halt(self, reason: str) -> None:
        if not self.stop_reason:
            self.stop_reason = reason
            log.warning("stopping: %s", reason)
        self.stop.set()

    # ---- one manual

    def take(self) -> dict | None:
        with self.lock:
            return self.pending.popleft() if self.pending else None

    def worker(self) -> None:
        while not self.stop.is_set():
            if time.time() > self.deadline:
                self.halt("time budget reached")
                return
            if not self.budget_left():
                self.halt(f"spend cap ${BUDGET_USD:.0f} reached")
                return
            entry = self.take()
            if entry is None:
                return
            manual_id = entry["manualId"]
            with self.lock:
                self.in_progress[manual_id] = time.time()
            try:
                self.one(entry)
            except Exception as exc:
                self.fail(entry, f"{type(exc).__name__}: {exc}"[:300])
            finally:
                with self.lock:
                    self.in_progress.pop(manual_id, None)

    def fail(self, entry: dict, reason: str) -> None:
        row = {"id": entry["manualId"], "url": entry["url"], "status": "error", "reason": reason, "at": time.time()}
        with self.lock:
            self.failed.append({"id": entry["manualId"], "url": entry["url"], "reason": reason, "batch": self.batch})
        self.report(row)
        print(f"x {entry['manualId']}  {reason}", flush=True)

    def one(self, entry: dict) -> None:
        manual_id, url = entry["manualId"], entry["url"]
        started = time.time()
        _tl.manual_id = manual_id
        with _spend_lock:
            _per_manual[manual_id] = 0.0

        if not self.wait_for_disk():
            with self.lock:
                self.pending.appendleft(entry)
            return
        with self.downloads:
            size = download(url, ingest.pdf_path(manual_id))

        digest = sha256(ingest.pdf_path(manual_id))
        with self.lock:
            twin = self.hashes.get(digest)
            if twin and twin != manual_id:
                self.dups += 1
            elif not twin:
                self.hashes[digest] = manual_id
        if twin and twin != manual_id:
            ingest.pdf_path(manual_id).unlink(missing_ok=True)
            self.queue_links(entry, twin)
            self.report({"id": manual_id, "status": "duplicate", "of": twin, "url": url, "at": time.time()})
            return

        model = pick_model()
        BUCKETS[model].manuals += 1
        manual = ingest.run(
            uuid.uuid4().hex[:12],
            str(ingest.pdf_path(manual_id)),
            manual_id,
            entry["bikeIds"],
            entry["make"],
            entry["model"],
            entry["year"],
            struct_model=model,
            batch=self.batch,
            workers=self.workers,
        )
        manual = manual.model_copy(update={"source": url})
        result = curate_mod.apply(manual)
        final = result.manual
        Manual.model_validate(final.model_dump(exclude_none=True))

        store = get_store()
        specs = len(store.specs(manual_id))
        highlights = sum(len(s.highlights) for s in final.sections)
        with _spend_lock:
            usd = round(_per_manual.get(manual_id, 0.0), 4)
        row = {
            "id": manual_id,
            "url": url,
            "make": entry["make"],
            "model": entry["model"],
            "year": entry["year"],
            "market": entry["market"],
            "bikes": len(entry["bikeIds"]),
            "structModel": model,
            "batch": self.batch,
            "pages": final.pages,
            "title": final.title,
            "sections": len(final.sections),
            "sectionsDropped": len(result.dropped),
            "highlights": highlights,
            "highlightsClamped": result.clamped,
            "highlightsDiscarded": result.discarded,
            "parts": len(final.parts),
            "specs": specs,
            "pdfBytes": size,
            "usd": usd,
            "seconds": round(time.time() - started, 1),
            "at": time.time(),
        }

        suspicious = []
        if len(final.sections) < 10:
            suspicious.append(f"{len(final.sections)} sections")
        if highlights == 0:
            suspicious.append("0 highlights")
        if not (final.title or "").strip():
            suspicious.append("empty title")
        if not ingest.pdf_path(manual_id).exists():
            suspicious.append("no PDF")
        row["status"] = "suspicious" if suspicious else "done"
        if suspicious:
            row["reason"] = ", ".join(suspicious)
            with self.lock:
                self.failed.append({"id": manual_id, "url": url, "reason": row["reason"], "batch": self.batch, "retryWithBatch": 3 if self.batch != 3 else 5})
        else:
            with self.lock:
                self.done += 1
                self.done_ids.add(manual_id)
            self.queue_links(entry)
        self.report(row)
        print(
            f"{'+' if not suspicious else '?'} {manual_id}  {model} p{final.pages} sec{len(final.sections)} "
            f"hl{highlights} parts{len(final.parts)} specs{specs} ${usd:.3f} {row['seconds']}s",
            flush=True,
        )

    # ---- loop

    def keeper(self) -> None:
        last_flush = 0.0
        while not self.stop.is_set():
            self.stop.wait(STATE_EVERY)
            try:
                self.write_state()
                if time.time() - last_flush > 60:
                    self.flush_links()
                    HASH_PATH.write_text(json.dumps(self.hashes), encoding="utf-8")
                    last_flush = time.time()
            except Exception as exc:
                log.warning("state write failed: %s", exc)

    def go(self) -> int:
        print(
            f"plan {self.planned}  pending {len(self.pending)}  already had {self.skipped}  "
            f"models {self.enabled}  batch {self.batch}  concurrency {self.concurrency}  dataDir {DATA}",
            flush=True,
        )
        self.write_state()
        keeper = threading.Thread(target=self.keeper, daemon=True)
        keeper.start()
        threads = [threading.Thread(target=self.worker, name=f"mass{i}") for i in range(self.concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.stop.set()
        self.flush_links()
        HASH_PATH.write_text(json.dumps(self.hashes), encoding="utf-8")
        self.write_state()
        state = self.snapshot()
        print(
            f"\ndone {state['done']}  failed {state['failed']}  dup {state['duplicatePdf']}  "
            f"${state['usd']:.2f}  {state['manualsPerMin']} manuals/min  eta {state['etaHours']}h  {state['stopReason'] or 'plan exhausted'}",
            flush=True,
        )
        return 0


# ---------------------------------------------------------------- cli


SWEEP_MIN_SECTIONS = 10


def _unlink_bikes(store, manual_id: str, bike_ids: list[str]) -> int:
    """A removed manual must not stay on any bike: BlobStore keeps the link in its own little blob."""
    wanted = {b for b in bike_ids}
    wanted |= {b.id for b in store.bikes() if b.manualId == manual_id}
    freed = 0
    for bike_id in sorted(wanted):
        bike = store.bike(bike_id)
        if bike is None or bike.manualId != manual_id:
            continue
        store.put_bikes([bike.model_copy(update={"manualId": None})])
        # model_dump(exclude_none=True) drops the field, so neither a rewritten overlay nor a deleted one can
        # clear a manualId that lives in the base bikes.json. Take it out of the base row itself.
        blob = getattr(store, "_blob", None)
        if blob is not None and (store.bike(bike_id) or bike).manualId == manual_id:
            try:
                blob(f"links/{bike_id}.json").delete_blob()
            except Exception:
                pass

            def drop(current, _id=bike_id):
                rows = [r for r in (current or []) if isinstance(r, dict)]
                for row in rows:
                    if row.get("id") == _id:
                        row.pop("manualId", None)
                return rows

            store._cas("bikes.json", drop)
            store._lists.clear()
        freed += 1
    return freed


def _remove_manual(store, manual_id: str) -> None:
    blob = getattr(store, "_blob", None)
    if blob is None:
        for folder in ("manuals", "pages", "specs"):
            (DATA / folder / f"{manual_id}.json").unlink(missing_ok=True)
        ingest.pdf_path(manual_id).unlink(missing_ok=True)
        return
    for name in (f"manuals/{manual_id}.json", f"pages/{manual_id}.json", f"specs/{manual_id}.json"):
        try:
            blob(name).delete_blob()
        except Exception:
            pass
    try:
        blob(f"{manual_id}.pdf", store.pdf).delete_blob()
    except Exception:
        pass
    store._lists.clear()


def cmd_sweep(write: bool, only: list[str] | None = None) -> int:
    """Drop manuals the pipeline never finished (0 sections) or that turned out to be a 3-page supplement.

    Goes through the Store, so it sweeps the blob-backed store exactly the same way it sweeps DATA_DIR.
    """
    store = get_store()
    wanted = [o.lower() for o in (only or [])]
    gone = 0
    for manual in store.manuals():
        count = len(manual.sections)
        if count >= SWEEP_MIN_SECTIONS:
            continue
        if wanted and not any(w in manual.id.lower() for w in wanted):
            continue
        gone += 1
        print(f"{'-' if write else '~'} {manual.id:<44} {count} sections, {len(manual.bikeIds)} bikes")
        if write:
            freed = _unlink_bikes(store, manual.id, manual.bikeIds)
            _remove_manual(store, manual.id)
            if freed:
                print(f"    unlinked {freed} bike(s)")
    print(f"\n{gone} manuals {'removed' if write else 'would be removed'}")
    return 0


def cmd_status() -> int:
    if not STATE_PATH.exists():
        print(f"no state yet: {STATE_PATH}")
        return 1
    s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    age = time.time() - s.get("updatedAt", 0)
    print(f"updated {age:.0f}s ago   dataDir {s.get('dataDir')}")
    print(f"planned {s['planned']}  done {s['done']}  pending {s['pending']}  had {s.get('skippedAlreadyHad')}  dup {s.get('duplicatePdf')}  failed {s['failed']}")
    print(f"rate {s['manualsPerMin']} manuals/min  eta {s.get('etaHours')} h  ${s['usd']:.2f} of ${s['budgetUsd']:.0f}  ${s.get('usdPerManual')} per manual")
    print(f"pdfs local {s.get('pdfBytesLocal', 0) / 1e9:.1f} GB of {s.get('pdfCapBytes', 0) / 1e9:.0f} GB  diskPaused {s.get('diskPaused')}  batch {s.get('batch')}  concurrency {s.get('concurrency')}")
    for model, m in sorted(s.get("models", {}).items()):
        print(f"  {model:<14} {m['manuals']:>5} manuals  {m['manualsPerMin']:>5}/min  {m['calls']:>6} calls  {m['tokens'] / 1e6:>6.1f}M tok  ${m['usd']:>7.2f}  429s {m['throttles']}  headroom {m['headroom']}")
    if s.get("stopReason"):
        print(f"stopped: {s['stopReason']}")
    for f in s.get("failedList", [])[-10:]:
        print(f"  ! {f['id']}: {f['reason']}")
    print(f"in progress: {', '.join(s.get('inProgress', [])[:8])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="tools.mass_ingest")
    p.add_argument("--plan", action="store_true")
    p.add_argument("--bench", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--warm", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--write", action="store_true")
    p.add_argument("--only", action="append", default=[])
    p.add_argument("--budget", type=float, default=None)
    p.add_argument("--hours", type=float, default=12.0)
    p.add_argument("--concurrency", type=int, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--models", default=",".join(LIMITS))
    p.add_argument("--sizes", default="3,5")
    args = p.parse_args(argv)

    if args.status:
        return cmd_status()
    if args.sweep:
        return cmd_sweep(args.write, args.only)
    if args.bench:
        return cmd_bench([m.strip() for m in args.models.split(",") if m.strip()], [int(s) for s in args.sizes.split(",")])
    if args.plan:
        plan = build_plan()
        print(f"{plan['uniqueUrls']} unique PDFs from {plan['registryRows']} rows, {plan['bikesCovered']} bikes")
        for make, n in plan["byBrand"].items():
            print(f"  {make:<16} {n}")
        print(f"-> {PLAN_PATH}")
        return 0
    if args.run or args.warm:
        global BUDGET_USD
        if args.budget:
            BUDGET_USD = args.budget
        plan = load_plan() or build_plan()
        patch_llm()
        inherit_manual_id()
        quiet_store()
        entries = warm_entries(plan) if args.warm else None
        if entries is not None:
            print(f"warm cache: {len(entries)} manuals, model years {WARM_FROM}-{WARM_TO}, budget ${BUDGET_USD:.0f}")
        return Run(plan, args.hours, args.concurrency, args.limit, entries).go()
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())

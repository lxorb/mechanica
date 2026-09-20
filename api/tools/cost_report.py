"""What the LLM stack actually costs, measured from the cost log. Owner: Token Company pitch agent.

    api/.venv/Scripts/python tools/cost_report.py [--log data/costs.jsonl] [--live] [--md OUT.md] [--json OUT.json]

Every figure printed here comes from a file on disk or from the live API - nothing is estimated unless the
row says `est`. Three sources:

  data/costs.jsonl      one JSON line per OpenAI call: route, model, input/cached/output tokens, USD
                        (written by app/llm.py::log, so a call that is not in here was never billed)
  data/mass_report.jsonl one line per ingested manual: pages, seconds, USD
  data/manuals/*.json   the catalog, for the page counts the naive baseline is computed over

The hard part is that the cost log records CALLS, not operations, and one answer is several calls. An ask is
a router call plus (sometimes) a picker call; a chat answer is a router call plus a streamed answer call. So
`operations()` stitches calls back into operations with a LIFO walk over the log in timestamp order, and then
prints its own consistency check so a bad stitch is visible rather than silent.

The savings ladder is a counterfactual: each rung re-prices the SAME measured token counts under the previous
rung's rules, so every step is arithmetic over numbers that were actually logged, not a guess at what a
different design would have used. The one exception is the compression rung, which uses the token counts
GET /cost/ttc and api/eval/chat-report.md record as removed before the prompt was ever billed.
"""

import argparse
import json
import statistics
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import PRICES, TOKENS_PER_PAGE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIVE = "https://mechanica.emilvinu.ch/api"

# gpt-6-astra, the model a naive "paste the manual in" implementation reaches for.
FLAGSHIP = "gpt-6-astra"
# OpenAI bills input above this many tokens at 2x (developers.openai.com/api/docs/pricing, 2026-09-19).
LONG_CONTEXT = 272_000
LONG_CONTEXT_MULT = 2.0
# A naive implementation still pays for its answer; ~100 output tokens is what our chat answers run to.
NAIVE_OUTPUT = 100
# Stitching window: a picker follows its router within ~2 s, a chat answer within ~9 s (chat-report.md p95).
STITCH_WINDOW = 60.0
# The mechanic in the story: 40 questions a day, every working day.
QUESTIONS_PER_DAY = 40
DAYS_PER_MONTH = 30

# Measured elsewhere, quoted here so the ladder is complete. Each carries its source.
EVAL_ASKS = 150                 # api/eval/report.md
EVAL_ASK_CALLS = 172            # api/eval/report.md - so 22 of 150 asks paid for a picker
EVAL_CHAT_QUESTIONS = 25        # api/eval/chat-report.md
EVAL_TTC_IN = 46_501            # api/eval/chat-report.md
EVAL_TTC_OUT = 31_977           # api/eval/chat-report.md
EVAL_CHAT_USD = 0.00488         # api/eval/chat-report.md, per answer
EVAL_ASK_USD = 0.00038          # api/eval/report.md, per ask over the 150-query mix
# api/eval/report-baseline.md - the SAME 150 queries before the router rewrite, the spec path and the
# picker gate. The only controlled A/B in the repo: cost and accuracy both moved, in the same direction.
BASELINE = {"usd": 0.00207, "calls": 259, "p95": 4.99, "oos": 55.0}
CURRENT = {"usd": 0.00038, "calls": 172, "p95": 3.33, "oos": 100.0}
STRIP_PCT = (2.8, 5.7)          # api/docs/CHAT-RESEARCH.md - referral boilerplate as % of page text


def _rows(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _usd(model: str, fresh: int, cached: int, out: int) -> float:
    p_in, p_cached, p_out = PRICES.get(model, (0.0, 0.0, 0.0))
    return (fresh * p_in + cached * p_cached + out * p_out) / 1_000_000


def whole_manual_usd(pages: int, model: str = FLAGSHIP, cached: bool = False) -> float:
    """What one question costs when the whole manual is the prompt. `cached` = the best case for that
    design, where the manual sits in the provider's prompt cache and only the question is fresh."""
    tokens = pages * TOKENS_PER_PAGE
    p_in, p_cached, p_out = PRICES[model]
    if tokens > LONG_CONTEXT:
        p_in *= LONG_CONTEXT_MULT
        p_cached *= LONG_CONTEXT_MULT
    price = p_cached if cached else p_in
    return (tokens * price + NAIVE_OUTPUT * p_out) / 1_000_000


# --------------------------------------------------------------------------- per route


def per_route(rows: list[dict]) -> list[dict]:
    agg: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "ti": 0, "tc": 0, "to": 0, "usd": 0.0})
    for e in rows:
        a = agg[(e["route"], e["model"])]
        a["n"] += 1
        a["ti"] += e.get("inputTokens", 0)
        a["tc"] += e.get("cachedTokens", 0)
        a["to"] += e.get("outputTokens", 0)
        a["usd"] += e.get("usd", 0.0)
    out = []
    for (route, model), a in sorted(agg.items()):
        n = a["n"]
        out.append(
            {
                "route": route,
                "model": model,
                "calls": n,
                "meanIn": a["ti"] / n,
                "cachedPct": 100.0 * a["tc"] / a["ti"] if a["ti"] else 0.0,
                "meanOut": a["to"] / n,
                "usdPerCall": a["usd"] / n,
                "usd": a["usd"],
            }
        )
    return out


# --------------------------------------------------------------------------- operations


def operations(rows: list[dict]) -> dict:
    """Stitch calls back into operations.

    app/ask.py logs `ask.router` first and `ask.picker` after it; app/chat.py logs `ask.router` (through
    ask._route) and then `chat.answer`. So a router event is open until something closes it: a picker makes
    it an ask-with-picker, a chat answer makes it a chat. A router nothing closes is an ask that never paid
    for a picker - the deterministic spec path, a decisive BM25 hit, or an out-of-scope question.
    """
    events = sorted(rows, key=lambda e: e["ts"])
    open_routers: list[dict] = []
    ops: list[dict] = []
    orphans = {"picker": 0, "chat": 0}

    def close(kind: str, event: dict) -> bool:
        while open_routers:
            router = open_routers.pop()
            if event["ts"] - router["ts"] > STITCH_WINDOW:
                ops.append({"kind": "ask", "picker": False, "calls": [router]})
                continue
            ops.append({"kind": kind, "picker": kind == "ask", "calls": [router, event]})
            return True
        return False

    for e in events:
        route = e["route"]
        if route == "ask.router":
            open_routers.append(e)
        elif route == "ask.picker":
            if not close("ask", e):
                orphans["picker"] += 1
                ops.append({"kind": "ask", "picker": True, "calls": [e]})
        elif route == "chat.answer":
            if not close("chat", e):
                orphans["chat"] += 1
                ops.append({"kind": "chat", "picker": False, "calls": [e]})
        elif route.startswith("identify."):
            ops.append({"kind": f"identify.{route.split('.')[1]}:{e['model']}", "picker": False, "calls": [e]})
    for router in open_routers:
        ops.append({"kind": "ask", "picker": False, "calls": [router]})

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for op in ops:
        key = op["kind"]
        if key == "ask":
            key = "ask (router + picker)" if op["picker"] else "ask (router only)"
        by_kind[key].append(op)

    summary = []
    for kind, group in sorted(by_kind.items()):
        usds = [sum(c.get("usd", 0.0) for c in op["calls"]) for op in group]
        tin = [sum(c.get("inputTokens", 0) for c in op["calls"]) for op in group]
        tcached = [sum(c.get("cachedTokens", 0) for c in op["calls"]) for op in group]
        tout = [sum(c.get("outputTokens", 0) for c in op["calls"]) for op in group]
        summary.append(
            {
                "operation": kind,
                "n": len(group),
                "meanIn": statistics.mean(tin),
                "cachedPct": 100.0 * sum(tcached) / max(1, sum(tin)),
                "meanOut": statistics.mean(tout),
                "meanUsd": statistics.mean(usds),
                "medianUsd": statistics.median(usds),
                "usd": sum(usds),
            }
        )

    asks = [op for op in ops if op["kind"] == "ask"]
    with_picker = sum(1 for op in asks if op["picker"])
    return {
        "byOperation": summary,
        "asks": len(asks),
        "asksWithPicker": with_picker,
        "asksZeroPicker": len(asks) - with_picker,
        "zeroPickerPct": 100.0 * (len(asks) - with_picker) / max(1, len(asks)),
        "orphans": orphans,
        "askMeanUsd": statistics.mean([sum(c.get("usd", 0.0) for c in op["calls"]) for op in asks]) if asks else 0.0,
    }


# --------------------------------------------------------------------------- counterfactuals


def reprice(rows: list[dict], routes: tuple[str, ...], model: str, ignore_cache: bool = True) -> float:
    """Total USD if these routes had run on `model`, over the token counts we actually logged."""
    total = 0.0
    for e in rows:
        if e["route"] not in routes:
            continue
        fresh = e.get("inputTokens", 0)
        cached = 0 if ignore_cache else e.get("cachedTokens", 0)
        total += _usd(model, fresh - cached, cached, e.get("outputTokens", 0))
    return total


def caching(rows: list[dict]) -> list[dict]:
    """What the provider's prompt cache is worth, per route: cached tokens x (fresh price - cached price)."""
    agg: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "ti": 0, "tc": 0, "usd": 0.0})
    for e in rows:
        a = agg[(e["route"], e["model"])]
        a["n"] += 1
        a["ti"] += e.get("inputTokens", 0)
        a["tc"] += e.get("cachedTokens", 0)
        a["usd"] += e.get("usd", 0.0)
    out = []
    for (route, model), a in sorted(agg.items()):
        p_in, p_cached, _ = PRICES.get(model, (0.0, 0.0, 0.0))
        saved = a["tc"] * (p_in - p_cached) / 1_000_000
        out.append(
            {
                "route": route,
                "model": model,
                "calls": a["n"],
                "hitPct": 100.0 * a["tc"] / a["ti"] if a["ti"] else 0.0,
                "usdPaid": a["usd"],
                "usdSaved": saved,
                "usdWithout": a["usd"] + saved,
            }
        )
    return out


# --------------------------------------------------------------------------- ingest


def ingest(path: Path) -> dict:
    rows = [r for r in _rows(path) if r.get("status") == "done" and r.get("usd")]
    usd = [r["usd"] for r in rows]
    pages = [r["pages"] for r in rows if r.get("pages")]
    return {
        "manuals": len(rows),
        "meanUsd": statistics.mean(usd),
        "medianUsd": statistics.median(usd),
        "maxUsd": max(usd),
        "totalUsd": sum(usd),
        "meanPages": statistics.mean(pages),
        "medianPages": statistics.median(pages),
        "usdPerPage": sum(usd) / sum(pages),
    }


def catalog(dirpath: Path) -> dict:
    pages = []
    for p in dirpath.glob("*.json"):
        try:
            n = json.loads(p.read_text(encoding="utf-8", errors="replace")).get("pages")
        except ValueError:
            continue
        if n:
            pages.append(n)
    pages.sort()
    return {
        "manuals": len(pages),
        "mean": statistics.mean(pages),
        "median": statistics.median(pages),
        "max": max(pages),
        "min": min(pages),
    }


# --------------------------------------------------------------------------- live


def live(path: str) -> dict | None:
    # Cloudflare 403s the default `Python-urllib/3.x` agent in front of this origin, so send a real one.
    request = urllib.request.Request(f"{LIVE}{path}", headers={"User-Agent": "mechanica-cost-report/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError):
        return None


# --------------------------------------------------------------------------- render


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def report(args) -> tuple[str, dict]:
    rows = _rows(Path(args.log))
    cat = catalog(Path(args.manuals))
    ing = ingest(Path(args.ingest))
    routes = per_route(rows)
    ops = operations(rows)
    cache_rows = caching(rows)
    live_cost = live("/cost") if args.live else None
    live_ttc = live("/cost/ttc") if args.live else None

    ask_usd = ops["askMeanUsd"]
    chat_row = next((o for o in ops["byOperation"] if o["operation"] == "chat"), None)
    chat_usd = chat_row["meanUsd"] if chat_row else EVAL_CHAT_USD

    L = [f"# Measured LLM cost — Mechanica ({len(rows)} logged calls)", ""]
    L.append(f"Source: `{args.log}` · `{args.ingest}` · `{args.manuals}`"
             + (" · live `/api/cost` + `/api/cost/ttc`" if live_cost else ""))
    L.append("")

    # ---- baselines
    L += ["## 1. Baselines — the whole manual in the prompt, once per question", ""]
    cases = [
        ("KTM 390 Duke 2023 (demo)", 128),
        ("median manual in our catalog", int(cat["median"])),
        ("BMW R 12 G/S 2026 (demo)", 270),
        ("largest manual in our catalog", int(cat["max"])),
        ("the founder's 500-page workshop manual", 500),
    ]
    L += _table(
        ["manual", "pages", "prompt tokens", f"naive: {FLAGSHIP}", "+ prompt cache", "reasonable: gpt-5.6-luna"],
        [
            [
                name,
                f"{pages}",
                f"{pages * TOKENS_PER_PAGE:,}" + (" (2x)" if pages * TOKENS_PER_PAGE > LONG_CONTEXT else ""),
                f"${whole_manual_usd(pages):.3f}",
                f"${whole_manual_usd(pages, cached=True):.3f}",
                f"${whole_manual_usd(pages, 'gpt-5.6-luna'):.4f}",
            ]
            for name, pages in cases
        ],
    )
    L += [
        "",
        f"`{TOKENS_PER_PAGE}` tokens/page and the >{LONG_CONTEXT:,}-token 2x rule are `app/llm.py`. "
        f"Output is {NAIVE_OUTPUT} tokens at the model's output price. The cache column is the best case "
        "for the naive design, not the normal one: it needs the same manual re-asked inside the cache TTL.",
        "",
    ]
    if live_cost:
        L.append(f"Live `/api/cost` reports `naivePerAsk` **${live_cost['naivePerAsk']:.2f}** for the biggest "
                 f"manual in the deployed catalog, over {live_cost['count']} calls and ${live_cost['total']:.2f} spent.")
        L.append("")

    # ---- ours
    L += ["## 2. Ours — per operation, stitched from the call log", ""]
    L += _table(
        ["operation", "n", "mean tokens in", "cached", "mean out", "mean $", "median $", "total $"],
        [
            [
                o["operation"],
                f"{o['n']}",
                f"{o['meanIn']:,.0f}",
                f"{o['cachedPct']:.1f}%",
                f"{o['meanOut']:,.0f}",
                f"${o['meanUsd']:.6f}",
                f"${o['medianUsd']:.6f}",
                f"${o['usd']:.4f}",
            ]
            for o in ops["byOperation"]
        ],
    )
    L += [
        "",
        f"Stitch check: {ops['asks']} asks, {ops['asksWithPicker']} paid for a picker, "
        f"{ops['asksZeroPicker']} did not (**{ops['zeroPickerPct']:.1f}% of asks make zero picker calls**). "
        f"Unstitched calls: {ops['orphans']['picker']} picker, {ops['orphans']['chat']} chat.",
        "",
        f"This log is every call ever made, development included, so its ask mix is picker-heavier than a "
        f"rider's. The controlled 150-query eval (`api/eval/report.md`) is the honest per-ask number: "
        f"**${EVAL_ASK_USD:.5f} per ask**, 1.15 LLM calls per ask. Both are carried below.",
        "",
        f"Ingest, from `{Path(args.ingest).name}`: {ing['manuals']} manuals, mean **${ing['meanUsd']:.4f}** "
        f"(median ${ing['medianUsd']:.4f}, max ${ing['maxUsd']:.4f}) for a mean of {ing['meanPages']:.0f} pages "
        f"= ${ing['usdPerPage'] * 1000:.3f} per 1,000 pages. Paid once per manual, never per question.",
        "",
    ]
    L += ["### Every call, by route and model", ""]
    L += _table(
        ["route", "model", "calls", "mean in", "cached", "mean out", "$/call", "$ total"],
        [
            [
                r["route"],
                r["model"],
                f"{r['calls']:,}",
                f"{r['meanIn']:,.0f}",
                f"{r['cachedPct']:.1f}%",
                f"{r['meanOut']:,.0f}",
                f"${r['usdPerCall']:.6f}",
                f"${r['usd']:.4f}",
            ]
            for r in routes
        ],
    )
    L.append("")

    # ---- ladder
    naive_pages = int(cat["median"])
    r0 = whole_manual_usd(naive_pages)
    r1 = whole_manual_usd(naive_pages, cached=True)
    # Rung 2: our retrieved prompt, still on the flagship, still uncached.
    flagship_chat = reprice(rows, ("chat.answer",), FLAGSHIP)
    flagship_ask = reprice(rows, ("ask.router", "ask.picker"), FLAGSHIP)
    n_chat = sum(1 for e in rows if e["route"] == "chat.answer")
    r2_chat = flagship_chat / max(1, n_chat)
    r2_ask = flagship_ask / max(1, ops["asks"])
    # Rung 3: our models, cache ignored.
    tier_chat = reprice(rows, ("chat.answer",), "gpt-5.6-terra") / max(1, n_chat)
    tier_ask = (
        reprice(rows, ("ask.router",), "gpt-5.6-luna") + reprice(rows, ("ask.picker",), "gpt-5.6-terra")
    ) / max(1, ops["asks"])
    # Rung 4: + the prompt cache actually observed.
    cache_chat = chat_usd
    cache_ask = ask_usd

    ladder = [
        ("0 · naive: whole manual, flagship, every question",
         f"${r0:.4f}", f"${r0:.4f}", "1x",
         f"{naive_pages}-page manual x {TOKENS_PER_PAGE} tok in {FLAGSHIP}"),
        ("1 · + prompt-cache the manual (best case for that design)",
         f"${r1:.4f}", f"${r1:.4f}", f"{r0 / r1:.0f}x",
         "cached-input price, app/llm.py PRICES"),
        ("2 · page retrieval instead of whole manual (still flagship)",
         f"${r2_ask:.5f}", f"${r2_chat:.5f}",
         f"{r0 / r2_chat:.0f}x (chat)",
         f"logged token counts re-priced at {FLAGSHIP}"),
        ("3 · + model tiering (luna router / terra picker + chat)",
         f"${tier_ask:.6f}", f"${tier_chat:.6f}",
         f"{r2_chat / tier_chat:.1f}x vs rung 2",
         "same tokens, our models, cache ignored"),
        ("4 · + prompt caching + spec path + picker gating + compression",
         f"${cache_ask:.6f}", f"${cache_chat:.6f}",
         f"{tier_chat / cache_chat:.1f}x vs rung 3",
         "what the log actually billed"),
        ("5 · + answer cache on a repeated question",
         "$0.000000", "$0.000000", "∞",
         "ask._cache / ttc._cache, `usd` forced to 0"),
    ]
    L += ["## 3. The savings ladder", ""]
    L += _table(
        ["rung", "$ / ask", "$ / chat answer", "step", "how it is computed"],
        [list(r) for r in ladder],
    )
    L.append("")
    L += ["### Rung detail, each measured separately", ""]

    L += [
        "**The one controlled A/B** — the same 150 rider queries, before and after the router rewrite, the "
        "deterministic spec path and the picker gate (`api/eval/report-baseline.md` → `api/eval/report.md`):",
        "",
    ]
    L += _table(
        ["", "before", "after", "change"],
        [
            ["$ per ask", f"${BASELINE['usd']:.5f}", f"${CURRENT['usd']:.5f}",
             f"**{BASELINE['usd'] / CURRENT['usd']:.1f}x cheaper**"],
            ["LLM calls per ask", f"{BASELINE['calls'] / EVAL_ASKS:.2f}", f"{CURRENT['calls'] / EVAL_ASKS:.2f}",
             f"−{100.0 * (1 - CURRENT['calls'] / BASELINE['calls']):.0f}%"],
            ["p95 latency", f"{BASELINE['p95']:.2f} s", f"{CURRENT['p95']:.2f} s",
             f"−{100.0 * (1 - CURRENT['p95'] / BASELINE['p95']):.0f}%"],
            ["out-of-scope answered correctly", f"{BASELINE['oos']:.0f}%", f"{CURRENT['oos']:.0f}%",
             "**+45 pts**"],
            ["in-scope top-1", "100%", "100%", "unchanged"],
        ],
    )
    L += ["", "Cheaper and more accurate on the same queries: the cheapest call is the one not made.", ""]

    # caching detail
    L += ["**Prompt caching** — cached tokens x (fresh price − cached price), per route:", ""]
    L += _table(
        ["route", "model", "calls", "cache hit rate", "$ paid", "$ saved", "$ without cache"],
        [
            [
                c["route"],
                c["model"],
                f"{c['calls']:,}",
                f"{c['hitPct']:.1f}%",
                f"${c['usdPaid']:.4f}",
                f"${c['usdSaved']:.4f}",
                f"${c['usdWithout']:.4f}",
            ]
            for c in cache_rows
            if c["hitPct"] > 0
        ],
    )
    L.append("")

    # tiering detail: same route on two models
    tier_pairs = defaultdict(dict)
    for r in routes:
        tier_pairs[r["route"]][r["model"]] = r
    L += ["**Model tiering** — two routes were run on both a flagship and a cheap model against the same job:", ""]
    trows = []
    for route, models in sorted(tier_pairs.items()):
        if len(models) < 2:
            continue
        big = max(models.values(), key=lambda r: r["usdPerCall"])
        small = min(models.values(), key=lambda r: r["usdPerCall"])
        trows.append(
            [
                route,
                f"{big['model']} ${big['usdPerCall']:.6f}",
                f"{small['model']} ${small['usdPerCall']:.6f}",
                f"{big['usdPerCall'] / small['usdPerCall']:.0f}x",
            ]
        )
    L += _table(["route", "flagship", "tier we ship", "factor"], trows)
    L.append("")

    # compression detail
    saved = EVAL_TTC_IN - EVAL_TTC_OUT
    per_answer = saved / EVAL_CHAT_QUESTIONS
    terra_in = PRICES["gpt-5.6-terra"][0]
    comp_usd = per_answer * terra_in / 1_000_000
    L += [
        "**Referral stripping + bear-2 compression** — tokens removed before the prompt was ever billed:",
        "",
        f"- `api/eval/chat-report.md`: {EVAL_TTC_IN:,} tokens in → {EVAL_TTC_OUT:,} out over "
        f"{EVAL_CHAT_QUESTIONS} answers = **{100.0 * saved / EVAL_TTC_IN:.1f}% saved**, "
        f"{per_answer:.0f} tokens per answer.",
        f"- At gpt-5.6-terra fresh input (${terra_in:.2f}/M) that is **${comp_usd:.5f} per answer**, "
        f"**{100.0 * comp_usd / (chat_usd + comp_usd):.1f}%** of what a chat answer would otherwise cost "
        f"(${chat_usd + comp_usd:.5f} → ${chat_usd:.5f}).",
        f"- `chat._strip_referrals` removes the dealer-referral boilerplate first: "
        f"{STRIP_PCT[0]}% of the KTM page text, {STRIP_PCT[1]}% of the BMW "
        "(`api/docs/CHAT-RESEARCH.md`), with 368/368 and 256/256 printed figures intact.",
        "",
    ]
    if live_ttc:
        t = live_ttc["total"]
        if t["tokensIn"]:
            L.append(f"- Live `/api/cost/ttc` right now: {t['tokensIn']:,} in → {t['tokensOut']:,} out, "
                     f"**{t['savedPct']}% saved**, {t['calls']} calls, {t['cached']} served from the local "
                     f"compression cache, {t['errors']} failures (a failure returns the uncompressed text).")
            for route, b in sorted(live_ttc["byRoute"].items()):
                L.append(f"  - `{route}`: {b['tokensIn']:,} → {b['tokensOut']:,}, {b['savedPct']}% saved")
        else:
            # Not a failure: the counter is an in-memory dict per replica (app/ttc.py), so a restart or a
            # different replica answers with zeroes until the next chat. Ask one question and re-read it.
            L.append(f"- Live `/api/cost/ttc` is reachable and `enabled: {live_ttc['enabled']}`, but this "
                     "replica's counters are at zero - they are in-memory per replica and reset on restart. "
                     "Ask one chat question against production and read it again.")
        L.append("")

    L += [
        "**Deterministic spec path + picker gating** — the two levers that remove an LLM call entirely:",
        "",
        f"- `api/eval/report.md`: {EVAL_ASK_CALLS} LLM calls for {EVAL_ASKS} asks = "
        f"{EVAL_ASK_CALLS / EVAL_ASKS:.2f} calls per ask, so "
        f"**{100.0 * (EVAL_ASKS - (EVAL_ASK_CALLS - EVAL_ASKS)) / EVAL_ASKS:.1f}% of asks never pay for a picker**.",
        f"- Over the whole log: {ops['asksZeroPicker']} of {ops['asks']} asks "
        f"(**{ops['zeroPickerPct']:.1f}%**) are router-only.",
        "- A spec question (`how much oil does it take`) is answered from parsed spec rows plus BM25: "
        "zero LLM calls past the router (`app/ask.py::_by_spec`).",
        "- A procedure question whose second BM25 hit is below `PICK_MARGIN` skips the picker too "
        "(`app/ask.py`, `decisive`).",
        "- Retrieval itself is free: BM25 in process, `app/search/local.py`, no embeddings, no vector DB.",
        "",
        "**On-demand ingest** — the cost that is paid once instead of per question:",
        "",
        f"- ${ing['meanUsd']:.4f} mean per manual over {ing['manuals']} real ingests, paid once. "
        f"That is **{100.0 * ing['meanUsd'] / r0:.0f}% of ONE naive question** "
        f"(${r0:.2f}), and it then answers every question about that bike forever.",
        f"- Break-even against the naive stack: **{ing['meanUsd'] / (r0 - chat_usd):.2f} questions**. "
        f"Against the reasonable luna baseline (${whole_manual_usd(naive_pages, 'gpt-5.6-luna'):.4f}): "
        f"**{ing['meanUsd'] / (whole_manual_usd(naive_pages, 'gpt-5.6-luna') - chat_usd):.1f} questions**.",
        "",
    ]

    # ---- monthly bill
    per_month = QUESTIONS_PER_DAY * DAYS_PER_MONTH
    big = 500  # the founder's own workshop manual, the one behind the "$4 a question" story
    mix = [
        ("naive, whole manual, flagship", r0, whole_manual_usd(big)),
        ("naive + prompt cache (best case for that design)", r1, whole_manual_usd(big, cached=True)),
        ("reasonable, whole manual in gpt-5.6-luna", whole_manual_usd(naive_pages, "gpt-5.6-luna"),
         whole_manual_usd(big, "gpt-5.6-luna")),
        ("ours, every question a chat answer (worst case)", chat_usd, chat_usd),
        ("ours, every question an ask, whole-log mix", ask_usd, ask_usd),
        ("ours, every question an ask, 150-query eval mix", EVAL_ASK_USD, EVAL_ASK_USD),
    ]
    L += [f"## 4. The mechanic's monthly bill — {QUESTIONS_PER_DAY} questions/day x {DAYS_PER_MONTH} days "
          f"= {per_month:,} questions", ""]
    L += _table(
        ["stack", f"$/q ({naive_pages} p)", f"$/mo ({naive_pages} p)",
         f"$/q ({big} p)", f"$/mo ({big} p)", "questions per $1 (500 p)"],
        [
            [name, f"${med:.6f}", f"${med * per_month:,.2f}", f"${bg:.6f}", f"${bg * per_month:,.2f}",
             (f"{1.0 / bg:,.0f}" if 1.0 / bg >= 1 else f"{1.0 / bg:.2f}") if bg else "-"]
            for name, med, bg in mix
        ],
    )
    L += [
        "",
        f"Left pair: the median manual in our catalog ({naive_pages} pages). Right pair: a {big}-page "
        "workshop manual, the size behind the founder's \"one question cost about $4\". Our side does not "
        "move with page count, because the prompt never holds the manual - only the pages BM25 returned.",
        "",
        f"Plus ingest: one manual per bike that comes through the door, ${ing['meanUsd']:.4f} each, "
        "forever, not per question.",
        "",
    ]

    # ---- scale
    shops = 1000
    L += [f"## 5. At {shops:,} mechanics", ""]
    L += _table(
        ["stack", "questions / month", "$ / month", "$ / year"],
        [
            [name, f"{shops * per_month:,}", f"${u * shops * per_month:,.0f}",
             f"${u * shops * per_month * 12:,.0f}"]
            for name, u in (
                ("naive, whole manual, flagship (median manual)", r0),
                ("ours, worst case: every question a chat answer", chat_usd),
                ("ours, the default path: an ask", EVAL_ASK_USD),
            )
        ],
    )
    L += [
        "",
        f"Plus the catalog: {cat['manuals']} manuals already ingested at ${ing['meanUsd']:.4f} each "
        f"= ${cat['manuals'] * ing['meanUsd']:,.0f} spent once, shared by every shop. Ingest does not "
        "scale with mechanics, it scales with distinct manuals, and there are only so many motorcycles.",
        "",
    ]

    data = {
        "log": args.log,
        "calls": len(rows),
        "catalog": cat,
        "ingest": ing,
        "byRoute": routes,
        "operations": ops,
        "caching": cache_rows,
        "baselines": {name: whole_manual_usd(p) for name, p in cases},
        "askUsd": ask_usd,
        "askUsdEval": EVAL_ASK_USD,
        "chatUsd": chat_usd,
        "ladder": ladder,
        "monthly": {name: {"median": med * per_month, "big": bg * per_month} for name, med, bg in mix},
        "live": {"cost": live_cost, "ttc": live_ttc},
    }
    return "\n".join(L), data


def main() -> int:
    ap = argparse.ArgumentParser(prog="tools.cost_report")
    ap.add_argument("--log", default=str(ROOT / "data" / "costs.jsonl"))
    ap.add_argument("--ingest", default=str(ROOT / "data" / "mass_report.jsonl"))
    ap.add_argument("--manuals", default=str(ROOT / "data" / "manuals"))
    ap.add_argument("--live", action="store_true", help="also read GET /cost and /cost/ttc from production")
    ap.add_argument("--md", help="write the report to this file")
    ap.add_argument("--json", dest="json_out", help="write the raw numbers to this file")
    args = ap.parse_args()

    try:  # the report is UTF-8; a cp1252 console would otherwise kill it on the first arrow
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    text, data = report(args)
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(text + "\n", encoding="utf-8")
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

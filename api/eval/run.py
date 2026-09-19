"""Offline eval of the ask pipeline. Run from api/:  .venv/Scripts/python eval/run.py

Every labelled query in eval/queries.json goes through ask.answer. Prints top-1 / top-4 per category,
the out-of-scope false-positive rate, latency, cost per ask from the cost-log delta, and the grounding
check on spec answers. Writes eval/report.md.
"""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import ask  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import AskResponse  # noqa: E402
from app.store import get_store  # noqa: E402

HERE = Path(__file__).resolve().parent
TARGETS = {"top1": 0.95, "oos": 0.90, "p95": 4.0, "usd": 0.002}
PROSE_FIELDS = {"matches", "intent", "usd"}


def load() -> tuple[dict[str, str], list[dict]]:
    data = json.loads((HERE / "queries.json").read_text(encoding="utf-8"))
    return data["manuals"], data["queries"]


def page_text(manual_id: str) -> dict[int, str]:
    return {p.page: p.text for p in get_store().pages(manual_id)}


def verbatim(quote: str, text: str) -> bool:
    return quote in text or " ".join(quote.split()) in " ".join(text.split())


class Grounding:
    """A spec section handed back must print its spec quote verbatim on its own page.

    violations: a returned section carries a spec row whose quote is not on the page it claims. Gate.
    unsourced:  a spec answer led with a section the ingest never parsed a spec row out of. Reported only:
                the printed value can still be on the page, it just was not extracted.
    """

    def __init__(self, manual_ids: list[str]):
        self.pages = {m: page_text(m) for m in manual_ids}
        self.specs: dict[str, dict[str, list]] = {}
        for m in manual_ids:
            by_section: dict[str, list] = {}
            for spec in get_store().specs(m):
                by_section.setdefault(spec.sectionId, []).append(spec)
            self.specs[m] = by_section
        self.violations: list[str] = []
        self.unsourced: list[str] = []

    def check(self, case: dict, manual_id: str, section_ids: list[str]) -> None:
        for section_id in section_ids:
            for row in self.specs[manual_id].get(section_id, []):
                if verbatim(row.quote, self.pages[manual_id].get(row.page, "")):
                    continue
                note = f"{manual_id}/{section_id}: {row.name[:40]!r} quote {row.quote[:30]!r} not on p. {row.page}"
                if note not in self.violations:
                    self.violations.append(note)
        if section_ids and not self.specs[manual_id].get(section_ids[0]):
            self.unsourced.append(f"{case['id']} {case['query']!r} -> {section_ids[0]} (no spec row parsed)")


def run_one(case: dict, manual_id: str) -> dict:
    started = time.perf_counter()
    try:
        response = ask.answer(manual_id, case["query"])
        error = ""
    except Exception as exc:  # a live demo must never 500
        response = AskResponse(matches=[], intent="error")
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    got = [m.section.id for m in response.matches]
    expect = case["expect"]
    oos = not expect
    return {
        **case,
        "manualId": manual_id,
        "got": got,
        "intent": response.intent,
        "usd": response.usd,
        "seconds": elapsed,
        "error": error,
        "top1": bool(got) and got[0] in expect,
        "top4": any(g in expect for g in got[:4]),
        "empty": not got,
        "oos": oos,
        "leak": sorted(response.model_dump().keys()) != sorted(PROSE_FIELDS),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


def summarise(rows: list[dict]) -> dict:
    in_scope = [r for r in rows if not r["oos"]]
    oos = [r for r in rows if r["oos"]]
    latencies = [r["seconds"] for r in rows]
    return {
        "n": len(rows),
        "inScope": len(in_scope),
        "top1": sum(r["top1"] for r in in_scope) / len(in_scope) if in_scope else 0.0,
        "top4": sum(r["top4"] for r in in_scope) / len(in_scope) if in_scope else 0.0,
        "oosEmpty": sum(r["empty"] for r in oos) / len(oos) if oos else 0.0,
        "oosFalsePositive": sum(not r["empty"] for r in oos) / len(oos) if oos else 0.0,
        "inScopeEmpty": sum(r["empty"] for r in in_scope) / len(in_scope) if in_scope else 0.0,
        "meanSeconds": statistics.fmean(latencies) if latencies else 0.0,
        "p95Seconds": percentile(latencies, 95),
        "errors": [r["id"] for r in rows if r["error"]],
        "leaks": [r["id"] for r in rows if r["leak"]],
    }


def by_category(rows: list[dict]) -> list[dict]:
    out = []
    for category in dict.fromkeys(r["category"] for r in rows):
        group = [r for r in rows if r["category"] == category]
        hit = [r for r in group if not r["oos"]]
        out.append(
            {
                "category": category,
                "n": len(group),
                "top1": sum(r["top1"] for r in hit) / len(hit) if hit else None,
                "top4": sum(r["top4"] for r in hit) / len(hit) if hit else None,
                "empty": sum(r["empty"] for r in group) / len(group),
                "meanSeconds": statistics.fmean(r["seconds"] for r in group),
                "p95Seconds": percentile([r["seconds"] for r in group], 95),
                "usd": statistics.fmean(r["usd"] for r in group),
            }
        )
    return out


def pct(value) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def report(rows: list[dict], totals: dict, cats: list[dict], cost: dict, ground: Grounding) -> str:
    verdict = {
        "top-1 in-scope >= 95%": totals["top1"] >= TARGETS["top1"],
        "out-of-scope empty >= 90%": totals["oosEmpty"] >= TARGETS["oos"],
        "p95 latency <= 4 s": totals["p95Seconds"] <= TARGETS["p95"],
        "mean cost per ask <= $0.002": cost["meanUsd"] <= TARGETS["usd"],
        "no prose fields on AskResponse": not totals["leaks"],
        "no ungrounded spec quote on a returned section": not ground.violations,
    }
    lines = [
        "# ask eval",
        "",
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · {totals['n']} queries · "
        f"router {settings.model_router} · picker {settings.model_picker}",
        "",
        "## Gates",
        "",
        "| gate | value | pass |",
        "| --- | --- | --- |",
        f"| top-1 in-scope >= 95% | {pct(totals['top1'])} | {'PASS' if verdict['top-1 in-scope >= 95%'] else 'FAIL'} |",
        f"| out-of-scope empty >= 90% | {pct(totals['oosEmpty'])} | {'PASS' if verdict['out-of-scope empty >= 90%'] else 'FAIL'} |",
        f"| p95 latency <= 4 s | {totals['p95Seconds']:.2f} s | {'PASS' if verdict['p95 latency <= 4 s'] else 'FAIL'} |",
        f"| mean cost per ask <= $0.002 | ${cost['meanUsd']:.5f} | {'PASS' if verdict['mean cost per ask <= $0.002'] else 'FAIL'} |",
        f"| AskResponse carries ids and scores only | {len(totals['leaks'])} leaks | "
        f"{'PASS' if verdict['no prose fields on AskResponse'] else 'FAIL'} |",
        f"| spec answers grounded | {len(ground.violations)} ungrounded quotes | "
        f"{'PASS' if verdict['no ungrounded spec quote on a returned section'] else 'FAIL'} |",
        "",
        "## Accuracy by category",
        "",
        "| category | n | top-1 | top-4 | empty | mean s | p95 s | mean $ |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in cats:
        lines.append(
            f"| {c['category']} | {c['n']} | {pct(c['top1'])} | {pct(c['top4'])} | {pct(c['empty'])} | "
            f"{c['meanSeconds']:.2f} | {c['p95Seconds']:.2f} | ${c['usd']:.5f} |"
        )
    lines += [
        "",
        f"In-scope top-1 {pct(totals['top1'])}, top-4 {pct(totals['top4'])} over {totals['inScope']} queries. "
        f"In-scope answers that came back empty: {pct(totals['inScopeEmpty'])}.",
        f"Out-of-scope false positives {pct(totals['oosFalsePositive'])}.",
        "",
        "## Latency and cost",
        "",
        f"- mean {totals['meanSeconds']:.2f} s, p95 {totals['p95Seconds']:.2f} s (sequential, cold cache)",
        f"- cost log delta on ask.* routes ${cost['totalUsd']:.4f} over {totals['n']} asks "
        f"= ${cost['meanUsd']:.5f} per ask (${cost['otherUsd']:.4f} logged by other routes meanwhile)",
        f"- by route: " + ", ".join(f"{k} ${v:.4f}" for k, v in sorted(cost["byRoute"].items())),
        f"- LLM calls: {cost['events']} for {totals['n']} asks ({cost['events'] / max(1, totals['n']):.2f} per ask)",
        "",
        "## Grounding (spec answers)",
        "",
        f"- spec rows on returned sections whose quote is not verbatim on its page: {len(ground.violations)}",
        f"- spec answers whose lead section has no parsed spec row (printed value not extracted): {len(ground.unsourced)}",
    ]
    for note in ground.violations[:10]:
        lines.append(f"  - violation: {note}")
    for note in ground.unsourced[:10]:
        lines.append(f"  - unsourced: {note}")
    misses = [r for r in rows if (not r["oos"] and not r["top1"]) or (r["oos"] and not r["empty"])]
    lines += ["", f"## Misses ({len(misses)})", ""]
    if not misses:
        lines.append("None.")
    for r in misses:
        lines.append(
            f"- `{r['id']}` {r['manual']} {r['query']!r} -> {r['got'][:4] or '[]'} "
            f"(expected {r['expect'] or '[]'}, intent {r['intent']})"
        )
    if totals["errors"]:
        lines += ["", "## Errors", ""] + [f"- {i}" for i in totals["errors"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1, help="1 keeps latency honest; >1 is for quick accuracy loops")
    parser.add_argument("--category", action="append", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default=str(HERE / "report.md"))
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    manuals, cases = load()
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    if args.limit:
        cases = cases[: args.limit]

    ask.clear_cache()  # cache-bust: repeated runs must really call the model
    store = get_store()
    before = len(store.costs())

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(lambda c: run_one(c, manuals[c["manual"]]), cases))
    else:
        rows = []
        for i, case in enumerate(cases, 1):
            rows.append(run_one(case, manuals[case["manual"]]))
            mark = "." if (rows[-1]["top1"] or (rows[-1]["oos"] and rows[-1]["empty"])) else "x"
            print(mark, end="" if i % 50 else f" {i}\n", flush=True)
        print(flush=True)

    delta = store.costs()[before:]
    events = [e for e in delta if e.route.startswith("ask.")]  # the cost log is shared with ingest and identify
    cost = {
        "totalUsd": sum(e.usd for e in events),
        "meanUsd": sum(e.usd for e in events) / max(1, len(cases)),
        "events": len(events),
        "byRoute": {r: sum(e.usd for e in events if e.route == r) for r in sorted({e.route for e in events})},
        "otherUsd": sum(e.usd for e in delta if not e.route.startswith("ask.")),
    }
    ground = Grounding(sorted(set(manuals.values())))
    for row in rows:
        if row["category"] == "spec" or row["intent"] == "spec":
            ground.check(row, row["manualId"], row["got"])

    totals = summarise(rows)
    cats = by_category(rows)
    text = report(rows, totals, cats, cost, ground)
    Path(args.out).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows, "totals": totals, "cost": cost}, default=str), "utf-8")
    print(text)
    print(f"written: {args.out}")
    ok = (
        totals["top1"] >= TARGETS["top1"]
        and totals["oosEmpty"] >= TARGETS["oos"]
        and totals["p95Seconds"] <= TARGETS["p95"]
        and cost["meanUsd"] <= TARGETS["usd"]
        and not totals["leaks"]
        and not ground.violations
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Live eval of the chat pipeline. Run from api/:  .venv/Scripts/python eval/chat_eval.py

Twenty rider questions (ten KTM 390 Duke 2024, ten BMW) go through chat.answer for real: real router,
real BM25, real The Token Company compression, real streamed OpenAI answer. Prints grounding rate,
citation validity, tokens before/after TTC, $/answer and latency (time to first token, and total).
Writes eval/chat-report.md.

Costs real money and needs both keys. --dry lists the questions and exits.
"""

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import chat, ttc  # noqa: E402
from app.config import settings  # noqa: E402
from app.store import get_store  # noqa: E402

HERE = Path(__file__).resolve().parent
TARGETS = {"citations": 0.95, "grounded": 0.95, "saved": 0.30, "ttft": 4.0}
CITE = chat.CITE  # one pattern for both, so the eval cannot disagree with the server about a citation
MASK = "␟"  # a character no manual prints, so masking a citation cannot collide with the text
# What counts as a claim: any sentence of four words or more. Deliberately blunt - a verb list
# let "Loosen the rear wheel nut and the adjuster nuts" through uncounted, which flatters the score.
CLAIM_WORDS = 4
# Sentences that state the ABSENCE of printed data, or just list pages to open, assert nothing the
# manual could be cited for. They are navigation and status, not claims.
ABSENCE = re.compile(r"(?:prints? no|no .{0,40}(?:is|are) (?:printed|provided|given)|no (?:applicable|relevant|specific) .{0,30}page|^Open[: ])", re.I)

QUESTIONS = [
    ("ktm", "how much oil does it take"),
    ("ktm", "chain is loose, what do I do"),
    ("ktm", "what pressure should the tyres be"),
    ("ktm", "how do I check the brake pads on the front"),
    ("ktm", "my battery is flat, can I charge it on the bike"),
    ("ktm", "torque for the rear axle nut"),
    ("ktm", "which oil do I need"),
    ("ktm", "a fuse blew, where is the fuse box"),
    ("ktm", "how do I get the rear wheel off"),
    ("ktm", "when is my next service due"),
    ("bmw", "how do I check the engine oil level"),
    ("bmw", "what tyre pressure two up with luggage"),
    ("bmw", "how do I adjust the headlight"),
    ("bmw", "coolant is low, what do I top it up with"),
    ("bmw", "how do I take the seat off"),
    ("bmw", "brake fluid spec"),
    ("bmw", "how do I set the spring preload"),
    ("bmw", "jump start it from a car"),
    ("bmw", "what is the minimum tread depth"),
    ("bmw", "best exhaust for it"),  # out of scope: must come back uncited
    # Jobs an owner manual answers with "see your dealer". A mechanic needs the figures it prints anyway,
    # and must never be sent to a workshop they are standing in.
    ("ktm", "valve clearance spec"),
    ("ktm", "how do I sync the throttle bodies"),
    ("bmw", "steering head bearing play check"),
    ("bmw", "fork oil change"),
    ("ktm", "when does the chain need replacing"),
]

# Advice a mechanic must never be given back. Matched on the answer, not the sources: the manual says it
# constantly, the answer may not. "retailer"/"specialist" are how BMW phrases the same referral.
REFERRAL = re.compile(r"\b(?:dealer|retailer|workshop|specialist|service cent(?:re|er))\b", re.I)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))]


def page_text(manual_id: str) -> dict[int, str]:
    return {p.page: p.text for p in get_store().pages(manual_id)}


STATUS = (chat.NOT_COVERED,)
# The five jobs an owner manual hands to a workshop. They must now come back as general steps +
# printed values + page chips, never as a refusal.
UNDERDOCUMENTED = {
    "valve clearance spec",
    "how do I sync the throttle bodies",
    "steering head bearing play check",
    "fork oil change",
    "when does the chain need replacing",
}


def claims(answer: str) -> list[tuple[str, bool]]:
    """(sentence, carries a citation) for every sentence that actually states something.

    The marker is masked before splitting: `[p. 78]` ends in a full stop after "p", so a naive sentence
    split cuts the citation off the claim it belongs to and scores a perfectly grounded answer at 0 %.
    """
    body = answer
    if chat.GENERAL in body:
        # General-procedure steps are declared NOT to come from the manual, so they are not claims that
        # should carry a [p. N]. Counting them would score the new policy as a grounding regression.
        body = "\n".join(
            line
            for line in body.split("\n")
            if not line.strip().startswith(chat.GENERAL) and not re.match(r"^\s*\d+[.)]\s", line)
        )
    masked = CITE.sub(lambda m: f"{MASK}{m.group(1)}{MASK}", body)
    out: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", masked):
        sentence = sentence.strip()
        cited = MASK in sentence
        bare = re.sub(rf"{MASK}[^{MASK}]*{MASK}", "", sentence).strip(" .;,")
        if not bare:
            # A fragment that is nothing but citations: the model wrote "... taut. [p. 77]", so the
            # citation belongs to the sentence before it, not to a claim of its own.
            if cited and out:
                out[-1] = (out[-1][0], True)
            continue
        if bare.rstrip(".") in [t.rstrip(".") for t in STATUS] or ABSENCE.search(bare):
            continue  # states no fact the manual could be cited for: a status or navigation line
        if len(bare.split()) >= CLAIM_WORDS:
            out.append((bare, cited))
    return out


def run_one(manual_id: str, question: str, pages: dict[int, str]) -> dict:
    """One chat turn, timed at the first token because that is what the rider feels."""
    started = time.perf_counter()
    first = None
    done: dict = {}
    error = ""
    try:
        for frame in chat.answer(manual_id, [{"role": "user", "content": question}]):
            payload = json.loads(frame[len("data: ") : -2])
            if payload["type"] == "token" and first is None:
                first = time.perf_counter() - started
            elif payload["type"] == "done":
                done = payload
    except Exception as exc:  # a crashed turn is a failed turn, not a crashed eval
        error = f"{type(exc).__name__}: {exc}"
    total = time.perf_counter() - started

    answer = done.get("answer", "")
    citations = done.get("citations", [])
    covered = answer.strip() == chat.NOT_COVERED

    referrals = sorted({m.group(0).lower() for m in REFERRAL.finditer(answer)})
    cited_text = {c["page"]: pages.get(c["page"], "") for c in citations}
    invented = chat._unverified_numbers(answer, cited_text) if citations else chat._unverified_numbers(answer, {})
    stated = claims(answer) if not covered else []
    grounded = [s for s, cited in stated if cited]
    valid = [c for c in citations if c.get("quote") and c["quote"] in pages.get(c.get("page", -1), "")]

    return {
        "manual": manual_id,
        "question": question,
        "answer": answer,
        "error": error,
        "notCovered": covered,
        "referrals": referrals,
        "invented": invented,
        "general": chat.GENERAL in answer,
        "chips": len({c["page"] for c in citations}),
        "claims": len(stated),
        "groundedClaims": len(grounded),
        "citations": len(citations),
        "validCitations": len(valid),
        "usd": float(done.get("usd", 0.0)),
        "tokensIn": int(done.get("tokensIn", 0)),
        "tokensSaved": int(done.get("tokensSaved", 0)),
        "ttft": first if first is not None else total,
        "seconds": total,
    }


def summarise(rows: list[dict], compression: dict) -> dict:
    answered = [r for r in rows if not r["notCovered"] and not r["error"]]
    claim_count = sum(r["claims"] for r in answered)
    grounded = sum(r["groundedClaims"] for r in answered)
    cited = sum(r["citations"] for r in rows)
    valid = sum(r["validCitations"] for r in rows)
    ttft = [r["ttft"] for r in rows if not r["error"]]
    total = [r["seconds"] for r in rows if not r["error"]]
    before = compression["total"]["tokensIn"]
    after = compression["total"]["tokensOut"]
    return {
        "n": len(rows),
        "answered": len(answered),
        "notCovered": sum(r["notCovered"] for r in rows),
        "generalAnswers": sum(r["general"] for r in rows),
        "errors": [f"{r['question']}: {r['error']}" for r in rows if r["error"]],
        "groundingRate": grounded / claim_count if claim_count else 0.0,
        "claims": claim_count,
        "citationValidity": valid / cited if cited else 0.0,
        "citations": cited,
        "uncitedAnswers": [r["question"] for r in answered if not r["citations"]],
        "referralAnswers": [f"{r['question']}: {', '.join(r['referrals'])}" for r in rows if r["referrals"]],
        "inventedAnswers": [f"{r['question']}: {', '.join(r['invented'])}" for r in rows if r["invented"]],
        "underDocumentedBad": [
            f"{r['question']}: " + ", ".join(
                filter(None, [
                    "" if (r["general"] or r["citations"]) else "neither general steps nor printed values",
                    "" if r["chips"] else "no page chips",
                    "refused" if r["notCovered"] else "",
                ])
            )
            for r in rows
            if r["question"] in UNDERDOCUMENTED
            and not (not r["notCovered"] and r["chips"] and (r["general"] or r["citations"]))
        ],
        "tokensBefore": before,
        "tokensAfter": after,
        "tokensSavedPct": (before - after) / before if before else 0.0,
        "usdPerAnswer": statistics.fmean([r["usd"] for r in rows]) if rows else 0.0,
        "usdTotal": sum(r["usd"] for r in rows),
        "tokensInPerAnswer": statistics.fmean([r["tokensIn"] for r in rows]) if rows else 0.0,
        "ttftP50": percentile(ttft, 50),
        "ttftP95": percentile(ttft, 95),
        "p50Seconds": percentile(total, 50),
        "p95Seconds": percentile(total, 95),
    }


def verdict(s: dict) -> dict:
    return {
        "valid citations >= 95 %": (s["citationValidity"] >= TARGETS["citations"], f"{s['citationValidity']:.1%}"),
        "claims carrying a citation >= 95 %": (s["groundingRate"] >= TARGETS["grounded"], f"{s['groundingRate']:.1%}"),
        "tokens saved by TTC >= 30 %": (s["tokensSavedPct"] >= TARGETS["saved"], f"{s['tokensSavedPct']:.1%}"),
        "p50 time to first token <= 4 s": (s["ttftP50"] <= TARGETS["ttft"], f"{s['ttftP50']:.2f} s"),
        "no answer sends a mechanic to a dealer": (not s["referralAnswers"], f"{len(s['referralAnswers'])} of {s['n']}"),
        "no invented numbers": (not s["inventedAnswers"], f"{len(s['inventedAnswers'])} of {s['n']}"),
        "under-documented jobs answered with steps + pages": (
            not s["underDocumentedBad"],
            f"{len(UNDERDOCUMENTED) - len(s['underDocumentedBad'])} of {len(UNDERDOCUMENTED)}",
        ),
    }


def report(rows: list[dict], s: dict, checks: dict, compression: dict) -> str:
    lines = [
        "# Chat eval",
        "",
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · {settings.model_chat} · "
        f"router {settings.model_router} · compression {compression['model']} "
        f"({'on' if compression['enabled'] else 'OFF'})",
        "",
        "| check | value | |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {name} | {value} | {'PASS' if ok else 'FAIL'} |" for name, (ok, value) in checks.items()]
    lines += [
        "",
        "## Totals",
        f"- {s['n']} questions, {s['answered']} answered, {s['notCovered']} declined as not about this bike, "
        f"{s['generalAnswers']} carried general steps the manual does not print",
        f"- grounding: {s['groundingRate']:.1%} of {s['claims']} claim sentences carry a [p. N]",
        f"- citations: {s['citations']} returned, {s['citationValidity']:.1%} verbatim on the page they name",
        f"- TTC: {s['tokensBefore']} tokens in -> {s['tokensAfter']} out, {s['tokensSavedPct']:.1%} saved "
        f"({compression['total']['calls']} calls, {compression['total']['cached']} cached, "
        f"{compression['total']['errors']} failed -> uncompressed)",
        f"- cost: ${s['usdPerAnswer']:.5f} per answer, ${s['usdTotal']:.4f} for the run, "
        f"{s['tokensInPerAnswer']:.0f} prompt tokens per answer",
        f"- latency: first token p50 {s['ttftP50']:.2f} s / p95 {s['ttftP95']:.2f} s; "
        f"full answer p50 {s['p50Seconds']:.2f} s / p95 {s['p95Seconds']:.2f} s",
        "",
        "## Per question",
        "",
        "| manual | question | claims | cited | valid | saved | $ | ttft |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['manual'].split('-')[0]} | {r['question']} | {r['groundedClaims']}/{r['claims']} | "
            f"{r['citations']} | {r['validCitations']} | {r['tokensSaved']} | ${r['usd']:.5f} | {r['ttft']:.2f} s |"
        )
    if s["errors"]:
        lines += ["", "## Errors", *[f"- {e}" for e in s["errors"]]]
    if s["inventedAnswers"]:
        lines += ["", "## Numbers not printed on the cited pages", *[f"- {a}" for a in s["inventedAnswers"]]]
    if s["underDocumentedBad"]:
        lines += ["", "## Under-documented jobs answered wrongly", *[f"- {a}" for a in s["underDocumentedBad"]]]
    if s["referralAnswers"]:
        lines += ["", "## Answers that referred the mechanic elsewhere", *[f"- {a}" for a in s["referralAnswers"]]]
    if s["uncitedAnswers"]:
        lines += ["", "## Answered without a citation", *[f"- {q}" for q in s["uncitedAnswers"]]]
    lines += ["", "## Answers", ""]
    for r in rows:
        lines += [f"**{r['question']}**", "", f"> {r['answer'] or r['error']}", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(HERE / "chat-report.md"))
    parser.add_argument("--dry", action="store_true", help="list the questions and exit, no API calls")
    args = parser.parse_args()

    manuals = json.loads((HERE / "queries.json").read_text(encoding="utf-8"))["manuals"]
    cases = [(manuals[key], question) for key, question in QUESTIONS]

    if args.dry:
        for manual_id, question in cases:
            print(f"{manual_id:28} {question}")
        return 0

    if not settings.openai_api_key:
        print("no OPENAI_API_KEY", file=sys.stderr)
        return 2
    if not settings.ttc_api_key:
        print("warning: no TTC key, the compression numbers will be zero", file=sys.stderr)

    pages = {manual_id: page_text(manual_id) for manual_id in dict.fromkeys(m for m, _ in cases)}
    ttc.reset()

    rows = []
    for i, (manual_id, question) in enumerate(cases, 1):
        row = run_one(manual_id, question, pages[manual_id])
        rows.append(row)
        mark = "N" if row["invented"] else "D" if row["referrals"] else ("x" if row["error"] else ("." if row["citations"] or row["notCovered"] else "o"))
        print(f"{mark} {i:2}/{len(cases)} {row['ttft']:5.2f}s {question}", flush=True)

    compression = ttc.stats()
    summary = summarise(rows, compression)
    summary["validCitations"] = sum(r["validCitations"] for r in rows)
    checks = verdict(summary)

    text = report(rows, summary, checks, compression)
    Path(args.out).write_text(text, encoding="utf-8")
    # Machine-readable sidecar: the per-sentence grounding detail, so a regression can be diffed
    # instead of re-parsed out of the markdown.
    Path(args.out).with_suffix(".json").write_text(
        json.dumps(
            {
                "summary": summary,
                "compression": compression,
                "rows": [{**r, "sentences": [{"text": t, "cited": c} for t, c in claims(r["answer"])]} for r in rows],
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print()
    print(text.split("## Per question")[0])
    print(f"written: {args.out}")
    return 0 if all(ok for ok, _ in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

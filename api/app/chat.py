"""Chat over ONE manual, grounded in its printed pages, streamed. Owner: chat agent.

answer(manual_id, messages) -> Iterator[str], SSE frames:
    data: {"type":"token","text":"..."}
    data: {"type":"done","answer":...,"citations":[{"page":N,"quote":"..."}],"usd":...,"tokensIn":...,"tokensSaved":...}

Loop: router rephrasings (app/ask.py) -> BM25 sections (app/search) -> the printed page text behind them ->
The Token Company compression (app/ttc.py) -> streamed OpenAI answer that may only use those pages.

GROUNDED-CITATION PATTERN ADOPTED FROM:
    LlamaIndex CitationQueryEngine - https://github.com/run-llama/llama_index - MIT licence
    llama-index-core/llama_index/core/query_engine/citation_query_engine.py (CITATION_QA_TEMPLATE)
Taken: the retrieve -> number every chunk -> "answer based solely on the provided sources, cite the
corresponding numbers, every answer includes at least one citation, only cite what you reference, say so when
no source helps" loop, its worked two-source example that teaches the citation format before the real sources
arrive, and the `------`-fenced source block.
Changed: the chunk number IS the printed page number, so `Source 1` / `[1]` becomes `Page 84` / `[p. 84]` and a
citation is a place the rider can be sent to; chunking is per manual page instead of SentenceSplitter(512/20);
added this app's bans (no invented figures, no advice the manual does not print) and Responses-API streaming.

Why the server, not the model, writes every `quote`: bear-2 compression strips punctuation and stopwords, so a
quote copied out of a compressed passage would never be verbatim. The model cites pages; _quote() then slices
the ORIGINAL page text. Citations are verbatim by construction, not by trusting the model.
"""

import json
import re
from collections.abc import Iterator

from . import ask as ask_mod
from . import llm, ttc
from .config import settings
from .search import get_index
from .search.local import canon
from .store import get_store

MAX_PAGES = 6
TOKEN_BUDGET = 8000
# Compression only ever shrinks, so the pre-compression ceiling may sit above the budget.
RAW_CEILING = 14000
HARD_AGGRESSIVENESS = 0.5
SOFT_AGGRESSIVENESS = 0.3
MEMORY_TURNS = 6
CANDIDATES = 6
MAX_OUTPUT = 700
EFFORT = "low"
MIN_QUOTE = 24
MAX_QUOTE = 240
QUOTE_LINES = 3
NOT_COVERED = "Not in this manual."

CITE = re.compile(r"\[p\.\s*(\d+)\]")
MARKER = re.compile(r"PAGE (\d+)")

SYSTEM = f"""You answer one question from a rider standing next to their motorcycle, with dirty hands, using
ONLY the printed pages of that motorcycle's own manual. The pages are given to you below as numbered sources;
each source is one printed page and its number is the page number printed in that manual.

Please provide an answer based solely on the provided sources. When referencing information from a source, cite
the appropriate page using its number, written exactly as [p. N]. EVERY sentence that states a fact, a step, a
figure or a name carries its own citation, placed at the end of that sentence, before the full stop - never one
citation at the end of a whole paragraph, and never a sentence left bare because the sentence before it was
cited. Only cite a page when you are explicitly referencing it. If none of the sources answer the question,
reply with exactly this sentence and nothing else: "{NOT_COVERED}"

For example:
Page 12:
Check the engine oil level with the motorcycle standing upright on a level surface.
Page 97:
Engine oil, quantity with filter change: 1.7 l.
Question: how much oil does it take?
Answer: It takes 1.7 l with a filter change [p. 97]. Check the level with the bike upright on level ground [p. 12].

Now it's your turn. Rules for your answer:
- Short. Two to five sentences, or up to six numbered steps for a procedure. No preamble, no sign-off, no
  "according to the manual", no offers to help further, no warnings the manual does not print.
- Mechanic-plain. Say what to do and in what order. Plain words a rider knows.
- Never invent a number. Torque figures, capacities, pressures, clearances, grades, fuse ratings, part
  designations and intervals may only be repeated if they are printed in a source, with that source cited. If
  the rider asks for a figure that no source prints, say the manual does not print it and cite nothing for it.
  A wrong torque figure breaks a motorcycle; guessing one is the single worst thing you can do here.
- Never carry a figure over from another motorcycle, from another section, or from your own knowledge.
- The sources have been machine-compressed, so their grammar and punctuation may be damaged. Read them for
  meaning; write your own clean sentences. Never copy a mangled fragment and never mention the compression.
- Answer only about THIS motorcycle. Riding technique, tuning, aftermarket parts, prices, dealers, insurance,
  routes and other vehicles are all "{NOT_COVERED}".
- Cite only page numbers that appear in the sources below. Never invent a page number."""


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _latest(messages: list[dict]) -> str:
    for message in reversed(messages):
        if (message.get("role") or "user") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _history(messages: list[dict]) -> list[dict]:
    """The last MEMORY_TURNS turns before the one being answered, so follow-ups ("and the rear?") work."""
    prior = messages[:-1] if messages and (messages[-1].get("role") or "user") == "user" else list(messages)
    out = []
    for message in prior[-MEMORY_TURNS:]:
        content = str(message.get("content") or "").strip()
        role = "assistant" if message.get("role") == "assistant" else "user"
        if content:
            out.append({"role": role, "content": content[:2000]})
    return out


def _pages_for(manual_id: str, question: str) -> list[int]:
    """Router rephrasings -> BM25 sections -> the distinct printed pages behind them, best section first."""
    manual = get_store().manual(manual_id)
    if manual is None:
        return []
    route = ask_mod._route(question)
    if route.intent == "unknown":
        return []
    sections = {s.id: s for s in manual.sections}
    hits = [h for h in get_index().query(manual_id, route.queries, route.components, k=CANDIDATES) if h.sectionId in sections]
    ordered: list[int] = []
    for hit in hits:
        section = sections[hit.sectionId]
        for page in range(section.pageStart, section.pageEnd + 1):
            if page not in ordered:
                ordered.append(page)
    return ordered[:MAX_PAGES]


def _split(compressed: str, pages: list[int]) -> dict[int, str] | None:
    """Undo _join. None when the markers did not survive compression, which is the whole safety check:
    a lost marker means text from one page would be attributed to another, so we use the original instead."""
    parts = MARKER.split(compressed)[1:]
    found = [int(parts[i]) for i in range(0, len(parts), 2)]
    if found != pages:
        return None
    out = {int(parts[i]): parts[i + 1].strip() for i in range(0, len(parts), 2)}
    return out if all(out.values()) else None


def _join(original: dict[int, str]) -> str:
    return "\n".join(f"PAGE {page}\n{text}" for page, text in original.items())


def _passages(manual_id: str, pages: list[int]) -> tuple[dict[int, str], dict[int, str], int, int]:
    """(original text per page, compressed text per page, tokens before, tokens after).

    ONE compress call for the whole prompt, not one per page: the API allows 60 requests/minute, so
    per-page calls would cap the app at ten chats a minute and 429 under any load. The pages are fenced
    with `PAGE N` markers, which bear-2 keeps at 0.3, and _split re-checks every marker afterwards.
    """
    by_page = {p.page: p.text for p in get_store().pages(manual_id) if p.page in set(pages)}
    original = {page: by_page[page] for page in pages if by_page.get(page, "").strip()}
    # Trim before paying for compression: a page dropped here costs nothing to compress.
    while len(original) > 1 and sum(_tokens(t) for t in original.values()) > RAW_CEILING:
        original.pop(next(page for page in reversed(pages) if page in original))
    if not original:
        return {}, {}, 0, 0

    raw_tokens = sum(_tokens(t) for t in original.values())
    # Adaptive: a normal hit compresses at 0.3, an oversized one harder rather than losing whole pages.
    aggressiveness = HARD_AGGRESSIVENESS if raw_tokens > TOKEN_BUDGET else SOFT_AGGRESSIVENESS
    out, before, after = ttc.compress(_join(original), aggressiveness, "chat")
    compressed = _split(out, list(original)) if before else None
    if compressed is None:
        # Compression off, failed, or mangled the markers: the printed text is always the safe answer.
        compressed, before, after = dict(original), 0, 0

    # Last resort when even compressed pages overflow: drop the weakest page, never truncate mid-sentence.
    # `pages` is best-section-first, so the last surviving entry is the weakest.
    while len(compressed) > 1 and sum(_tokens(t) for t in compressed.values()) > TOKEN_BUDGET:
        worst = next(page for page in reversed(pages) if page in compressed)
        compressed.pop(worst)
        original.pop(worst)
    return original, compressed, before, after


def _context(compressed: dict[int, str]) -> str:
    body = "\n".join(f"Page {page}:\n{' '.join(text.split())}" for page, text in compressed.items())
    return f"Below are several numbered sources of information:\n------\n{body}\n------\n"


def _quote(page_text: str, answer: str, question: str) -> str:
    """The best verbatim slice of THIS page for what was answered. Always a substring of page_text."""
    lines = page_text.split("\n")
    wanted = set(canon(answer)) | set(canon(question))
    best, best_score = "", 0.0
    for i in range(len(lines)):
        for span in range(1, QUOTE_LINES + 1):
            if i + span > len(lines):
                break
            window = "\n".join(lines[i : i + span]).strip()
            if not (MIN_QUOTE <= len(window) <= MAX_QUOTE):
                continue
            tokens = set(canon(window))
            if not tokens:
                continue
            # Overlap, damped by length so a whole paragraph cannot outscore the one printed line that answers it.
            score = len(wanted & tokens) / (len(tokens) ** 0.5)
            if score > best_score:
                best, best_score = window, score
    return best if best_score > 0 and best in page_text else ""


def _citations(answer: str, question: str, original: dict[int, str]) -> list[dict]:
    """Only pages the model was actually shown, each with a quote verified verbatim against that page."""
    out: list[dict] = []
    seen: set[int] = set()
    for match in CITE.finditer(answer):
        page = int(match.group(1))
        if page in seen or page not in original:
            continue
        seen.add(page)
        quote = _quote(original[page], answer, question)
        if quote:
            out.append({"page": page, "quote": quote})
    return out


def _frame(**payload) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _plain(text: str, saved: int = 0) -> Iterator[str]:
    yield _frame(type="token", text=text)
    yield _frame(type="done", answer=text, citations=[], usd=0.0, tokensIn=0, tokensSaved=saved)


def answer(manual_id: str, messages: list[dict]) -> Iterator[str]:
    question = _latest(messages)
    if not question:
        yield from _plain(NOT_COVERED)
        return

    try:
        pages = _pages_for(manual_id, question)
        original, compressed, before, after = _passages(manual_id, pages) if pages else ({}, {}, 0, 0)
    except Exception:
        original, compressed, before, after = {}, {}, 0, 0
    saved = max(0, before - after)

    # Nothing printed in this manual matches: that is the answer, and it costs nothing to give.
    if not compressed:
        yield from _plain(NOT_COVERED, saved)
        return

    user = f"{_context(compressed)}Question: {question}\nAnswer: "
    parts: list[str] = []
    usage = {"usd": 0.0, "tokensIn": 0}
    try:
        for kind, payload in llm.stream(
            route="chat.answer",
            model=settings.model_chat,
            system=SYSTEM,
            user=user,
            history=_history(messages),
            cache_key=f"chat:{settings.model_chat}",
            reasoning=EFFORT,
            max_output_tokens=MAX_OUTPUT,
        ):
            if kind == "delta":
                parts.append(str(payload))
                yield _frame(type="token", text=payload)
            elif isinstance(payload, dict):
                usage = payload
    except Exception:
        if not parts:
            yield from _plain(NOT_COVERED, saved)
            return

    text = "".join(parts).strip() or NOT_COVERED
    yield _frame(
        type="done",
        answer=text,
        citations=_citations(text, question, original),
        usd=round(float(usage.get("usd", 0.0)), 6),
        tokensIn=int(usage.get("tokensIn", 0)),
        tokensSaved=saved,
    )

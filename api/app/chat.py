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

# Accepts [p. 84], [pp. 68-69] and [pp. 68, 69]: the model reaches for all three, and a citation the
# pattern misses is both a lost page chip and a false "invented number".
CITE = re.compile(r"\[pp?\.\s*([0-9][0-9,;\s–—-]*)\]")
PAGE_NUM = re.compile(r"\d+")
MARKER = re.compile(r"PAGE (\d+)")

# Owner manuals pad every job with "consult an authorised workshop". The reader here is a mechanic with
# the bike already on the lift, so that sentence is noise that crowds out the printed values next to it.
# PDF text layers hyphenate across line breaks ("spe- cialist", "autho- rized"), so de-hyphenate first.
HYPHEN = re.compile(r"(\w)-\s+(\w)")
DEALER = re.compile(r"\b(?:dealer|retailer|workshop|specialist|service cent(?:re|er))\b", re.I)
# Split only where a full stop is followed by space + a new sentence: splitting on every "." would
# cut "0.10 mm" into "0. 10 mm" and corrupt exactly the printed values this is meant to protect.
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
# Below this a page is boilerplate with nothing printed on it, so it loses its slot to a page that prints something.
MIN_SUBSTANTIVE = 200
GENERAL = "General procedure, not printed in this manual:"

# Every number the model writes must be copied off a printed page. These let the check ignore the two
# kinds of digit that are legitimately the model's own: the step number, and the page inside a citation.
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
STEP = re.compile(r"^\s*\d+[.)]\s", re.M)

SYSTEM = f"""You answer one question from a professional motorcycle mechanic who has this bike on the lift,
using ONLY the printed pages of that motorcycle's own manual. The pages are given to you below as numbered
sources; each source is one printed page and its number is the page number printed in that manual.

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
- You are writing for a professional mechanic who already has the bike on the lift and the tools in hand.
  Terse and technical: values, steps, tools. No preamble, no sign-off, no "according to the manual", no
  offers to help further. Two to five sentences, or up to six numbered steps.
- NEVER tell the reader to visit, consult, contact or have the work done by a dealer, a retailer, an
  authorised workshop, a specialist workshop or a service centre. They ARE the workshop. Owner manuals pad
  most jobs with that referral; it is the one thing in the sources you must not pass on.
- NEVER add safety boilerplate: no "for your safety", no "if you are unsure", no "improper work can cause
  accidents", no warnings or disclaimers of your own. The reader knows the risks of the job.
- Refuse with "{NOT_COVERED}" ONLY when the question is not about servicing or operating THIS motorcycle:
  riding technique, tuning, aftermarket parts, prices, insurance, routes, other vehicles, small talk. That
  is the only refusal you have. Anything a mechanic would actually do to this bike gets a real answer.
- An owner's manual does not fully print most standard jobs - brake fluid change, brake pad change, chain
  replacement, valve clearance check, fork oil, coolant change, the details of an oil change. NEVER refuse
  one of those and never call it "{NOT_COVERED}". Answer it in three parts, in this order:
  1. The line "{GENERAL}" and then 3 to 6 terse steps of standard workshop practice for a motorcycle of
     this type. Imperative, one clause per step, name the tool. These steps are your own general knowledge,
     so they carry NO NUMBERS AT ALL beyond the step number itself - no torque, no capacity, no interval,
     no wear limit, no "two turns", no "30 minutes". If a step needs a figure, say which figure is needed
     ("to the printed torque") and let part 2 supply it.
  2. Then the printed figures: every specification, fluid grade, capacity, torque, interval, tolerance and
     wear limit the sources print for this job, one per line, each with its [p. N].
  3. Then the pages to open, as a short line starting "Open:" followed by bare [p. N] citations for the
     check or level sections closest to the job.
  If the sources print no figure at all for the job, keep parts 1 and 3 and say plainly that the manual
  prints no figures for it. Never reach for a figure belonging to a different job to pad part 2.
- If a torque, clearance, capacity, pressure or interval for the job is printed ANYWHERE in the sources,
  including a technical-data or tightening-torque table on another page, surface it and cite that page.
- EVERY number anywhere in your answer must be copied from a source and carry a [p. N]. The only digits you
  may write that are your own are the step numbers in part 1. No torque, capacity, pressure, clearance,
  grade, fuse rating, part designation or interval may appear unless it is printed in a source and cited. If
  the reader asks for a figure no source prints, say the manual does not print it and cite nothing for it.
  A wrong torque figure breaks a motorcycle; guessing one is the single worst thing you can do here. Giving
  general steps is now allowed; giving a general NUMBER never is.
- Never carry a figure over from another motorcycle, from another section, or from your own knowledge.
- The sources have been machine-compressed, so their grammar and punctuation may be damaged. Read them for
  meaning; write your own clean sentences. Never copy a mangled fragment and never mention the compression.
- Answer only about THIS motorcycle. Riding technique, tuning, aftermarket parts, prices, insurance, routes
  and other vehicles are all "{NOT_COVERED}".
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


def _pages_for(manual_id: str, question: str) -> tuple[list[int], bool]:
    """(pages, is about this motorcycle). Router rephrasings -> BM25 sections -> the printed pages behind
    them, best section first. The flag is the ONLY thing that may produce a refusal: a real job with no
    matching page still gets a general-procedure answer, it just gets one with nothing to cite."""
    manual = get_store().manual(manual_id)
    if manual is None:
        return [], False
    route = ask_mod._route(question)
    if route.intent == "unknown":
        return [], False
    sections = {s.id: s for s in manual.sections}
    hits = [h for h in get_index().query(manual_id, route.queries, route.components, k=CANDIDATES) if h.sectionId in sections]
    ordered: list[int] = []
    for hit in hits:
        section = sections[hit.sectionId]
        for page in range(section.pageStart, section.pageEnd + 1):
            if page not in ordered:
                ordered.append(page)
    return ordered[:MAX_PAGES], True


def _split(compressed: str, pages: list[int]) -> dict[int, str] | None:
    """Undo _join. None when the markers did not survive compression, which is the whole safety check:
    a lost marker means text from one page would be attributed to another, so we use the original instead."""
    parts = MARKER.split(compressed)[1:]
    found = [int(parts[i]) for i in range(0, len(parts), 2)]
    if found != pages:
        return None
    out = {int(parts[i]): parts[i + 1].strip() for i in range(0, len(parts), 2)}
    return out if all(out.values()) else None


def _strip_referrals(text: str) -> str:
    """Drop pure "have it done by an authorised workshop" sentences from what the model gets to read.

    Only from the CONTEXT - `original` stays pristine, so every citation quote is still sliced out of the
    real printed page. A sentence carrying a digit is never dropped even when it names a workshop: BMW
    prints tightening torques inside exactly such warnings, and the number is the whole point of the answer.
    """
    flat = HYPHEN.sub(r"\1\2", " ".join(text.split()))
    kept = [
        s.strip()
        for s in SENTENCE.split(flat)
        if s.strip() and not (DEALER.search(s) and not any(c.isdigit() for c in s))
    ]
    return " ".join(kept)


def _join(original: dict[int, str]) -> str:
    return "\n".join(f"PAGE {page}\n{text}" for page, text in original.items())


def _passages(manual_id: str, pages: list[int]) -> tuple[dict[int, str], dict[int, str], int, int]:
    """(original text per page, compressed text per page, tokens before, tokens after).

    ONE compress call for the whole prompt, not one per page: the API allows 60 requests/minute, so
    per-page calls would cap the app at ten chats a minute and 429 under any load. The pages are fenced
    with `PAGE N` markers, which bear-2 keeps at 0.3, and _split re-checks every marker afterwards.
    """
    by_page = {p.page: p.text for p in get_store().pages(manual_id) if p.page in set(pages)}
    printed = {page: by_page[page] for page in pages if by_page.get(page, "").strip()}
    clean = {page: _strip_referrals(text) for page, text in printed.items()}

    # A page whose text is nothing but "consult an authorised workshop" answers nothing, so it gives up its
    # slot to a page that prints something. Kept last rather than deleted: sometimes it is all there is.
    ranked = [page for page in pages if page in clean]
    solid = [page for page in ranked if len(clean[page]) >= MIN_SUBSTANTIVE]
    if solid and len(solid) < len(ranked):
        ranked = solid + [page for page in ranked if page not in set(solid)]

    # Trim before paying for compression: a page dropped here costs nothing to compress.
    while len(ranked) > 1 and sum(_tokens(clean[page]) for page in ranked) > RAW_CEILING:
        ranked.pop()
    if not ranked:
        return {}, {}, 0, 0
    original = {page: printed[page] for page in ranked}
    context = {page: clean[page] for page in ranked}

    raw_tokens = sum(_tokens(t) for t in context.values())
    # Adaptive: a normal hit compresses at 0.3, an oversized one harder rather than losing whole pages.
    aggressiveness = HARD_AGGRESSIVENESS if raw_tokens > TOKEN_BUDGET else SOFT_AGGRESSIVENESS
    out, before, after = ttc.compress(_join(context), aggressiveness, "chat")
    compressed = _split(out, ranked) if before else None
    if compressed is None:
        # Compression off, failed, or mangled the markers: the printed text is always the safe answer.
        compressed, before, after = dict(context), 0, 0

    # Last resort when even compressed pages overflow: drop the weakest page, never truncate mid-sentence.
    # `ranked` is best-section-first, boilerplate last, so the last surviving entry is the weakest.
    while len(compressed) > 1 and sum(_tokens(t) for t in compressed.values()) > TOKEN_BUDGET:
        worst = next(page for page in reversed(ranked) if page in compressed)
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
        for found in PAGE_NUM.findall(match.group(1)):
            page = int(found)
            if page in seen or page not in original:
                continue
            seen.add(page)
            quote = _quote(original[page], answer, question)
            if quote:
                out.append({"page": page, "quote": quote})
    return out


def _unverified_numbers(answer: str, original: dict[int, str]) -> list[str]:
    """Numbers in the answer that are printed on none of the pages it was given.

    The model may now write general procedure steps out of its own knowledge, so this is the guard that
    keeps the old promise intact underneath the new freedom: general STEPS are allowed, a general NUMBER
    never is. Step numbers and the page numbers inside [p. N] are the model's own and are excluded.
    """
    printed = " ".join(" ".join(text.split()) for text in original.values()).replace(",", ".")
    text = STEP.sub(" ", CITE.sub(" ", answer))
    loose: list[str] = []
    for match in NUMBER.finditer(text):
        token = match.group(0).replace(",", ".")
        # 0.50 may be printed as 0.5, and 2.0 as 2, so a trimmed form counts as printed too.
        trimmed = token.rstrip("0").rstrip(".") if "." in token else token
        if token in printed or (trimmed and trimmed in printed):
            continue
        loose.append(match.group(0))
    return sorted(set(loose))


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
        pages, servicing = _pages_for(manual_id, question)
        original, compressed, before, after = _passages(manual_id, pages) if pages else ({}, {}, 0, 0)
    except Exception:
        original, compressed, before, after, servicing = {}, {}, 0, 0, True
    saved = max(0, before - after)

    # The only refusal left: the question is not about servicing this motorcycle. Costs nothing to give.
    # A real job whose pages the index missed still gets an answer - general steps with nothing to cite.
    if not servicing:
        yield from _plain(NOT_COVERED, saved)
        return

    sources = _context(compressed) if compressed else "No printed page of this manual matched the question.\n"
    user = f"{sources}Question: {question}\nAnswer: "
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
    citations = _citations(text, question, original)
    if not citations and original and text != NOT_COVERED:
        chips = " ".join(f"[p. {page}]" for page in list(original)[:3])
        tail = f"{chr(10)}Open: {chips}"
        yield _frame(type="token", text=tail)
        text += tail
        citations = _citations(text, question, original)
    # Only present when it is non-empty, so the happy-path frame keeps the shape the UI already reads.
    loose = _unverified_numbers(text, original)
    yield _frame(
        type="done",
        answer=text,
        citations=citations,
        usd=round(float(usage.get("usd", 0.0)), 6),
        tokensIn=int(usage.get("tokensIn", 0)),
        tokensSaved=saved,
        **({"unverifiedNumbers": loose} if loose else {}),
    )

"""The only LLM pass over the manual: 3 pages in, printed units out. Quotes are verbatim or they get dropped later."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from pydantic import BaseModel

from .. import llm
from ..config import settings
from ..models import Page

BATCH = 5
WORKERS = 32
MIN_CHARS = 40

SpecKind = Literal["torque", "capacity", "clearance", "pressure", "grade", "size", "electrical", "other"]


class SpecOut(BaseModel):
    name: str
    kind: SpecKind
    value: str
    unit: str | None
    quote: str


class PartOut(BaseModel):
    name: str
    spec: str
    quote: str


class UnitOut(BaseModel):
    title: str
    kind: Literal["procedure", "spec_table", "info"]
    pageStart: int
    pageEnd: int
    components: list[str]
    operations: list[str]
    quotes: list[str]
    specs: list[SpecOut]
    parts: list[PartOut]
    continuesPrevious: bool


class BatchOut(BaseModel):
    units: list[UnitOut]


class KeywordItem(BaseModel):
    index: int
    keywords: list[str]


class KeywordsOut(BaseModel):
    items: list[KeywordItem]


SYSTEM = """You index an official motorcycle manual so a rider can be sent straight to the printed page that answers them. You never write prose and you never invent text.

You get 1-3 consecutive pages, verbatim from the PDF text layer, plus the chapter and the headings the table of contents lists on them.

Return one unit per printed heading a rider or mechanic would act on:
- "procedure": a task with steps - check, change, adjust, clean, lubricate, remove, install, replace, charge, fill, top up, bleed, set - or how to work a control, switch, menu or lock.
- "spec_table": printed technical data - tightening torques, capacities, fluid grades, tire sizes and pressures, chain, fuses, bulbs, battery, dimensions, electrical values.
- "info": a short reference a rider looks up - warning and telltale lamp meanings, symbols, break-in, winter storage, jump starting, troubleshooting tables.

Return NO unit for: the cover, table of contents, index, warranty, consumer rights, emission and noise statements, general safety advice, protective clothing, means of representation, figures, dealer or marketing pages, and pages that are only a photo caption.

Rules, in order of importance:
1. quotes are copied character for character out of the page text above. Do not paraphrase, do not fix spelling, do not join two separated table cells with words of your own, do not expand abbreviations. A quote is one contiguous run of the printed text. Quote the decisive work steps and the lines carrying a quantity, in the order they are printed. Never quote a warning, caution, attention, note or hazard block, and never quote a bare label such as Condition, Preparatory work, Main work, Guideline or Info. At most 8, fewest that answer the task.
2. title is the printed heading exactly, minus its numbering prefix: "18.1 Checking the engine oil level" -> "Checking the engine oil level". Keep capitals if the heading is printed in capitals.
3. pageStart and pageEnd are the numbers from the "=== PAGE n ===" markers, never the number printed in the page corner.
4. continuesPrevious is true when the unit's own heading is not on these pages because it started earlier.
5. specs: only values that are printed. value is the number with its unit as printed ("12.5 Nm", "2.0 bar", "1.5 l"), unit is the unit alone, quote is the printed run that contains it.
6. parts: only consumables and replaceable items whose grade, size or number is printed here - oil, coolant, brake fluid, spark plug, fuse, bulb, tire, chain, battery, filter, fork oil, grease. name is what the manual calls it, with its printed capitalization. spec is the whole printed designation - grade, quantity, brand, part number, everything printed about it. quote is the printed run that contains it.
7. components are lowercase nouns ("engine oil", "oil filter", "front brake", "chain", "battery", "fuse", "front tire"). operations are lowercase verbs ("check", "change", "adjust", "remove", "charge", "top up").
Return an empty units list when there is nothing a rider would act on. Otherwise return every qualifying printed heading on these pages, even when the pages are crowded - a short unit with two quotes beats a missing one. Never more than 8 units."""

KEYWORDS_SYSTEM = """A rider with dirty hands asks a motorcycle manual a question out loud. For every numbered section title below, return the phrases that rider would actually say.

- 6 to 15 phrases per section, lowercase, no punctuation.
- Mix: the plain words of the title, the everyday name of the part, the everyday name of the job, common synonyms and slang, and the symptom that sends someone to this section.
- Examples for "Checking the engine oil level": engine oil level, check oil level, oil level, how much oil is in it, oil sight glass, check the oil, oil window, low oil, engine oil, oil dipstick.
- Never invent a part the section is not about. Never return a phrase longer than 5 words.
- Return one entry per index, every index exactly once."""


def _page_text(page: Page) -> str:
    return page.text.strip()


def batches(pages: list[Page], skip: set[int], size: int | None = None) -> list[list[Page]]:
    size = max(1, size or BATCH)
    out: list[list[Page]] = []
    for i in range(0, len(pages), size):
        window = [p for p in pages[i : i + size] if p.page not in skip and len(_page_text(p)) >= MIN_CHARS]
        if window:
            out.append(window)
    return out


def prompt(window: list[Page], manual_title: str, bike: str, chapter: str, headings: list[str]) -> str:
    head = [f"MANUAL: {manual_title} - {bike}"]
    if chapter:
        head.append(f"CHAPTER: {chapter}")
    if headings:
        head.append("HEADINGS THE TABLE OF CONTENTS LISTS HERE: " + "; ".join(headings))
    body = "\n".join(f"=== PAGE {p.page} ===\n{_page_text(p)}" for p in window)
    return "\n".join(head) + "\n\n" + body


def run_batches(prompts: list[str], on_done=None, model: str | None = None, workers: int | None = None) -> list[list[UnitOut]]:
    chosen = model or settings.model_struct

    def one(text: str) -> list[UnitOut]:
        for attempt in range(2):
            try:
                return llm.structured(
                    route="ingest.struct",
                    model=chosen,
                    schema=BatchOut,
                    system=SYSTEM,
                    user=text,
                ).units
            except Exception:
                if attempt:
                    return []
        return []

    results: list[list[UnitOut]] = [[] for _ in prompts]
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers or WORKERS)) as pool:
        futures = {pool.submit(one, text): i for i, text in enumerate(prompts)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            done += 1
            if on_done:
                on_done(done)
    return results


def keywords(titles: list[str], chunk: int = 12, model: str | None = None, on_done=None) -> list[list[str]]:
    """chunk is small on purpose: more calls run in parallel, so the pass is shorter and its progress is visible."""
    chosen = model or settings.model_struct
    out: list[list[str]] = [[] for _ in titles]
    chunks = [(i, titles[i : i + chunk]) for i in range(0, len(titles), chunk)]

    def one(job: tuple[int, list[str]]) -> tuple[int, KeywordsOut | None]:
        offset, group = job
        text = "\n".join(f"{n}. {t}" for n, t in enumerate(group))
        for attempt in range(2):
            try:
                return offset, llm.structured(
                    route="ingest.keywords",
                    model=chosen,
                    schema=KeywordsOut,
                    system=KEYWORDS_SYSTEM,
                    user=text,
                )
            except Exception:
                if attempt:
                    return offset, None
        return offset, None

    finished = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for offset, result in pool.map(one, chunks):
            finished += 1
            if on_done:
                on_done(finished, len(chunks))
            if not result:
                continue
            for item in result.items:
                idx = offset + item.index
                if 0 <= idx < len(titles):
                    out[idx] = [k.strip().lower() for k in item.keywords if k.strip()][:15]
    return out

"""Live retailer offers for one part of one manual, fetched on first click and cached in the store.

  offers(manual_id, part_id, bike) -> OffersResult

The fear this removes is "I bought the wrong part". So the query is built from what the manual actually
prints for THIS bike - the OEM number when there is one, else the spec string - plus make/model/year, and
the model is told that a shop listing that exact number fits even when the shop names other models.

Search: OpenAI Responses API with the built-in web_search tool (settings.model_offers). The model answers
in one pipe-delimited line per offer and Python parses the lines: a price that no regex can find in the
model's own text can never reach the UI, which is a stronger promise than asking a model for JSON and
hoping. A structured second pass runs only when the line format drifted.

Every surviving offer is then fetched (HEAD, GET on a 405) with a 2.5 s timeout, in parallel; a 404/410/5xx
or a dead host drops it. Offers carry `priceUsd` beside `price`/`currency` and arrive sorted by it, so a
list of eight shops in five currencies still reads cheapest-first without the browser doing arithmetic.

Cold latency. What a cold click used to cost a rider was 15.4 s: the request waited 4.5 s, returned zero
offers, and the Parts sheet asked again 10 s later. Measured where those seconds are, per search:

  model            first search call -> first offer line    whole answer    offers   usd
  gpt-5.6-terra x2            16.4 s                           21.8 s         13     .074
  gpt-5.6-terra x1            12.6 s                           16.7 s          9     .052
  gpt-5.6-luna  x1             4.1 s                            5.5 s          5     .023

So the cost is not the writing, it is the looking-up before the first word, and a second parallel leg of
the same model is exactly as slow as the first. Two things follow, and both are here:

1. The answer is read as it is written. The line-per-offer format was chosen to be parseable; streaming
   makes it parseable *early*. A completed line is parsed the moment its newline lands and its URL goes
   straight into the verification pool, so shops are being checked while the model writes the next line.
2. A cold click that someone is waiting on runs two legs at once: the fast model answers the deadline,
   the thorough one fills the cache. One search call each, so the bill for a cold part is what one
   two-call terra search used to cost, and the rider sees prices at ~6 s instead of 15.4 s.

The request leaves as soon as ENOUGH offers are verified; DEADLINE is the ceiling, not the wait. The
lookup thread keeps going, verifies the rest and writes the finished answer to the cache, so the next
click - or the /parts/offers/warm prefetch the Parts view fires on open - is a millisecond. `warm()`
skips the fast leg: nobody is waiting on a prefetch, so it pays for depth only.

Cache: store.put_offers(manual_id, part_id, result); a result under 24 h old is served as-is for $0.
A result that found nothing expires after an hour instead, so one bad search does not sit there all day.
"""

import os
import re
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from . import llm
from .config import settings
from .models import Bike, Link, Manual, Part
from .store import get_store

FRESH = 24 * 3600.0
FRESH_EMPTY = 3600.0
MAX_OFFERS = 15
VERIFY_TIMEOUT = 2.5
VERIFY_WORKERS = 16
SEARCH_CALLS = 1  # a second tool call measured +5 s and +$0.022 for four more offers; the fast leg is cheaper
CONTEXT_SIZE = "low"
# The leg that answers the deadline. It lives here rather than in config.py because it is not a choice
# about quality - settings.model_offers stays the model that decides what the cache ends up holding -
# it is a choice about which model starts writing first, and that is this module's problem.
FAST_MODEL = os.getenv("MODEL_OFFERS_FAST", "gpt-5.6-luna")
FAST_CALLS = 1
FAST_OFFERS = 8
# Two of them, because the fast model is fast but flaky: measured over five real parts it wrote a
# parseable offer line inside the deadline three times out of five. Two independent legs turn that
# into four out of five, and they are pointed at different corners of the trade so the second is
# not simply a re-roll of the first.
FAST_FOCUS = (
    "Start with the big catalogue retailers and marketplaces.",
    "Start with the vehicle maker's own online shop and the national dealer shops.",
)
# The ceiling on a cold click, not the wait: the request leaves the moment ENOUGH shops have been
# verified. ttm.js allows 25 s (OFFERS_MS) and the Parts sheet re-asks 10 s after an empty answer,
# so anything that returns real offers inside this beats a 15 s empty-then-retry by a mile.
DEADLINE = 7.5
ENOUGH = 2  # two verified shops is already a comparison; the rest arrives in the cache
WARM_PARTS = 12
WARM_WORKERS = 12

# Named in the prompt, not enforced as a filter: a hard allowed_domains filter measured five searches for
# one result, and the founder wants the local dealer shops the search surfaces too.
SHOPS = (
    "RevZilla, Partzilla, Amazon, eBay, FC-Moto, Louis, Polo, Rocky Mountain ATV/MC and the vehicle "
    "maker's own shop"
)

SYSTEM = (
    "You shop for one exact motorcycle part. Use web_search, then list what you found.\n"
    "The part number or specification comes from that bike's own manual, so a shop listing that exact "
    "part number or specification fits the bike even when the shop names other models.\n"
    "Answer with one line per offer and nothing else - no prose, no headings, no bullet points:\n"
    "SHOP | product title | price with currency | full product URL | variant | new or used | shipping | in stock\n"
    f"Prefer {SHOPS}; any real dealer shop the search surfaces is fine. "
    "List every variant separately, one line each - pack sizes, bottle sizes, lengths, brands, colours - "
    "and keep several lines from the same shop when they are different products or different variants. "
    "Only lines for a product page whose price and URL you actually saw - never a category page, never a "
    "search page, never a price you reconstructed. Write 'unknown' for a field the page does not state.\n"
    "Write each line the moment you have that one product; never hold them back to list them together. "
    "The first line is read and shown while you are still finding the rest."
)

# Hosts that carry prices but nothing to buy.
BLOCKED = (
    "reddit.com", "quora.com", "wikipedia.org", "wikimedia.org", "youtube.com", "youtu.be",
    "facebook.com", "instagram.com", "pinterest.", "tiktok.com", "x.com", "twitter.com",
    "google.", "bing.com", "duckduckgo.com", "yelp.com", "tripadvisor.", "alibaba.com",
    "idealo.", "geizhals.", "pricerunner.", "shopping.", "forum", "advrider.com", "wikihow.com",
    "shop.app",  # Shopify's proxy storefront: the shop's own product page is the one to link
)
SEARCH_PATHS = ("/search", "/catalogsearch", "/s?k=", "?q=", "&q=", "/find", "/c/", "/category")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# A shop that answers a bot with 401/403/405/429 is alive; only 404/410/5xx and a dead host are not.
WALLED = {401, 403, 405, 406, 429, 999}

CURRENCY_CODES = {
    "USD", "EUR", "GBP", "CHF", "CAD", "AUD", "JPY", "SEK", "NOK", "DKK", "PLN", "CZK",
    "INR", "NZD", "BRL", "MXN", "ZAR", "HUF", "RON", "TRY", "SGD", "HKD",
}
# Fixed rates. `price` and `currency` stay exactly as the shop printed them; `priceUsd` is this
# table's arithmetic, which is what a mixed-currency list can be sorted and compared on.
TO_USD = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.12, "CAD": 0.73, "AUD": 0.66, "NZD": 0.61,
    "JPY": 0.0067, "SEK": 0.095, "NOK": 0.092, "DKK": 0.145, "PLN": 0.25, "CZK": 0.043,
    "INR": 0.012, "BRL": 0.18, "MXN": 0.05, "ZAR": 0.055, "HUF": 0.0027, "RON": 0.22,
    "TRY": 0.029, "SGD": 0.74, "HKD": 0.128,
}
SYMBOLS = (
    (re.compile(r"\bUS\s?\$|\bUSD"), "USD"),
    (re.compile(r"\bCA\s?\$|\bCAD"), "CAD"),
    (re.compile(r"\bAU\s?\$|\bAUD"), "AUD"),
    (re.compile(r"\bNZ\s?\$|\bNZD"), "NZD"),
    (re.compile(r"R\$"), "BRL"),
    (re.compile(r"[€]|\bEUR"), "EUR"),
    (re.compile(r"[£]|\bGBP"), "GBP"),
    (re.compile(r"[¥]|\bJPY"), "JPY"),
    (re.compile(r"\bCHF|\bFr\.?\s?\d"), "CHF"),
    (re.compile(r"zł|\bPLN"), "PLN"),
    (re.compile(r"Kč|\bCZK"), "CZK"),
    (re.compile(r"\bkr\b"), "SEK"),
    (re.compile(r"\$"), "USD"),
)
NUMBER = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?")
UNKNOWN = {"", "unknown", "n/a", "na", "none", "not stated", "not shown", "not listed", "-", "--", "?"}
PIPE = re.compile(r"(?<!\\)\|")
BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
URL_IN = re.compile(r"https?://[^\s|)\]>,]+")
IN_STOCK = re.compile(r"\bin[ -]?stock|\bavailable\b|ships? (?:within|in|today|same)|\d+ in stock", re.I)
OUT_STOCK = re.compile(r"out of stock|sold out|unavailable|back ?order|pre-?order|discontinued", re.I)
# spec fragments that describe the job, not the product to buy
NOISE = re.compile(
    r"^\W*(?:\d[\d.,\s]*(?:bar|psi|kpa|nm|lbf|ft|km|mi|mm|cm|in\.?|°c|°f|h|min)\b"
    r"|max\.?\b|min\.?\b|approx\.?\b|per \w+|with filter change|load index|speed category"
    r"|battery voltage|nominal capacity|electrode gap)",
    re.I,
)


class Offer(BaseModel):
    retailer: str
    title: str
    price: float
    currency: str
    priceUsd: float = 0.0  # always computed here from TO_USD, never taken from the model
    url: str
    variant: str | None = None
    condition: str | None = None
    shipping: str | None = None
    inStock: bool | None = None


class OffersResult(BaseModel):
    manualId: str
    partId: str
    query: str
    offers: list[Offer]
    fetchedAt: float
    usd: float = 0.0
    # the manual's own search links: what the UI shows when the web search found nothing buyable
    links: list[Link] = []
    # false while the background thread is still verifying; the next call serves the finished answer
    complete: bool = True


class _Row(BaseModel):
    """Only used when the pipe format drifted: re-read the same text, invent nothing. Deliberately
    without priceUsd - a currency conversion is arithmetic, not something to ask a model for."""

    retailer: str
    title: str
    price: float
    currency: str
    url: str
    variant: str | None = None
    condition: str | None = None
    shipping: str | None = None
    inStock: bool | None = None


class _Rows(BaseModel):
    offers: list[_Row]


def in_usd(price: float, currency: str) -> float:
    return round(price * TO_USD.get(currency.upper(), 1.0), 2)


# --- query ---------------------------------------------------------------


def _fragments(spec: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[;,]|\s+-\s+", spec):
        frag = re.sub(r"\s+", " ", raw).strip(" .;,:-")
        if len(frag) > 1 and not NOISE.match(frag) and frag.lower() not in {f.lower() for f in out}:
            out.append(frag)
    return out


def build_query(part: Part, bike: Bike | None, hint: str | None = None) -> str:
    """OEM number when the manual printed one, else the spec it printed, else the catalogue's own
    searchHint for a part this manual never printed - plus the bike, always."""
    ride = f"{bike.make} {bike.model} {bike.year}" if bike else ""
    head = part.oem or " ".join(_fragments(part.spec))[:90] or (hint or "").strip() or part.name
    name = part.name if part.oem or part.name.lower() not in head.lower() else ""
    return re.sub(r"\s+", " ", f"{head} {name} {ride}").strip()


# --- parsing -------------------------------------------------------------


def parse_price(field: str) -> tuple[float, str] | None:
    """('US $1.234,56' -> 1234.56, 'USD'). No number or no currency means no offer."""
    text = field.replace(" ", " ").strip()
    found = NUMBER.search(text)
    if not found:
        return None
    raw = found.group(0).replace(" ", "").replace(" ", "")
    if "," in raw and "." in raw:  # the rightmost separator is the decimal point, either way round
        cut = max(raw.rfind(","), raw.rfind("."))
        raw = re.sub(r"[.,]", "", raw[:cut]) + "." + raw[cut + 1 :]
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        head, tail = raw.rsplit(sep, 1)
        # a lone group of exactly three digits is a thousands separator ("1,234"), one or two is cents
        raw = head.replace(sep, "") + ("" if len(tail) == 3 else ".") + tail
    try:
        price = float(raw)
    except ValueError:
        return None
    upper = text.upper()
    currency = next((c for c in CURRENCY_CODES if re.search(rf"\b{c}\b", upper)), None)
    if currency is None:
        currency = next((code for pattern, code in SYMBOLS if pattern.search(text)), None)
    if currency is None or not 0 < price < 100_000:
        return None
    return round(price, 2), currency


def _clean(value: str) -> str | None:
    text = re.sub(r"\s+", " ", value.replace("\\|", "|")).strip(" *_`\"")
    return None if text.lower() in UNKNOWN else text


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _buyable(url: str) -> bool:
    host, low = _host(url), url.lower()
    if not host or any(b in host for b in BLOCKED):
        return False
    path = urlparse(url).path
    if len(path) <= 1:
        return False
    return not any(s in low for s in SEARCH_PATHS)


def _retailer(field: str | None, url: str) -> str:
    name = _clean(field or "")
    if name and len(name) < 60:
        return name
    host = _host(url)
    return host.split(".")[0].replace("-", " ").title() if host else "Shop"


def parse_lines(text: str) -> list[Offer]:
    """SHOP | title | price | url | variant | condition | shipping | stock -> offers. Tolerant about
    markdown the model sprinkles on, strict about the two fields that matter: a price and a URL."""
    out: list[Offer] = []
    for raw in text.splitlines():
        line = MD_LINK.sub(r"\1 \2", BULLET.sub("", raw)).strip()
        if line.count("|") < 3 or re.fullmatch(r"[\s|:_-]+", line):
            continue
        fields = [f.strip() for f in PIPE.split(line.strip("| "))]
        if len(fields) < 4 or fields[0].lower() in {"shop", "retailer"}:
            continue
        found = next(((i, m) for i, f in enumerate(fields) if (m := URL_IN.search(f))), None)
        if found is None:
            continue
        url_at, url = found[0], found[1].group(0).rstrip(".,;)")
        # read the price out of any field but the title first: a title can carry a "save $10"
        order = [i for i in range(len(fields)) if i not in (url_at, 1)] + ([1] if url_at != 1 else [])
        money = next(((i, p) for i in order if (p := parse_price(fields[i]))), None)
        if money is None or not _buyable(url):
            continue
        price_at, (price, currency) = money
        taken = {url_at, price_at}
        shop_at = 0 if 0 not in taken else None
        title_at = next((i for i in range(len(fields)) if i not in taken and i != shop_at), None)
        rest = [f for i, f in enumerate(fields) if i > max(taken) and i != title_at]
        shipping = _clean(rest[2]) if len(rest) > 2 else None
        title = (_clean(fields[title_at]) if title_at is not None else None) or "Part"
        out.append(
            Offer(
                retailer=_retailer(fields[shop_at] if shop_at is not None else None, url),
                title=title[:120],
                price=price,
                currency=currency,
                priceUsd=in_usd(price, currency),
                url=url,
                variant=_clean(rest[0]) if rest else None,
                condition=_condition(rest[1] if len(rest) > 1 else ""),
                shipping=shipping[:80] if shipping else None,
                inStock=_stock(" ".join(rest[-2:])),
            )
        )
    return out


def _condition(value: str) -> str | None:
    low = (value or "").lower()
    for word in ("refurbished", "remanufactured", "used", "new"):
        if word in low:
            return word
    return None


def _stock(value: str) -> bool | None:
    if OUT_STOCK.search(value or ""):
        return False
    return True if IN_STOCK.search(value or "") else None


# --- verification --------------------------------------------------------


def alive(url: str, client: httpx.Client) -> bool:
    """HEAD, then GET when the shop does not do HEAD. A bot wall is not a dead page."""
    for method in ("HEAD", "GET"):
        try:
            code = client.request(method, url).status_code
        except Exception:
            return False
        if code < 400:
            return True
        if code not in WALLED:
            return False  # 404, 410, 5xx: nothing to buy there
        if method == "GET":
            return True  # the shop blocks robots, not riders
    return False


def verify(offers: list[Offer], on_live=None) -> list[Offer]:
    """Every URL at once. `on_live` is handed each offer the moment it checks out, so a caller that
    has to answer on a deadline can paint what is already verified instead of waiting for the slowest
    shop in the list."""
    if not offers:
        return []
    live: list[Offer] = []
    with httpx.Client(
        timeout=VERIFY_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": UA, "Accept": "text/html,*/*"},
    ) as client:
        with ThreadPoolExecutor(max_workers=min(VERIFY_WORKERS, len(offers))) as pool:
            checking = {pool.submit(alive, offer.url, client): offer for offer in offers}
            for future in as_completed(checking):
                offer = checking[future]
                if future.result():
                    live.append(offer)
                    if on_live:
                        on_live(offer)
    return live


class Checker:
    """Verification that can start before the search has finished. Offers are handed in one at a
    time as their line is parsed off the stream; each URL is checked on the pool straight away and
    the ones that answer are handed to `on_live`. `close()` waits for whatever is still in flight."""

    def __init__(self, on_live):
        self.on_live = on_live
        self.client = httpx.Client(
            timeout=VERIFY_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": UA, "Accept": "text/html,*/*"},
        )
        self.pool = ThreadPoolExecutor(max_workers=VERIFY_WORKERS, thread_name_prefix="verify")
        self.pending: list = []
        self.seen: set[str] = set()

    def add(self, offer: Offer) -> None:
        key = _key(offer)
        if key in self.seen or len(self.seen) >= MAX_OFFERS * 2:
            return
        self.seen.add(key)
        self.pending.append(self.pool.submit(self._check, offer))

    def _check(self, offer: Offer) -> None:
        if alive(offer.url, self.client):
            self.on_live(offer)

    def close(self) -> None:
        for future in self.pending:
            try:
                future.result(timeout=VERIFY_TIMEOUT * 2)
            except Exception:
                pass
        self.pool.shutdown(wait=False)
        self.client.close()


# --- assembly ------------------------------------------------------------


def _key(offer: Offer) -> str:
    """The whole URL, query string included: two brake fluids from one shop are two offers, and two
    sizes of the same bottle differ only in ?sku= ."""
    parsed = urlparse(offer.url.lower())
    return f"{_host(offer.url)}{parsed.path.rstrip('/')}?{parsed.query}"


def dedupe(offers: list[Offer]) -> list[Offer]:
    best: dict[str, Offer] = {}
    for offer in offers:
        key = _key(offer)
        current = best.get(key)
        if current is None or offer.priceUsd < current.priceUsd:
            best[key] = offer
    return list(best.values())


def _user(
    query: str, part: Part, bike: Bike | None, hint: str | None, want: int = MAX_OFFERS, focus: str = ""
) -> str:
    ride = f"{bike.make} {bike.model} {bike.year}" if bike else "this motorcycle"
    printed = part.oem or part.spec or hint or part.name
    return (
        f"Part: {part.name}\n"
        f"Printed in the manual: {printed}\n"
        f"Bike: {ride}\n"
        f"Search: {query}\n"
        f"Up to {want} offers, variants on their own lines."
        + (f"\n{focus}" if focus else "")
    )


def stream_lines(route: str, system: str, user: str, model: str, calls: int) -> Iterator[tuple[str, object]]:
    """The same search llm.web_search makes, read as it is written: yields ("delta", text) while
    the model writes and exactly one ("usd", float) when it stops.

    It reaches for llm.client() and llm.log() instead of llm.web_search() because the answer has to
    be parsed while it is still arriving - the whole point - and llm.py owns the non-streaming
    shape. Same tool, same effort, same cost accounting, same door; llm.web_search is still the
    fallback in search() below when a stream cannot be opened at all."""
    usage = None
    searches = 0
    with llm.client().responses.stream(
        model=model,
        instructions=system,
        input=[{"role": "user", "content": [llm.text_part(user)]}],
        tools=[{"type": "web_search", "search_context_size": CONTEXT_SIZE}],
        reasoning={"effort": "low"},
        max_tool_calls=calls,
    ) as events:
        for event in events:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    yield "delta", delta
            elif kind == "response.completed":
                response = getattr(event, "response", None)
                usage = getattr(response, "usage", None)
                searches = sum(
                    1
                    for item in (getattr(response, "output", None) or [])
                    if getattr(item, "type", "") == "web_search_call"
                )
    cost = 0.0
    if usage is not None:
        cost = llm.log(route, model, usage, extra_usd=searches * llm.WEB_SEARCH_CALL_USD)
    yield "usd", cost


def _read(route: str, user: str, on_offer, model: str, calls: int) -> tuple[list[Offer], float, str]:
    """Stream the answer and parse every line the moment its newline lands. A stream that cannot be
    opened at all - an SDK without it, a proxy that buffers - falls back to the plain request, which
    is the behaviour this had before and is only slower, never wrong."""
    offers: list[Offer] = []
    text = ""

    def take(chunk: str) -> None:
        for offer in parse_lines(chunk):
            offers.append(offer)
            if on_offer:
                on_offer(offer)

    try:
        cost = 0.0
        buffer = ""
        for kind, value in stream_lines(route, SYSTEM, user, model, calls):
            if kind == "usd":
                cost = float(value or 0.0)
                continue
            buffer += str(value)
            text += str(value)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                take(line)
        take(buffer)
        return offers, cost, text
    except Exception:
        text, cost = llm.web_search(route, model, SYSTEM, user, max_calls=calls)
        offers = []
        take(text)
        return offers, cost, text


def search(
    route: str,
    query: str,
    part: Part,
    bike: Bike | None,
    hint: str | None = None,
    on_offer=None,
    model: str | None = None,
    calls: int = SEARCH_CALLS,
    want: int = MAX_OFFERS,
    focus: str = "",
) -> tuple[list[Offer], float]:
    """`on_offer` is handed each offer the moment its line is complete, so verification of the
    first shop starts while the model is still writing the fifteenth."""
    model = model or settings.model_offers
    user = _user(query, part, bike, hint, want, focus)
    offers, cost, text = _read(route, user, on_offer, model, calls)
    if not offers and URL_IN.search(text or ""):
        # the format drifted but there is something there: one cheap structured re-read of the same text
        rows = llm.structured(
            f"{route}.extract",
            settings.model_struct,
            _Rows,
            "Turn each offer in this text into one object. Drop anything without both a number price and "
            "an http URL. Copy the values exactly as written; never invent one.",
            text,
        )
        offers = [
            Offer(**row.model_dump(), priceUsd=in_usd(row.price, row.currency))
            for row in rows.offers
            if _buyable(row.url) and 0 < row.price < 100_000
        ]
        for offer in offers:
            if on_offer:
                on_offer(offer)
    return offers, cost


# --- resolving the part ---------------------------------------------------


def _field(row, name: str):
    value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
    return value if value not in ("", None) else None


def _catalogue_row(rows, part_id: str) -> tuple[Part, str | None] | None:
    """A catalogue row - dict or model - as a Part plus its searchHint. A row the manual never
    printed has no spec and no page; the hint is what it is bought by."""
    row = next((r for r in (rows or []) if str(_field(r, "id") or "") == part_id), None)
    if row is None:
        return None
    return (
        Part(
            id=part_id,
            name=str(_field(row, "name") or part_id.replace("-", " ")),
            spec=str(_field(row, "spec") or ""),
            page=int(_field(row, "page") or 0),
            oem=_field(row, "oem"),
            links=[Link.model_validate(link) for link in (_field(row, "links") or [])],
        ),
        _field(row, "searchHint"),
    )


def _catalogue(manual_id: str, bike: Bike | None, part_id: str) -> tuple[Part, str | None] | None:
    """`GET /parts/catalog` lists parts this bike takes that the manual never prints, so an id from
    that list has to buy something here too. The catalogue module is another agent's; this reaches
    for it by name and stays a no-op until it lands, rather than importing it as a hard dependency."""
    try:
        from .parts import catalog as catalogue  # type: ignore[attr-defined]
    except Exception:
        return None
    for name in ("parts", "catalog", "rows"):
        fn = getattr(catalogue, name, None)
        if not callable(fn):
            continue
        for args in ((manual_id, bike.id if bike else None), (manual_id,)):
            try:
                rows = fn(*args)
            except TypeError:
                continue
            except Exception:
                return None
            if rows:
                return _catalogue_row(rows, part_id)
    return None


def resolve(manual: Manual, part_id: str, bike: Bike | None) -> tuple[Part, str | None]:
    """The manual's printed parts first, then the catalogue - whose rows carry a searchHint instead
    of a printed spec, because nothing about them was printed in this manual."""
    printed = next((p for p in manual.parts if p.id == part_id), None)
    if printed is not None:
        return printed, None
    found = _catalogue(manual.id, bike, part_id)
    if found is None:
        raise HTTPException(404, "part not found")
    return found


# --- one lookup, on its own thread ---------------------------------------

_POOL = ThreadPoolExecutor(max_workers=WARM_WORKERS + 4, thread_name_prefix="offers")
# The fast leg needs a thread of its own, and it must not be able to queue behind the thorough legs
# already holding _POOL - that would put the answer back behind the thing it is racing.
_SEARCH = ThreadPoolExecutor(max_workers=WARM_WORKERS + 4, thread_name_prefix="offers-fast")
_running: dict[tuple[str, str], "_Lookup"] = {}
_running_lock = threading.Lock()


class _Lookup:
    """One cold lookup. `snapshot()` is readable from the request thread at any moment, so the
    deadline can be answered with what is verified so far while this keeps running and caches the
    finished answer. Two clicks on the same part share one lookup, and one search bill."""

    def __init__(
        self,
        manual_id: str,
        part_id: str,
        part: Part,
        hint: str | None,
        bike: Bike | None,
        fast: bool = True,
    ):
        self.manual_id = manual_id
        self.part_id = part_id
        self.part = part
        self.hint = hint
        self.bike = bike
        self.fast = fast  # someone is waiting: pay for the legs that answer first
        self.query = build_query(part, bike, hint)
        self.legs: list = []
        # Decided here, not in run(): a second click can reach boost() before the thread starts.
        self.boosted = fast
        self.cost = 0.0
        self.finished = False
        self.live: list[Offer] = []
        self.lock = threading.Lock()
        self.done = threading.Event()  # for waiting on, never for deciding what is finished
        # ENOUGH verified shops is a good enough answer to send: the rest lands in the cache.
        self.ready = threading.Event()
        self.checker = Checker(self._keep)

    def _leg(self, route: str, model: str | None, calls: int, want: int, focus: str = "") -> list[Offer]:
        found, cost = search(
            route, self.query, self.part, self.bike, self.hint,
            on_offer=self.checker.add, model=model, calls=calls, want=want, focus=focus,
        )
        with self.lock:
            self.cost += cost
        return found

    def boost(self) -> None:
        """A click landed on a lookup a prefetch had already started. Nobody was waiting when it
        began, so it bought depth; someone is waiting now, so buy speed alongside it."""
        with self.lock:
            if self.boosted or self.done.is_set():
                return
            self.boosted = True
        self._spawn_fast()

    def _spawn_fast(self) -> None:
        legs = [
            _SEARCH.submit(self._leg, "offers.fast", FAST_MODEL, FAST_CALLS, FAST_OFFERS, focus)
            for focus in FAST_FOCUS
        ]
        with self.lock:
            self.legs += legs

    def _collect(self) -> list[Offer]:
        found: list[Offer] = []
        while True:
            with self.lock:
                if not self.legs:
                    return found
                leg = self.legs.pop()
            try:
                found += leg.result()
            except Exception:  # one flaky leg is not the answer
                pass

    def run(self) -> None:
        try:
            if self.fast:
                self._spawn_fast()
            found = self._leg("offers", None, SEARCH_CALLS, MAX_OFFERS)
            found += self._collect()
            self.checker.close()
            if not self.live and found:  # the non-streaming fallback answered in one piece
                verify(dedupe(found), on_live=self._keep)
            self.finished = True
            self._cache()
        except Exception:  # an outage is never cached: the next click tries again
            self.finished = False
        finally:
            self.checker.close()
            self.ready.set()
            self.done.set()
            with _running_lock:
                _running.pop((self.manual_id, self.part_id), None)

    def wait(self, seconds: float) -> None:
        """Back as soon as there is something worth painting, and never longer than `seconds`."""
        self.ready.wait(timeout=seconds)

    def _keep(self, offer: Offer) -> None:
        with self.lock:
            self.live.append(offer)
            enough = len(self.live) >= ENOUGH
        if enough:
            self.ready.set()

    def snapshot(self) -> list[Offer]:
        with self.lock:
            return sorted(self.live, key=lambda o: o.priceUsd)[:MAX_OFFERS]

    def result(self) -> OffersResult:
        complete = self.finished
        return OffersResult(
            manualId=self.manual_id,
            partId=self.part_id,
            query=self.query,
            offers=self.snapshot(),
            fetchedAt=time.time(),
            usd=round(self.cost, 6) if complete else 0.0,
            links=self.part.links,
            complete=complete,
        )

    def _cache(self) -> None:
        write = getattr(get_store(), "put_offers", None)
        if write:
            write(self.manual_id, self.part_id, self.result().model_dump())


def _start(
    manual_id: str, part_id: str, part: Part, hint: str | None, bike: Bike | None, fast: bool = True
) -> _Lookup:
    key = (manual_id, part_id)
    with _running_lock:
        current = _running.get(key)
        if current is not None:
            return current
        lookup = _Lookup(manual_id, part_id, part, hint, bike, fast)
        _running[key] = lookup
    _POOL.submit(lookup.run)
    return lookup


def cached(manual_id: str, part_id: str, part: Part) -> OffersResult | None:
    read = getattr(get_store(), "offers", None)
    raw = read(manual_id, part_id) if read else None
    if not raw:
        return None
    result = OffersResult.model_validate(raw)
    if not result.complete:
        return None
    age = time.time() - result.fetchedAt
    if age >= (FRESH if result.offers else FRESH_EMPTY):
        return None
    result = repair(manual_id, part_id, result)
    # the search links come from the manual, which may have been re-ingested since
    return result.model_copy(update={"usd": 0.0, "links": part.links})


def repair(manual_id: str, part_id: str, result: OffersResult) -> OffersResult:
    """Offers cached before priceUsd existed come back as 0.0 on every row, which sorts the whole
    sheet wrong and shows the rider nothing to compare. Recompute the conversion from the price and
    currency that were always there, re-sort, and write the mended answer back - the offers
    themselves are still good, so there is nothing here worth paying for a second search."""
    broken = [o for o in result.offers if o.priceUsd <= 0 < o.price]
    if not broken:
        return result
    for offer in broken:
        offer.priceUsd = in_usd(offer.price, offer.currency)
    mended = result.model_copy(update={"offers": sorted(result.offers, key=lambda o: o.priceUsd)})
    write = getattr(get_store(), "put_offers", None)
    if write:
        write(manual_id, part_id, mended.model_dump())  # fetchedAt is untouched: the TTL keeps running
    return mended


# --- the two calls --------------------------------------------------------


def offers(manual_id: str, part_id: str, bike: Bike | None) -> OffersResult:
    store = get_store()
    manual = store.manual(manual_id)
    if manual is None:
        raise HTTPException(404, "manual not found")
    part, hint = resolve(manual, part_id, bike)
    warm_hit = cached(manual_id, part_id, part)
    if warm_hit is not None:
        return warm_hit
    if bike is None and manual.bikeIds:
        bike = store.bike(manual.bikeIds[0])
    lookup = _start(manual_id, part_id, part, hint, bike)
    lookup.boost()  # a no-op unless a prefetch got here first without the fast legs
    lookup.wait(DEADLINE)
    return lookup.result()


def warm(manual_id: str, bike: Bike | None, part_ids: list[str] | None = None) -> dict:
    """Prefetch, so the Parts view can fill the cache while the rider is still reading the list and
    a click lands on a warm answer. Returns at once; the lookups run on the pool."""
    store = get_store()
    manual = store.manual(manual_id)
    if manual is None:
        raise HTTPException(404, "manual not found")
    if bike is None and manual.bikeIds:
        bike = store.bike(manual.bikeIds[0])
    wanted = [i for i in (part_ids or [p.id for p in manual.parts]) if i][:WARM_PARTS]
    queued, ready, unknown = [], [], []
    for part_id in wanted:
        try:
            part, hint = resolve(manual, part_id, bike)
        except HTTPException:
            unknown.append(part_id)
            continue
        if cached(manual_id, part_id, part) is not None:
            ready.append(part_id)
            continue
        _start(manual_id, part_id, part, hint, bike, fast=False)  # nobody is waiting on a prefetch
        queued.append(part_id)
    return {"manualId": manual_id, "queued": queued, "cached": ready, "unknown": unknown}

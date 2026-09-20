"""Live retailer offers for one part of one manual, fetched on first click and cached in the store.

  offers(manual_id, part_id, bike) -> OffersResult

The fear this removes is "I bought the wrong part". So the query is built from what the manual actually
prints for THIS bike - the OEM number when there is one, else the spec string - plus make/model/year, and
the model is told that a shop listing that exact number fits even when the shop names other models.

Search: OpenAI Responses API with the built-in web_search tool (settings.model_offers). The model answers
in one pipe-delimited line per offer and Python parses the lines: a price that no regex can find in the
model's own text can never reach the UI, which is a stronger promise than asking a model for JSON and
hoping. A structured second pass runs only when the line format drifted.

Every surviving offer is then fetched (HEAD, GET on a 405) with a 4 s timeout, in parallel; a 404/410/5xx
or a dead host drops it. Offers are sorted by price - across currencies by a static rate, for ordering only.

Cache: store.put_offers(manual_id, part_id, result); a result under 24 h old is served as-is for $0.
A result that found nothing expires after an hour instead, so one bad search does not sit there all day.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
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
MAX_OFFERS = 12
VERIFY_TIMEOUT = 4.0
VERIFY_WORKERS = 12
SEARCH_CALLS = 2

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
    "Only lines for a product page whose price and URL you actually saw - never a category page, never a "
    "search page, never a price you reconstructed. Write 'unknown' for a field the page does not state."
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
# Ordering only. Never shown, never used to rewrite a price.
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


class _Rows(BaseModel):
    """Only used when the pipe format drifted: re-read the same text, invent nothing."""

    offers: list[Offer]


# --- query ---------------------------------------------------------------


def _fragments(spec: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[;,]|\s+-\s+", spec):
        frag = re.sub(r"\s+", " ", raw).strip(" .;,:-")
        if len(frag) > 1 and not NOISE.match(frag) and frag.lower() not in {f.lower() for f in out}:
            out.append(frag)
    return out


def build_query(part: Part, bike: Bike | None) -> str:
    """OEM number when the manual printed one, else the spec the manual printed, plus the bike."""
    ride = f"{bike.make} {bike.model} {bike.year}" if bike else ""
    head = part.oem or " ".join(_fragments(part.spec))[:90] or part.name
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


def verify(offers: list[Offer]) -> list[Offer]:
    if not offers:
        return []
    with httpx.Client(
        timeout=VERIFY_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": UA, "Accept": "text/html,*/*"},
    ) as client:
        with ThreadPoolExecutor(max_workers=min(VERIFY_WORKERS, len(offers))) as pool:
            live = list(pool.map(lambda o: alive(o.url, client), offers))
    return [offer for offer, ok in zip(offers, live) if ok]


# --- assembly ------------------------------------------------------------


def _key(offer: Offer) -> str:
    parsed = urlparse(offer.url)
    return f"{_host(offer.url)}{parsed.path.rstrip('/')}"


def dedupe(offers: list[Offer]) -> list[Offer]:
    best: dict[str, Offer] = {}
    for offer in offers:
        key = _key(offer)
        current = best.get(key)
        if current is None or _usd(offer) < _usd(current):
            best[key] = offer
    return list(best.values())


def _usd(offer: Offer) -> float:
    return offer.price * TO_USD.get(offer.currency, 1.0)


def search(route: str, query: str, part: Part, bike: Bike | None) -> tuple[list[Offer], float]:
    ride = f"{bike.make} {bike.model} {bike.year}" if bike else "this motorcycle"
    printed = part.oem or part.spec
    user = (
        f"Part: {part.name}\n"
        f"Printed in the manual: {printed}\n"
        f"Bike: {ride}\n"
        f"Search: {query}\n"
        f"Up to {MAX_OFFERS} offers."
    )
    text, cost = llm.web_search(route, settings.model_offers, SYSTEM, user, max_calls=SEARCH_CALLS)
    offers = parse_lines(text)
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
        offers = [o for o in rows.offers if _buyable(o.url) and 0 < o.price < 100_000]
    return offers, cost


def _part(manual: Manual, part_id: str) -> Part:
    found = next((p for p in manual.parts if p.id == part_id), None)
    if found is None:
        raise HTTPException(404, "part not found")
    return found


def offers(manual_id: str, part_id: str, bike: Bike | None) -> OffersResult:
    store = get_store()
    manual = store.manual(manual_id)
    if manual is None:
        raise HTTPException(404, "manual not found")
    part = _part(manual, part_id)
    read = getattr(store, "offers", None)
    cached = read(manual_id, part_id) if read else None
    if cached:
        result = OffersResult.model_validate(cached)
        age = time.time() - result.fetchedAt
        if age < (FRESH if result.offers else FRESH_EMPTY):
            # the search links come from the manual, which may have been re-ingested since
            return result.model_copy(update={"usd": 0.0, "links": part.links})

    if bike is None and manual.bikeIds:
        bike = store.bike(manual.bikeIds[0])
    query = build_query(part, bike)
    try:
        found, cost = search("offers", query, part, bike)
    except Exception:  # a shopping trip that fails still owes the rider the manual's own search links
        return OffersResult(
            manualId=manual_id, partId=part_id, query=query, offers=[], fetchedAt=time.time(), links=part.links
        )
    live = sorted(dedupe(verify(found)), key=_usd)[:MAX_OFFERS]
    result = OffersResult(
        manualId=manual_id,
        partId=part_id,
        query=query,
        offers=live,
        fetchedAt=time.time(),
        usd=round(cost, 6),
        links=part.links,
    )
    write = getattr(store, "put_offers", None)
    if write:
        write(manual_id, part_id, result.model_dump())
    return result

"""Shared plumbing for the OEM adapters: one polite client, bounded concurrency, retries, slugs."""

from __future__ import annotations

import datetime
import logging
import os
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx

log = logging.getLogger("registry")

UA = os.getenv("REGISTRY_UA", "Mozilla/5.0 (compatible; trustthemanual/0.1; +https://trustthemanual.app/bot)")
GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
WORKERS = max(1, min(4, int(os.getenv("REGISTRY_WORKERS", "4"))))
RETRIES = max(1, int(os.getenv("REGISTRY_RETRIES", "3")))
TIMEOUT = httpx.Timeout(30.0, connect=15.0, read=120.0)
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

T = TypeVar("T")
R = TypeVar("R")


def langs() -> set[str] | None:
    """Languages kept by the multi-language portals. REGISTRY_LANGS='*' keeps every one."""
    raw = os.getenv("REGISTRY_LANGS", "en").strip()
    if raw == "*":
        return None
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def keep_lang(lang: str) -> bool:
    allowed = langs()
    return allowed is None or lang.lower() in allowed


@contextmanager
def client(ua: str = UA, headers: dict[str, str] | None = None) -> Iterator[httpx.Client]:
    head = {"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9", **(headers or {})}
    limits = httpx.Limits(max_connections=WORKERS, max_keepalive_connections=WORKERS)
    with httpx.Client(headers=head, timeout=TIMEOUT, follow_redirects=True, limits=limits) as c:
        yield c


class Throttle:
    """At most `rate` requests per second across every thread. For portals that answer 429 fast."""

    def __init__(self, rate: float):
        self.gap = 1.0 / rate
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.gap
        if start > now:
            time.sleep(start - now)


def _backoff(r: httpx.Response | None, attempt: int) -> float:
    if r is not None:
        for header in ("Retry-After", "retry-after-medium", "x-ratelimit-reset-short"):
            raw = r.headers.get(header)
            if raw and raw.strip().isdigit():
                return min(30.0, float(raw))
    return 0.5 * 2**attempt


def request(c: httpx.Client, method: str, url: str, throttle: Throttle | None = None, **kw: Any) -> httpx.Response | None:
    for attempt in range(RETRIES):
        got: httpx.Response | None = None
        try:
            if throttle:
                throttle.wait()
            got = c.request(method, url, **kw)
            if got.status_code in RETRY_STATUS:
                raise httpx.HTTPStatusError(str(got.status_code), request=got.request, response=got)
            got.raise_for_status()
            return got
        except Exception as exc:
            if attempt == RETRIES - 1:
                log.warning("%s %s failed: %s", method, url[:120], type(exc).__name__)
                return None
            time.sleep(_backoff(got, attempt))
    return None


def get_json(c: httpx.Client, url: str, **kw: Any) -> Any:
    r = request(c, "GET", url, **kw)
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        log.warning("not json: %s", url[:120])
        return None


def post_json(c: httpx.Client, url: str, **kw: Any) -> Any:
    r = request(c, "POST", url, **kw)
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        log.warning("not json: %s", url[:120])
        return None


def get_text(c: httpx.Client, url: str, **kw: Any) -> str | None:
    r = request(c, "GET", url, **kw)
    return r.text if r is not None else None


def pmap(fn: Callable[[T], R], items: Iterable[T]) -> Iterator[R]:
    """Run fn over items with at most WORKERS in flight; a failing item is logged and skipped."""
    items = list(items)
    if not items:
        return

    def guarded(item: T) -> R | None:
        try:
            return fn(item)
        except Exception as exc:
            log.warning("item failed (%r): %s", item, exc)
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for out in ex.map(guarded, items):
            if out is not None:
                yield out


def published_year(c: httpx.Client, url: str) -> int | None:
    """The year a file was published, from Last-Modified. For portals that print no model year."""
    r = request(c, "HEAD", url)
    raw = r.headers.get("Last-Modified") if r is not None else None
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).year
    except Exception:
        return None


def slug(*parts: object) -> str:
    raw = "-".join(str(p) for p in parts if p not in (None, ""))
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", raw.lower())).strip("-")


# 1885 is the Daimler Reitwagen; the top is two model years ahead of today, which is as far as any
# OEM publishes. Harley's archive really does reach back to 1903, so a 1950 floor would erase the
# oldest genuine manuals in the registry.
FIRST_MODEL_YEAR = 1885


def model_years() -> range:
    return range(FIRST_MODEL_YEAR, datetime.date.today().year + 3)


MODEL_YEARS = model_years()


def plausible_years(years: Iterable[object]) -> list[int]:
    """Keep only values that can be a model year. OEM portals do print impossible ones - Yamaha EU
    ships a truncated `201` alongside 2011-2016, Honda's Motopub answers `5019` for a `19YM` file -
    and an unclamped year mints a catalog vehicle nothing can ever match. Sorted and deduplicated."""
    out: set[int] = set()
    for y in years:
        try:
            value = int(str(y).strip())
        except (TypeError, ValueError):
            continue
        if value in MODEL_YEARS:
            out.add(value)
    return sorted(out)


def years_in(text: str) -> list[int]:
    return sorted({int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", text or "")})


def split_year(name: str) -> tuple[str, list[int]]:
    """'390 Duke 2024' -> ('390 Duke', [2024])."""
    m = re.search(r"\s((?:19|20)\d{2})\s*$", name or "")
    if m:
        return name[: m.start()].strip(), [int(m.group(1))]
    return (name or "").strip(), years_in(name)

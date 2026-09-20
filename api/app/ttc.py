"""The Token Company middleware (https://thetokencompany.com/docs). Owner: chat agent.

Sits between PDF page text and every LLM call (chat and the ask picker). It is a cost lever, never a
correctness lever: no key, a 5xx, a timeout or a junk body all return the original text unchanged, so
the worst case is that we pay full price for a correct answer.

HTTP contract verified live on 2026-09-20 (see api/docs/CHAT-RESEARCH.md):
    POST https://api.thetokencompany.com/v1/compress
    Authorization: Bearer ttc-...
    {"model": "bear-2", "input": "...", "compression_settings": {"aggressiveness": 0.3}}
 -> {"output": "...", "output_tokens": 58, "original_input_tokens": 100, "compression_time": 0.06}
The official SDK (`pip install the-token-company`) wraps exactly this one call; we use httpx, which the
API already depends on, rather than adding a package for a 12-line request.

Savings are not a CostEvent: a CostEvent is dollars spent at an OpenAI price, and compression spends
nothing and saves tokens. They live in an in-memory counter, per route, read back through stats() and
served by GET /cost/ttc (app/cost_ttc.py).
"""

import hashlib
import threading
import time
from collections import OrderedDict

import httpx

from .config import settings

URL = "https://api.thetokencompany.com/v1/compress"
MODEL = "bear-2"
# The API rejects 0.0 and 1.0; 0.8 deletes so much that a page stops being readable.
MIN_AGGRESSIVENESS = 0.1
MAX_AGGRESSIVENESS = 0.6
TIMEOUT = 8.0
ATTEMPTS = 3
BACKOFF = 0.3
# Measured, not documented: the API answers 429 {"detail":"Rate limit exceeded: 60 requests/minute"}.
# That is why chat compresses a whole prompt in ONE call instead of one call per page, and why a
# rider never waits out a long Retry-After: past this, the uncompressed text is the better answer.
MAX_RETRY_AFTER = 2.0
# Below this the round trip costs more latency than the tokens are worth.
MIN_CHARS = 400
CACHE_MAX = 2000

_cache: "OrderedDict[tuple[str, float], tuple[str, int, int]]" = OrderedDict()
_stats: dict[str, dict[str, float]] = {}
_lock = threading.RLock()


def _blank() -> dict[str, float]:
    return {"calls": 0, "cached": 0, "errors": 0, "tokensIn": 0, "tokensOut": 0, "tokensSaved": 0, "seconds": 0.0}


def _record(route: str, **delta: float) -> None:
    with _lock:
        bucket = _stats.setdefault(route, _blank())
        for key, value in delta.items():
            bucket[key] += value


def stats() -> dict[str, dict]:
    """Per-route counters plus a total. `savedPct` is of the tokens that actually reached the API."""
    with _lock:
        snapshot = {route: dict(bucket) for route, bucket in _stats.items()}
    total = _blank()
    for bucket in snapshot.values():
        for key, value in bucket.items():
            total[key] += value
    for bucket in (*snapshot.values(), total):
        tokens_in = bucket["tokensIn"]
        bucket["savedPct"] = round(100.0 * bucket["tokensSaved"] / tokens_in, 1) if tokens_in else 0.0
        bucket["seconds"] = round(bucket["seconds"], 3)
        for key in ("calls", "cached", "errors", "tokensIn", "tokensOut", "tokensSaved"):
            bucket[key] = int(bucket[key])
    return {"model": MODEL, "enabled": bool(settings.ttc_api_key), "byRoute": snapshot, "total": total}


def reset() -> None:
    with _lock:
        _cache.clear()
        _stats.clear()


def _cached(key: tuple[str, float]) -> tuple[str, int, int] | None:
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
        return hit


def _remember(key: tuple[str, float], value: tuple[str, int, int]) -> None:
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


class _RateLimited(Exception):
    def __init__(self, wait: float):
        super().__init__("429")
        self.wait = wait


def _retry_after(response) -> float:
    try:
        return min(MAX_RETRY_AFTER, max(0.0, float(response.headers.get("Retry-After", ""))))
    except (TypeError, ValueError):
        return BACKOFF


def _call(text: str, aggressiveness: float) -> tuple[str, int, int]:
    """One compress round trip. Raises on anything that is not a usable reply."""
    response = httpx.post(
        URL,
        headers={"Authorization": f"Bearer {settings.ttc_api_key}", "Content-Type": "application/json"},
        json={"model": MODEL, "input": text, "compression_settings": {"aggressiveness": aggressiveness}},
        timeout=TIMEOUT,
    )
    if response.status_code == 429:
        raise _RateLimited(_retry_after(response))
    response.raise_for_status()
    data = response.json()
    out = data.get("output")
    if not isinstance(out, str) or not out.strip():
        raise ValueError("ttc: empty output")
    original = int(data.get("original_input_tokens") or 0)
    produced = int(data.get("output_tokens") or 0)
    # A "compression" that grew the text is a bug on their side, not a saving on ours.
    if original and produced >= original:
        raise ValueError("ttc: no saving")
    return out, original, produced


def compress(text: str, aggressiveness: float = 0.3, route: str = "chat") -> tuple[str, int, int]:
    """(compressed_text, original_tokens, output_tokens). On any failure: (text, 0, 0) — never raises."""
    if not settings.ttc_api_key or not text or len(text) < MIN_CHARS:
        return text, 0, 0
    aggressiveness = min(MAX_AGGRESSIVENESS, max(MIN_AGGRESSIVENESS, round(float(aggressiveness), 2)))
    key = (hashlib.sha256(text.encode("utf-8")).hexdigest(), aggressiveness)

    hit = _cached(key)
    if hit is not None:
        # A cache hit still keeps those tokens out of the OpenAI prompt, so it counts as a saving.
        # `calls` stays the number of TTC round trips; `cached` is how many we did not have to make.
        _out, was, now = hit
        _record(f"ttc.{route}", cached=1, tokensIn=was, tokensOut=now, tokensSaved=max(0, was - now))
        return hit

    started = time.monotonic()
    for attempt in range(ATTEMPTS):
        try:
            out, original, produced = _call(text, aggressiveness)
        except Exception as exc:
            if attempt + 1 < ATTEMPTS:
                time.sleep(exc.wait if isinstance(exc, _RateLimited) else BACKOFF * (attempt + 1))
                continue
            _record(f"ttc.{route}", errors=1, seconds=time.monotonic() - started)
            return text, 0, 0
        result = (out, original, produced)
        _remember(key, result)
        _record(
            f"ttc.{route}",
            calls=1,
            tokensIn=original,
            tokensOut=produced,
            tokensSaved=max(0, original - produced),
            seconds=time.monotonic() - started,
        )
        return result
    return text, 0, 0

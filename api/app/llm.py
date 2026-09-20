"""One door to OpenAI. Every call goes through here so cost is logged per route."""

import base64
import time
from collections.abc import Iterator
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .config import settings
from .models import CostEvent
from .store import get_store

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens: input, cached input, output (developers.openai.com/api/docs/pricing, 2026-09-19)
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-6-astra": (10.0, 1.0, 50.0),
    "gpt-5.6-sol": (4.0, 0.4, 20.0),
    "gpt-5.6-terra": (2.0, 0.2, 12.0),
    "gpt-5.6-luna": (0.2, 0.02, 1.2),
    "gpt-5.4-mini": (0.75, 0.075, 4.5),
    "gpt-5.4-nano": (0.2, 0.02, 1.25),
    "gpt-5-mini": (0.25, 0.025, 2.0),
    "gpt-5-nano": (0.05, 0.005, 0.4),
    "text-embedding-3-small": (0.02, 0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.13, 0.0),
}

TOKENS_PER_PAGE = 800
NAIVE_MODEL = "gpt-6-astra"

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def usd(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    p_in, p_cached, p_out = PRICES.get(model, (0.0, 0.0, 0.0))
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1_000_000


def naive_usd(pages: int) -> float:
    tokens = pages * TOKENS_PER_PAGE
    p_in = PRICES[NAIVE_MODEL][0] * (2 if tokens > 272_000 else 1)
    return tokens * p_in / 1_000_000


def log(route: str, model: str, usage) -> float:
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    details = getattr(usage, "input_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
    cost = usd(model, input_tokens, cached, output_tokens)
    get_store().log_cost(
        CostEvent(
            ts=time.time(),
            route=route,
            model=model,
            inputTokens=input_tokens,
            cachedTokens=cached,
            outputTokens=output_tokens,
            usd=cost,
        )
    )
    return cost


def image_part(data: bytes, mime: str, detail: str = "auto") -> dict:
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{base64.b64encode(data).decode()}",
        "detail": detail,
    }


def text_part(text: str) -> dict:
    return {"type": "input_text", "text": text}


def structured(
    route: str,
    model: str,
    schema: type[T],
    system: str,
    user: str | list[dict],
    reasoning: str | None = None,
) -> T:
    """Structured output via the Responses API. `user` is a string or a list of input parts (text_part/image_part)."""
    content = user if isinstance(user, list) else [text_part(user)]
    kwargs: dict = {}
    if reasoning:
        kwargs["reasoning"] = {"effort": reasoning}
    response = client().responses.parse(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        text_format=schema,
        **kwargs,
    )
    log(route, model, response.usage)
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError(f"{route}: no parsed output")
    return parsed


def embed(route: str, texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    response = client().embeddings.create(model=model, input=texts)
    log(route, model, response.usage)
    return [d.embedding for d in response.data]


def stream(
    route: str,
    model: str,
    system: str,
    user: str,
    history: list[dict] | None = None,
    cache_key: str | None = None,
    reasoning: str | None = None,
    max_output_tokens: int | None = None,
) -> Iterator[tuple[str, object]]:
    """Streamed text from the Responses API.

    Yields ("delta", str) for every output chunk, then exactly one ("usage", dict) with the logged
    cost: {"usd", "tokensIn", "cachedTokens", "tokensOut"}. The system prompt is sent as `instructions`
    and `prompt_cache_key` is pinned per route+model so the long grounding prompt is served from
    OpenAI's prompt cache on the second turn onwards instead of being billed at full input price.
    """
    kwargs: dict = {}
    if reasoning:
        kwargs["reasoning"] = {"effort": reasoning}
    if max_output_tokens:
        kwargs["max_output_tokens"] = max_output_tokens
    messages = [*(history or []), {"role": "user", "content": [text_part(user)]}]
    usage = None
    with client().responses.stream(
        model=model,
        instructions=system,
        input=messages,
        prompt_cache_key=cache_key or f"{route}:{model}",
        **kwargs,
    ) as events:
        for event in events:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    yield "delta", delta
            elif kind == "response.completed":
                usage = getattr(getattr(event, "response", None), "usage", None)
    cost = log(route, model, usage) if usage is not None else 0.0
    details = getattr(usage, "input_tokens_details", None)
    yield "usage", {
        "usd": cost,
        "tokensIn": int(getattr(usage, "input_tokens", 0) or 0),
        "cachedTokens": int(getattr(details, "cached_tokens", 0) or 0) if details else 0,
        "tokensOut": int(getattr(usage, "output_tokens", 0) or 0),
    }

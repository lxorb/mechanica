"""The Token Company middleware, entirely offline.

conftest pops TTC_API_KEY but app.config also falls back to C:\\Users\\me\\agent-secrets\\ttc.txt, which
exists on the dev box and not in CI. Every test therefore sets settings.ttc_api_key explicitly instead of
trusting the environment, so the suite behaves the same in both places.
"""

import httpx
import pytest

from app import ttc
from app.config import settings

LONG = (
    "The engine oil level must be checked with the motorcycle standing upright on a level surface. "
    "Allow the engine to reach operating temperature before checking. The oil level must be between the "
    "MIN and MAX markings on the sight glass. If the oil level is below the MIN marking, add engine oil "
    "of the specified grade until the level reaches the MAX marking. Do not overfill. Engine oil "
    "capacity is 1.7 litres with a filter change. Tightening torque for the oil drain plug is 20 Nm. "
) * 2
SHORT_OUT = "engine oil level checked motorcycle upright level surface capacity 1.7 litres drain plug 20 Nm"


@pytest.fixture(autouse=True)
def clean():
    ttc.reset()
    yield
    ttc.reset()


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(settings, "ttc_api_key", None)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(settings, "ttc_api_key", "ttc-test-key")


class FakePost:
    """Stands in for httpx.post. Records every call so we can assert the wire contract and the cache."""

    def __init__(self, output=SHORT_OUT, original=200, produced=40, status=200):
        self.calls: list[dict] = []
        self.output, self.original, self.produced, self.status = output, original, produced, status

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}, "json": json or {}, "timeout": timeout})
        body = {
            "output": self.output,
            "output_tokens": self.produced,
            "original_input_tokens": self.original,
            "compression_time": 0.06,
        }
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))


def test_no_key_is_passthrough(no_key):
    out, before, after = ttc.compress(LONG, 0.3, "chat")
    assert (out, before, after) == (LONG, 0, 0)
    assert ttc.stats()["enabled"] is False
    assert ttc.stats()["total"]["tokensSaved"] == 0


def test_short_text_never_pays_for_a_round_trip(key, monkeypatch):
    post = FakePost()
    monkeypatch.setattr(httpx, "post", post)
    text = "chain slack 5 mm"
    assert ttc.compress(text, 0.3, "chat") == (text, 0, 0)
    assert post.calls == []


def test_compression_applied_and_wire_contract(key, monkeypatch):
    post = FakePost()
    monkeypatch.setattr(httpx, "post", post)

    out, before, after = ttc.compress(LONG, 0.3, "chat")
    assert out == SHORT_OUT
    assert (before, after) == (200, 40)

    assert len(post.calls) == 1
    call = post.calls[0]
    assert call["url"] == "https://api.thetokencompany.com/v1/compress"
    assert call["headers"]["Authorization"] == "Bearer ttc-test-key"
    assert call["json"]["model"] == "bear-2"
    assert call["json"]["input"] == LONG
    assert call["json"]["compression_settings"] == {"aggressiveness": 0.3}


def test_cached_by_text_and_aggressiveness(key, monkeypatch):
    post = FakePost()
    monkeypatch.setattr(httpx, "post", post)

    first = ttc.compress(LONG, 0.3, "chat")
    second = ttc.compress(LONG, 0.3, "chat")
    assert first == second
    assert len(post.calls) == 1, "same text at the same aggressiveness must not hit the API twice"

    ttc.compress(LONG, 0.5, "chat")
    assert len(post.calls) == 2, "a different aggressiveness is a different compression"

    ttc.compress(LONG + " Extra printed line.", 0.3, "chat")
    assert len(post.calls) == 3

    stats = ttc.stats()["byRoute"]["ttc.chat"]
    assert stats["calls"] == 3
    assert stats["cached"] == 1


def test_aggressiveness_is_clamped_into_the_api_band(key, monkeypatch):
    post = FakePost()
    monkeypatch.setattr(httpx, "post", post)
    ttc.compress(LONG, 0.0, "chat")
    ttc.compress(LONG, 1.0, "chat")
    sent = [c["json"]["compression_settings"]["aggressiveness"] for c in post.calls]
    assert sent == [ttc.MIN_AGGRESSIVENESS, ttc.MAX_AGGRESSIVENESS]


@pytest.mark.parametrize(
    "post",
    [
        FakePost(status=500),
        FakePost(output=""),
        FakePost(output=SHORT_OUT, original=100, produced=140),  # "compressed" bigger than the input
    ],
    ids=["http-500", "empty-output", "grew"],
)
def test_any_bad_reply_falls_back_to_the_original_text(key, monkeypatch, post):
    monkeypatch.setattr(httpx, "post", post)
    assert ttc.compress(LONG, 0.3, "chat") == (LONG, 0, 0)
    assert ttc.stats()["byRoute"]["ttc.chat"]["errors"] == 1


def test_transport_error_retries_then_falls_back(key, monkeypatch):
    attempts = []

    def boom(*args, **kwargs):
        attempts.append(1)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(ttc, "BACKOFF", 0.0)
    assert ttc.compress(LONG, 0.3, "chat") == (LONG, 0, 0)
    assert len(attempts) == ttc.ATTEMPTS


def test_stats_report_savings_per_route(key, monkeypatch):
    monkeypatch.setattr(httpx, "post", FakePost())
    ttc.compress(LONG, 0.3, "chat")
    ttc.compress(LONG, 0.3, "picker")

    stats = ttc.stats()
    assert stats["enabled"] is True
    assert stats["model"] == "bear-2"
    assert set(stats["byRoute"]) == {"ttc.chat", "ttc.picker"}
    assert stats["byRoute"]["ttc.chat"]["tokensSaved"] == 160
    assert stats["total"]["tokensSaved"] == 320
    assert stats["total"]["tokensIn"] == 400
    assert stats["total"]["savedPct"] == 80.0


def test_cost_ttc_route(client, key, monkeypatch):
    monkeypatch.setattr(httpx, "post", FakePost())
    ttc.compress(LONG, 0.3, "chat")
    body = client.get("/cost/ttc").json()
    assert body["total"]["tokensSaved"] == 160
    assert body["byRoute"]["ttc.chat"]["calls"] == 1

"""Offline contracts for the LLM gateway: requests, streamed events, and cost logging.

SDK calls and the cost store are replaced locally; no test writes application data.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from pydantic import BaseModel

from app import llm
from app.models import CostEvent

MODEL = "gpt-5.6-terra"
TOKEN_COST = 0.00524  # 800 fresh + 200 cached input tokens, 300 output tokens.


class Answer(BaseModel):
    answer: str


@pytest.fixture(autouse=True)
def cost_events(monkeypatch):
    """Keep both the singleton client and every cost write isolated to one test."""
    events = []
    store = SimpleNamespace(log_cost=events.append)
    monkeypatch.setattr(llm, "get_store", lambda: store)
    monkeypatch.setattr(llm, "time", SimpleNamespace(time=lambda: 1234.5))
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm, "OpenAI", Mock(side_effect=AssertionError("unexpected SDK construction")))
    return events


@pytest.fixture
def sdk(monkeypatch):
    fake = SimpleNamespace(
        responses=SimpleNamespace(parse=Mock(), create=Mock(), stream=Mock()),
        embeddings=SimpleNamespace(create=Mock()),
    )
    monkeypatch.setattr(llm, "_client", fake)
    return fake


@pytest.fixture
def usage():
    return SimpleNamespace(
        input_tokens=1000,
        input_tokens_details=SimpleNamespace(cached_tokens=200),
        output_tokens=300,
    )


def stream_context(sdk, events):
    context = MagicMock(spec=["__enter__", "__exit__"])
    context.__enter__.return_value = iter(events)
    context.__exit__.return_value = False
    sdk.responses.stream.return_value = context
    return context


def test_client_is_created_lazily_and_reused(monkeypatch):
    instance = object()
    constructor = Mock(return_value=instance)
    monkeypatch.setattr(llm, "OpenAI", constructor)
    monkeypatch.setattr(llm.settings, "openai_api_key", "sk-llm-test")

    constructor.assert_not_called()
    assert llm.client() is instance
    assert llm.client() is instance
    constructor.assert_called_once_with(api_key="sk-llm-test")


def test_failed_client_construction_can_be_retried(monkeypatch):
    instance = object()
    constructor = Mock(side_effect=[RuntimeError("configuration error"), instance])
    monkeypatch.setattr(llm, "OpenAI", constructor)

    with pytest.raises(RuntimeError, match="configuration error"):
        llm.client()

    assert llm._client is None
    assert llm.client() is instance
    assert constructor.call_count == 2


@pytest.mark.parametrize(
    "model,tokens_in,cached,tokens_out,expected",
    [
        (MODEL, 1000, 200, 300, 0.00524),
        ("gpt-6-astra", 1000, 200, 300, 0.0232),
        ("gpt-5.6-luna", 1000, 200, 300, 0.000524),
        ("text-embedding-3-small", 1000, 0, 0, 0.00002),
        ("text-embedding-3-large", 1000, 0, 0, 0.00013),
        (MODEL, 1000, 0, 0, 0.002),
        (MODEL, 1000, 1000, 0, 0.0002),
        (MODEL, 0, 0, 1000, 0.012),
        (MODEL, 100, 200, 0, 0.00004),  # Fresh tokens cannot become negative.
        (MODEL, 0, 0, 0, 0.0),
        ("unpriced-model", 1000, 200, 300, 0.0),
    ],
)
def test_usd_prices_fresh_cached_and_output_tokens(model, tokens_in, cached, tokens_out, expected):
    assert llm.usd(model, tokens_in, cached, tokens_out) == pytest.approx(expected)


@pytest.mark.parametrize(
    "pages,expected",
    [(0, 0.0), (1, 0.008), (339, 2.712), (340, 2.72), (341, 5.456)],
)
def test_naive_usd_doubles_the_input_rate_only_above_272000_tokens(pages, expected):
    assert llm.naive_usd(pages) == pytest.approx(expected)


def test_log_records_token_counts_route_model_timestamp_and_tool_fee(cost_events, usage):
    cost = llm.log("offers", MODEL, usage, extra_usd=0.02)

    assert cost == pytest.approx(0.02524)
    assert len(cost_events) == 1
    assert isinstance(cost_events[0], CostEvent)
    assert cost_events[0].model_dump() == {
        "ts": 1234.5,
        "route": "offers",
        "model": MODEL,
        "inputTokens": 1000,
        "cachedTokens": 200,
        "outputTokens": 300,
        "usd": pytest.approx(cost),
    }


@pytest.mark.parametrize(
    "value,expected_counts,expected_cost",
    [
        pytest.param(None, (0, 0, 0), 0.0, id="no-usage"),
        pytest.param(SimpleNamespace(), (0, 0, 0), 0.0, id="missing-counts"),
        pytest.param(
            SimpleNamespace(input_tokens=None, output_tokens=None, input_tokens_details=None),
            (0, 0, 0), 0.0, id="null-counts",
        ),
        pytest.param(
            SimpleNamespace(input_tokens=1000, output_tokens=300),
            (1000, 0, 300), 0.0056, id="missing-details",
        ),
        pytest.param(
            SimpleNamespace(input_tokens=1000, input_tokens_details=SimpleNamespace()),
            (1000, 0, 0), 0.002, id="missing-cached-count",
        ),
        pytest.param(
            SimpleNamespace(input_tokens=1000, input_tokens_details=SimpleNamespace(cached_tokens=None)),
            (1000, 0, 0), 0.002, id="null-cached-count",
        ),
        pytest.param(
            SimpleNamespace(
                input_tokens="1000", output_tokens="300",
                input_tokens_details=SimpleNamespace(cached_tokens="200"),
            ),
            (1000, 200, 300), TOKEN_COST, id="numeric-strings",
        ),
    ],
)
def test_log_normalizes_optional_usage_fields(cost_events, value, expected_counts, expected_cost):
    assert llm.log("chat", MODEL, value) == pytest.approx(expected_cost)
    assert len(cost_events) == 1
    event = cost_events[0]
    assert (event.inputTokens, event.cachedTokens, event.outputTokens) == expected_counts
    assert event.usd == pytest.approx(expected_cost)


def test_log_keeps_tool_fees_without_usage_or_known_token_prices(cost_events):
    assert llm.log("offers", "unpriced-model", None, extra_usd=0.03) == pytest.approx(0.03)
    assert len(cost_events) == 1
    assert cost_events[0].usd == pytest.approx(0.03)


@pytest.mark.parametrize("text", ["", "Torque: 48 Nm\nCheck again.", "Gr\u00f6sse \U0001f527"])
def test_text_part_preserves_the_text(text):
    assert llm.text_part(text) == {"type": "input_text", "text": text}


@pytest.mark.parametrize(
    "data,mime,options,encoded,detail",
    [
        (b"\x00\xff\x10", "image/png", {}, "AP8Q", "auto"),
        (b"hello", "image/jpeg", {"detail": "high"}, "aGVsbG8=", "high"),
        (b"", "image/webp", {"detail": "low"}, "", "low"),
    ],
)
def test_image_part_builds_a_base64_data_url(data, mime, options, encoded, detail):
    assert llm.image_part(data, mime, **options) == {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": detail,
    }


@pytest.mark.parametrize("reasoning", [None, "", "high"])
def test_structured_sends_schema_and_optional_reasoning(sdk, cost_events, usage, reasoning):
    parsed = Answer(answer="48 Nm")
    sdk.responses.parse.return_value = SimpleNamespace(output_parsed=parsed, usage=usage)

    result = llm.structured("spec", MODEL, Answer, "Use the manual.", "Axle torque?", reasoning=reasoning)

    assert result is parsed
    expected = {
        "model": MODEL,
        "input": [
            {"role": "system", "content": "Use the manual."},
            {"role": "user", "content": [{"type": "input_text", "text": "Axle torque?"}]},
        ],
        "text_format": Answer,
    }
    if reasoning:
        expected["reasoning"] = {"effort": reasoning}
    sdk.responses.parse.assert_called_once_with(**expected)
    assert len(cost_events) == 1
    assert (cost_events[0].route, cost_events[0].model) == ("spec", MODEL)
    assert cost_events[0].usd == pytest.approx(TOKEN_COST)


@pytest.mark.parametrize("parts", [[], [
    {"type": "input_text", "text": "Read this plate."},
    {"type": "input_image", "image_url": "data:image/png;base64,AP8Q", "detail": "high"},
]])
def test_structured_passes_multimodal_parts_without_wrapping_or_mutating(sdk, usage, parts):
    original = deepcopy(parts)
    parsed = Answer(answer="390")
    sdk.responses.parse.return_value = SimpleNamespace(output_parsed=parsed, usage=usage)

    assert llm.structured("vision", MODEL, Answer, "Read the image.", parts) is parsed

    sent = sdk.responses.parse.call_args.kwargs["input"][1]["content"]
    assert sent == original
    assert parts == original


def test_structured_logs_paid_usage_even_when_parsed_output_is_missing(sdk, cost_events, usage):
    sdk.responses.parse.return_value = SimpleNamespace(output_parsed=None, usage=usage)

    with pytest.raises(RuntimeError, match="^spec: no parsed output$"):
        llm.structured("spec", MODEL, Answer, "Use the manual.", "Axle torque?")

    assert len(cost_events) == 1
    assert cost_events[0].usd == pytest.approx(TOKEN_COST)


@pytest.mark.parametrize("calls", [0, 1, 3])
def test_web_search_bills_actual_search_calls_and_sends_default_options(sdk, cost_events, usage, calls):
    output = [SimpleNamespace(type="message"), SimpleNamespace(), {"type": "web_search_call"}]
    output.extend(SimpleNamespace(type="web_search_call") for _ in range(calls))
    sdk.responses.create.return_value = SimpleNamespace(output=output, output_text="Found a part.", usage=usage)

    text, cost = llm.web_search("offers", MODEL, "Find a supplier.", "Brake pads")

    assert text == "Found a part."
    assert cost == pytest.approx(TOKEN_COST + calls * 0.01)
    sdk.responses.create.assert_called_once_with(
        model=MODEL,
        instructions="Find a supplier.",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "Brake pads"}]}],
        tools=[{"type": "web_search", "search_context_size": "low"}],
        reasoning={"effort": "low"},
        max_tool_calls=2,
    )
    assert len(cost_events) == 1
    assert (cost_events[0].route, cost_events[0].model) == ("offers", MODEL)
    assert cost_events[0].usd == pytest.approx(cost)


@pytest.mark.parametrize("domains", [None, [], ["parts.example", "shop.example"]])
def test_web_search_forwards_options_and_only_adds_nonempty_domain_filters(sdk, usage, domains):
    sdk.responses.create.return_value = SimpleNamespace(output=[], output_text="Found.", usage=usage)
    original = deepcopy(domains)

    llm.web_search(
        "offers", MODEL, "Find a supplier.", "Brake pads",
        context_size="high", max_calls=4, reasoning="medium", allowed_domains=domains,
    )

    kwargs = sdk.responses.create.call_args.kwargs
    tool = {"type": "web_search", "search_context_size": "high"}
    if domains:
        tool["filters"] = {"allowed_domains": domains}
    assert kwargs["tools"] == [tool]
    assert kwargs["max_tool_calls"] == 4
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert domains == original


@pytest.mark.parametrize("output_text", [None, ""])
def test_web_search_normalizes_empty_text_and_still_bills_tools(sdk, cost_events, output_text):
    sdk.responses.create.return_value = SimpleNamespace(
        output=[SimpleNamespace(type="web_search_call")], output_text=output_text, usage=None,
    )

    text, cost = llm.web_search("offers", MODEL, "Find a supplier.", "Brake pads")

    assert text == ""
    assert cost == pytest.approx(0.01)
    assert len(cost_events) == 1
    assert cost_events[0].usd == pytest.approx(0.01)


@pytest.mark.parametrize("model", [None, "text-embedding-3-large"])
def test_embed_preserves_vector_order_and_passes_usage_to_logger(sdk, monkeypatch, model):
    texts = ["chain tension", "axle torque"]
    vectors = [[0.1, -0.2], [0.3, 0.4]]
    # Embeddings have a different usage shape; verify it reaches the shared logger intact.
    embedding_usage = SimpleNamespace(prompt_tokens=12, total_tokens=12)
    sdk.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=vector) for vector in vectors], usage=embedding_usage,
    )
    logger = Mock(return_value=0.0)
    monkeypatch.setattr(llm, "log", logger)
    options = {"model": model} if model else {}

    assert llm.embed("index", texts, **options) == vectors

    expected_model = model or "text-embedding-3-small"
    sdk.embeddings.create.assert_called_once_with(model=expected_model, input=texts)
    logger.assert_called_once_with("index", expected_model, embedding_usage)
    assert texts == ["chain tension", "axle torque"]


def test_embed_accepts_an_empty_embedding_result(sdk, cost_events):
    sdk.embeddings.create.return_value = SimpleNamespace(data=[], usage=None)

    assert llm.embed("index", []) == []

    sdk.embeddings.create.assert_called_once_with(model="text-embedding-3-small", input=[])
    assert len(cost_events) == 1
    assert cost_events[0].usd == 0.0


def test_stream_yields_nonempty_text_then_one_usage_event(sdk, cost_events, usage):
    context = stream_context(sdk, [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(),
        SimpleNamespace(type="response.output_text.delta", delta="Torque "),
        SimpleNamespace(type="response.output_text.delta", delta=""),
        SimpleNamespace(type="response.output_text.delta", delta=None),
        SimpleNamespace(type="response.output_text.delta"),
        SimpleNamespace(type="response.refusal.delta", delta="not answer text"),
        SimpleNamespace(type="response.output_text.delta", delta="48 Nm."),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage)),
    ])
    stream = llm.stream("chat", MODEL, "Use the manual.", "Axle torque?")
    sdk.responses.stream.assert_not_called()

    assert next(stream) == ("delta", "Torque ")
    assert cost_events == []
    assert next(stream) == ("delta", "48 Nm.")
    assert cost_events == []
    context.__exit__.assert_not_called()
    assert next(stream) == ("usage", {
        "usd": pytest.approx(TOKEN_COST), "tokensIn": 1000, "cachedTokens": 200, "tokensOut": 300,
    })
    assert list(stream) == []
    context.__enter__.assert_called_once_with()
    context.__exit__.assert_called_once_with(None, None, None)
    sdk.responses.stream.assert_called_once_with(
        model=MODEL,
        instructions="Use the manual.",
        input=[{"role": "user", "content": [{"type": "input_text", "text": "Axle torque?"}]}],
        prompt_cache_key=f"chat:{MODEL}",
    )
    assert len(cost_events) == 1
    assert (cost_events[0].route, cost_events[0].model) == ("chat", MODEL)
    assert cost_events[0].usd == pytest.approx(TOKEN_COST)


def test_stream_forwards_history_and_explicit_options_without_mutation(sdk):
    history = [{"role": "user", "content": "Which axle?"}, {"role": "assistant", "content": "Rear."}]
    original = deepcopy(history)
    stream_context(sdk, [])

    list(llm.stream(
        "chat", MODEL, "Use the manual.", "Torque?", history=history,
        cache_key="manual:rear-axle", reasoning="low", max_output_tokens=64,
    ))

    sdk.responses.stream.assert_called_once_with(
        model=MODEL,
        instructions="Use the manual.",
        input=[*original, {"role": "user", "content": [{"type": "input_text", "text": "Torque?"}]}],
        prompt_cache_key="manual:rear-axle",
        reasoning={"effort": "low"},
        max_output_tokens=64,
    )
    assert history == original


def test_stream_omits_empty_options_and_uses_the_default_cache_key(sdk):
    stream_context(sdk, [])

    list(llm.stream("chat", MODEL, "Manual", "Question", history=[], cache_key="", reasoning="", max_output_tokens=0))

    kwargs = sdk.responses.stream.call_args.kwargs
    assert kwargs["prompt_cache_key"] == f"chat:{MODEL}"
    assert "reasoning" not in kwargs
    assert "max_output_tokens" not in kwargs


@pytest.mark.parametrize("events", [
    pytest.param([], id="empty-stream"),
    pytest.param([SimpleNamespace(type="response.completed")], id="no-response"),
    pytest.param([SimpleNamespace(type="response.completed", response=SimpleNamespace())], id="no-usage"),
    pytest.param([
        SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None)),
    ], id="null-usage"),
])
def test_stream_without_usage_emits_zero_totals_without_logging(sdk, cost_events, events):
    stream_context(sdk, [SimpleNamespace(type="response.output_text.delta", delta="Answer"), *events])

    assert list(llm.stream("chat", MODEL, "Manual", "Question")) == [
        ("delta", "Answer"),
        ("usage", {"usd": 0.0, "tokensIn": 0, "cachedTokens": 0, "tokensOut": 0}),
    ]
    assert cost_events == []


@pytest.mark.parametrize("details", [None, SimpleNamespace(), SimpleNamespace(cached_tokens=None)])
def test_stream_normalizes_optional_usage_counts(sdk, cost_events, details):
    usage = SimpleNamespace(input_tokens="1000", output_tokens=None, input_tokens_details=details)
    stream_context(sdk, [SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=usage))])

    assert list(llm.stream("chat", MODEL, "Manual", "Question")) == [
        ("usage", {"usd": pytest.approx(0.002), "tokensIn": 1000, "cachedTokens": 0, "tokensOut": 0}),
    ]
    assert len(cost_events) == 1
    assert cost_events[0].usd == pytest.approx(0.002)


@pytest.mark.parametrize("operation", ["structured", "web_search", "embed", "stream"])
def test_sdk_errors_propagate_without_logging_fabricated_usage(sdk, cost_events, operation):
    error = RuntimeError("SDK unavailable")
    sdk.responses.parse.side_effect = error
    sdk.responses.create.side_effect = error
    sdk.embeddings.create.side_effect = error
    sdk.responses.stream.side_effect = error
    calls = {
        "structured": lambda: llm.structured("spec", MODEL, Answer, "Manual", "Question"),
        "web_search": lambda: llm.web_search("offers", MODEL, "Find parts", "Brake pads"),
        "embed": lambda: llm.embed("index", ["chain"]),
        "stream": lambda: list(llm.stream("chat", MODEL, "Manual", "Question")),
    }

    with pytest.raises(RuntimeError, match="SDK unavailable") as raised:
        calls[operation]()

    assert raised.value is error
    assert cost_events == []


def test_stream_iteration_failure_closes_context_and_preserves_the_error(sdk, cost_events):
    error = RuntimeError("stream disconnected")

    def interrupted():
        yield SimpleNamespace(type="response.output_text.delta", delta="Partial answer")
        raise error

    context = stream_context(sdk, interrupted())
    stream = llm.stream("chat", MODEL, "Manual", "Question")
    assert next(stream) == ("delta", "Partial answer")

    with pytest.raises(RuntimeError, match="stream disconnected") as raised:
        next(stream)

    assert raised.value is error
    assert list(stream) == []
    context.__exit__.assert_called_once()
    assert context.__exit__.call_args.args[:2] == (RuntimeError, error)
    assert cost_events == []

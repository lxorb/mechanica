"""Grounded chat over one manual. No network: the OpenAI stream and the router are monkeypatched,
retrieval and page text are the real seeded KTM 390 Duke manual.
"""

import json
import re

import pytest

from app import chat
from app.ask import Route
from app.config import settings
from app.store import get_store

from conftest import BMW, KTM


def frames(stream) -> list[dict]:
    """Parse the SSE wire format back into frames, asserting the framing itself."""
    out = []
    for chunk in stream:
        assert chunk.startswith("data: "), chunk
        assert chunk.endswith("\n\n"), chunk
        out.append(json.loads(chunk[len("data: ") : -2]))
    return out


def offered_pages(user: str) -> list[int]:
    return [int(n) for n in re.findall(r"^Page (\d+):$", user, flags=re.M)]


def fake_stream(answer_for, usage=None):
    """Stands in for llm.stream. `answer_for(user_prompt)` builds the answer; it is emitted in chunks."""
    seen: dict = {}

    def stream(route, model, system, user, history=None, cache_key=None, reasoning=None, max_output_tokens=None):
        seen.update(route=route, model=model, system=system, user=user, history=history, cache_key=cache_key)
        text = answer_for(user)
        for i in range(0, len(text), 7):
            yield "delta", text[i : i + 7]
        yield "usage", usage or {"usd": 0.0012, "tokensIn": 3200, "cachedTokens": 2048, "tokensOut": 90}

    stream.seen = seen
    return stream


@pytest.fixture(autouse=True)
def stub_router(monkeypatch):
    """The router is app/ask.py's own LLM call; chat is tested against retrieval, not against it."""

    def route(query: str) -> Route:
        return Route(intent="procedure", components=[], queries=[query], specName=None, specKind=None)

    monkeypatch.setattr(chat.ask_mod, "_route", route)


@pytest.fixture(autouse=True)
def no_compression(monkeypatch):
    """TTC has its own suite; here passages must reach the prompt unchanged so quotes stay checkable."""
    monkeypatch.setattr(settings, "ttc_api_key", None)


def page_text(page: int) -> str:
    return next(p.text for p in get_store().pages(KTM) if p.page == page)


def test_streams_tokens_then_one_done_frame(monkeypatch):
    def answer(user):
        page = offered_pages(user)[0]
        return f"Set the chain slack as printed [p. {page}]."

    monkeypatch.setattr(chat.llm, "stream", fake_stream(answer))
    out = frames(chat.answer(KTM, [{"role": "user", "content": "chain is loose"}]))

    assert [f["type"] for f in out[:-1]] == ["token"] * (len(out) - 1)
    assert len(out) > 2, "the answer must arrive as a stream, not as one blob"
    done = out[-1]
    assert done["type"] == "done"
    assert done["answer"] == "".join(f["text"] for f in out[:-1])
    assert set(done) == {"type", "answer", "citations", "usd", "tokensIn", "tokensSaved"}
    assert done["usd"] == 0.0012
    assert done["tokensIn"] == 3200


def test_every_citation_quote_is_verbatim_on_the_page_it_names(monkeypatch):
    def answer(user):
        pages = offered_pages(user)
        return " ".join(f"Step {i + 1} is printed there [p. {p}]." for i, p in enumerate(pages[:3]))

    monkeypatch.setattr(chat.llm, "stream", fake_stream(answer))
    done = frames(chat.answer(KTM, [{"role": "user", "content": "adjust the chain tension"}]))[-1]

    assert done["citations"], "a grounded answer that cites real pages must return citations"
    for citation in done["citations"]:
        assert citation["quote"]
        assert citation["quote"] in page_text(citation["page"]), citation


def test_invented_page_numbers_are_dropped(monkeypatch):
    def answer(user):
        real = offered_pages(user)[0]
        return f"Real [p. {real}]. Invented [p. 9001]. Also invented [p. 1337]."

    monkeypatch.setattr(chat.llm, "stream", fake_stream(answer))
    done = frames(chat.answer(KTM, [{"role": "user", "content": "chain is loose"}]))[-1]

    cited = {c["page"] for c in done["citations"]}
    assert 9001 not in cited and 1337 not in cited
    assert cited == {offered_pages(chat.llm.stream.seen["user"])[0]}


def test_out_of_manual_question_says_not_covered_and_cites_nothing(monkeypatch):
    """The router calls it unknown, so no page is retrieved, no OpenAI call is paid for, and the
    answer is the one sentence the prompt reserves for it."""

    monkeypatch.setattr(
        chat.ask_mod, "_route", lambda q: Route(intent="unknown", components=[], queries=[], specName=None, specKind=None)
    )

    def explode(*args, **kwargs):
        raise AssertionError("an out-of-manual question must not reach OpenAI")

    monkeypatch.setattr(chat.llm, "stream", explode)
    out = frames(chat.answer(KTM, [{"role": "user", "content": "how do I wheelie"}]))

    done = out[-1]
    assert done["answer"] == chat.NOT_COVERED
    assert done["citations"] == []
    assert done["usd"] == 0.0


def test_a_real_job_with_no_matching_page_still_gets_an_answer(monkeypatch):
    """The policy change: only "not about this motorcycle" refuses. A job the index simply missed must
    still reach the model, which then gives general steps with nothing to cite."""
    monkeypatch.setattr(chat.get_index(), "query", lambda *a, **k: [])
    stream = fake_stream(lambda user: f"{chat.GENERAL}
1. Drain the old fluid.
2. Refill and bleed.")
    monkeypatch.setattr(chat.llm, "stream", stream)
    done = frames(chat.answer(KTM, [{"role": "user", "content": "change the brake fluid"}]))[-1]
    assert done["answer"].startswith(chat.GENERAL)
    assert "No printed page" in stream.seen["user"]


def test_model_that_ignores_the_prompt_still_yields_no_unverified_citation(monkeypatch):
    monkeypatch.setattr(chat.llm, "stream", fake_stream(lambda user: "Torque it to 48 Nm."))
    done = frames(chat.answer(KTM, [{"role": "user", "content": "rear axle torque"}]))[-1]
    assert done["citations"] == [], "an answer with no [p. N] marker must return no citations at all"
    assert done["answer"] == "Torque it to 48 Nm."


def test_prompt_carries_numbered_pages_and_the_grounding_rules(monkeypatch):
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)
    frames(chat.answer(KTM, [{"role": "user", "content": "check the tire pressure"}]))

    seen = stream.seen
    assert seen["model"] == settings.model_chat
    assert seen["route"] == "chat.answer"
    assert seen["cache_key"], "the long grounding prompt must be pinned to a prompt cache key"
    assert "[p. N]" in seen["system"] and chat.NOT_COVERED in seen["system"]
    assert "Please provide an answer based solely on the provided sources" in seen["system"]

    pages = offered_pages(seen["user"])
    assert 0 < len(pages) <= chat.MAX_PAGES
    assert "check the tire pressure" in seen["user"]
    for page in pages:
        assert page_text(page).split()[0] in seen["user"]


def test_context_stays_inside_the_token_budget(monkeypatch):
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)
    for question in ("change the engine oil", "remove the rear wheel", "replace a fuse", "charge the battery"):
        frames(chat.answer(KTM, [{"role": "user", "content": question}]))
        assert chat._tokens(stream.seen["user"]) <= chat.TOKEN_BUDGET + 500, question


def test_memory_keeps_the_last_six_turns_only(monkeypatch):
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(12)
    ]
    frames(chat.answer(KTM, [*history, {"role": "user", "content": "chain is loose"}]))

    sent = stream.seen["history"]
    assert len(sent) == chat.MEMORY_TURNS
    assert [m["content"] for m in sent] == [f"turn {i}" for i in range(6, 12)]
    assert {m["role"] for m in sent} == {"user", "assistant"}
    assert all(m["content"] != "chain is loose" for m in sent), "the live question is not part of the memory"


def test_empty_question_is_answered_without_any_call(monkeypatch):
    monkeypatch.setattr(chat.llm, "stream", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    done = frames(chat.answer(KTM, [{"role": "user", "content": "   "}]))[-1]
    assert done["answer"] == chat.NOT_COVERED


def test_openai_failure_degrades_to_not_covered(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("openai down")
        yield

    monkeypatch.setattr(chat.llm, "stream", explode)
    done = frames(chat.answer(KTM, [{"role": "user", "content": "chain is loose"}]))[-1]
    assert done["answer"] == chat.NOT_COVERED
    assert done["citations"] == []


def fake_compress(keep_markers=True, saved=450):
    """bear-2 as it really behaves: drops stopwords and punctuation, keeps the PAGE markers."""
    calls: list[dict] = []

    def compress(text, aggressiveness=0.3, route="chat"):
        calls.append({"text": text, "aggressiveness": aggressiveness, "route": route})
        out = []
        for line in text.split("\n"):
            if re.fullmatch(r"PAGE \d+", line):
                out.append(line if keep_markers else "")
            else:
                out.append(" ".join(w for w in line.split() if len(w) > 2))
        body = "\n".join(out)
        return body, 1000, 1000 - saved

    compress.calls = calls
    return compress


def test_one_compress_call_carries_every_page(monkeypatch):
    """The API allows 60 requests/minute, so a chat must cost exactly one compress call, not one per page."""
    monkeypatch.setattr(settings, "ttc_api_key", "ttc-test-key")
    compress = fake_compress()
    monkeypatch.setattr(chat.ttc, "compress", compress)
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)

    done = frames(chat.answer(KTM, [{"role": "user", "content": "chain is loose"}]))[-1]

    assert len(compress.calls) == 1
    assert compress.calls[0]["route"] == "chat"
    assert compress.calls[0]["aggressiveness"] == chat.SOFT_AGGRESSIVENESS
    sent = offered_pages(stream.seen["user"])
    assert sent and all(f"PAGE {p}" in compress.calls[0]["text"] for p in sent)
    assert done["tokensSaved"] == 450


def test_lost_page_markers_fall_back_to_the_printed_text(monkeypatch):
    """A marker eaten by compression would attribute one page's text to another page's number, so a
    failed check must throw the compressed version away rather than risk a wrong citation."""
    monkeypatch.setattr(settings, "ttc_api_key", "ttc-test-key")
    monkeypatch.setattr(chat.ttc, "compress", fake_compress(keep_markers=False))
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)

    done = frames(chat.answer(KTM, [{"role": "user", "content": "chain is loose"}]))[-1]

    assert done["tokensSaved"] == 0, "a discarded compression saved nothing and must not claim to"
    for page in offered_pages(stream.seen["user"]):
        assert page_text(page).split()[0] in stream.seen["user"]
    for citation in done["citations"]:
        assert citation["quote"] in page_text(citation["page"])


def test_chat_endpoint_streams_sse(client, monkeypatch):
    monkeypatch.setattr(chat.llm, "stream", fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}]."))
    response = client.post("/chat", json={"manualId": KTM, "messages": [{"role": "user", "content": "chain is loose"}]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert body.startswith("data: ")
    assert '"type": "done"' in body or '"type":"done"' in body


def test_chat_endpoint_404s_on_an_unknown_manual(client):
    response = client.post("/chat", json={"manualId": "nope", "messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 404


def test_referral_sentences_are_stripped_but_printed_values_survive():
    """Owner manuals pad every job with "have it done by an authorised workshop". A mechanic gets the
    figures, not the referral - and a sentence that prints a number is never dropped."""
    cases = [
        ("Have the fault rectified by a spe- cialist workshop, preferably an authorised BMW Motorrad "
         "retailer. Check the oil level every 1000 km.", "Check the oil level every 1000 km."),
        ("Valve clearance must be checked by an authorised workshop. Valve clearance intake 0.10 mm.",
         "Valve clearance intake 0.10 mm."),
        ("Remove the seat. Undo the bolt.", "Remove the seat. Undo the bolt."),
    ]
    for raw, expected in cases:
        assert chat._strip_referrals(raw) == expected

    # The value-bearing warning stays whole: BMW prints tightening torques inside exactly these sentences.
    kept = chat._strip_referrals("Always have the security screws tightened to 21 Nm by a specialist workshop.")
    assert "21 Nm" in kept


def test_stripping_never_splits_a_decimal():
    """Splitting on every full stop would turn 0.10 mm into "0. 10 mm" and corrupt a printed clearance."""
    for value in ("0.10 mm", "1.7 l", "2.2 bar", "73.8 lbf ft"):
        assert value in chat._strip_referrals(f"Consult a workshop. Printed value is {value} exactly.")


def test_every_printed_figure_survives_stripping_on_both_real_manuals():
    figure = re.compile(r"\d+(?:[.,]\d+)?\s*(?:Nm|l\b|mm|bar|psi|V|A|km|qt|lbf)", re.I)
    for manual_id in (KTM, BMW):
        for page in get_store().pages(manual_id):
            flat = " ".join(page.text.split())
            missing = set(figure.findall(flat)) - set(figure.findall(chat._strip_referrals(page.text)))
            assert not missing, f"{manual_id} p.{page.page} lost {missing}"


def test_context_sent_to_the_model_carries_no_dealer_referral(monkeypatch):
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)
    for question in ("valve clearance spec", "steering head bearing play", "how do I check the brake pads on the front"):
        frames(chat.answer(BMW, [{"role": "user", "content": question}]))
        sent = stream.seen["user"]
        bare = [s for s in re.split(r"(?<=[.!?])\s+", sent) if chat.DEALER.search(s) and not any(c.isdigit() for c in s)]
        assert not bare, f"{question}: referral boilerplate reached the prompt: {bare[:2]}"


def test_boilerplate_only_pages_lose_their_slot(monkeypatch):
    """A page that only says "see your dealer" must rank behind a page that prints a procedure."""
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)
    monkeypatch.setattr(chat, "MAX_PAGES", 2)

    boiler, solid = 900, 901
    pages = {boiler: "Contact an authorized KTM workshop.", solid: "Tightening torque rear wheel spindle 100 Nm. " * 12}

    class FakePage:
        def __init__(self, page, text):
            self.page, self.text = page, text

    monkeypatch.setattr(chat, "_pages_for", lambda m, q: ([boiler, solid], True))
    real_pages = get_store().pages

    def patched(manual_id):
        return [FakePage(p, t) for p, t in pages.items()] if manual_id == KTM else real_pages(manual_id)

    monkeypatch.setattr(chat.get_store(), "pages", patched)
    frames(chat.answer(KTM, [{"role": "user", "content": "rear axle torque"}]))
    assert offered_pages(stream.seen["user"])[0] == solid


def test_the_prompt_forbids_dealer_advice_and_safety_boilerplate(monkeypatch):
    stream = fake_stream(lambda user: f"Yes [p. {offered_pages(user)[0]}].")
    monkeypatch.setattr(chat.llm, "stream", stream)
    frames(chat.answer(KTM, [{"role": "user", "content": "valve clearance"}]))

    system = stream.seen["system"]
    assert "professional" in system and "on the lift" in system
    assert "authorised workshop" in system and "NEVER tell the reader" in system
    assert "safety boilerplate" in system
    assert chat.GENERAL in system

"""What a six-turn spoken conversation must not do. Owner: voice-interaction agent.

Every assertion here is a rule that was written because the live socket broke it in a recorded
turn on 2026-09-20, not because it might. The traces are in the scratchpad and the numbers are in
`web/docs/VOICE.md`; the turn each rule came from is named in the test's own docstring, so a
future edit to `_prompt` that quietly drops one of them fails here with the reason attached.

`test_voice_agent.py` already covers the Settings message's shape - the tools, the endpoints, the
keyterms, the digest. This file is only about how the thing TALKS, plus the one change that made
a procedure question stop taking ten seconds (`find_procedure` returning its section's text).
"""


import pytest

from conftest import BMW, KTM

SETTINGS = "/voice/agent-settings"


@pytest.fixture(autouse=True)
def https_base(monkeypatch):
    """Deepgram calls the tool endpoints from its own servers and takes https only, so the
    settings endpoint refuses to build a Settings message against conftest's http://testserver."""
    from app.config import settings

    monkeypatch.setattr(settings, "public_base", "https://ttm.example.test/api")


@pytest.fixture
def prompt(client) -> str:
    body = client.get(SETTINGS, params={"manualId": KTM}).json()
    return body["settings"]["agent"]["think"]["prompt"]


# ---------------------------------------------------------------- the greeting


def test_the_greeting_is_a_mechanic_not_an_assistant(client):
    """Turn 0. "I see you're looking at the KTM 390 Duke 2024." is an assistant narrating the
    screen the rider is already holding. A foreman says the bike and gets out of the way."""
    greeting = client.get(SETTINGS, params={"manualId": KTM}).json()["settings"]["agent"]["greeting"]
    assert greeting == "KTM 390 Duke 2024. Go ahead."
    assert "I see" not in greeting
    assert len(greeting.split()) <= 8


# ---------------------------------------------------------------- how it talks


def test_one_sentence_not_two_or_three(prompt):
    """Live, the old rule "one or two sentences, never three" produced four: "Page 86." "The
    manual does not print a brake fluid spec on this page." "The usual way is DOT four for KTM but
    this manual does not say." "Check page 82 or 83 for the actual fluid type." """
    assert "One sentence. A second one only when it carries a different fact" in prompt
    assert "Never a third" in prompt
    assert "One or two sentences" not in prompt


def test_the_page_comes_before_the_figure_and_stays_in_digits(prompt):
    """The reader is moved by `/\\bpages?\\s+(\\d{1,4})\\b/` in voice-deepgram.js reading the
    agent's own transcript, so the page has to reach the transcript as DIGITS even though aura-2
    says it as "seventy eight". A prompt that asked for "page seventy eight" in words would read
    beautifully and silently stop the reader turning, which is the product's whole promise."""
    assert "The page first, in the same sentence as the figure" in prompt
    assert '"Page 78, one hundred newton metres."' in prompt
    assert 'Write the page as digits - "page 78"' in prompt


def test_figures_are_spelled_the_way_they_are_said(prompt):
    """Measured over eight live turns every figure came out spelled, but two leaked a printed
    GRADE through raw - SAE 15W/50 and DOT 4 - and aura-2 reads those as letters. The grades are
    now in the table with the torques."""
    for printed, spoken in [
        ("100 Nm", "one hundred newton metres"),
        ("2.0 bar", "two point zero bar"),
        ("SAE 15W/50", "SAE fifteen W fifty"),
        ("DOT 4", "DOT four"),
        ("M10x1.25", "M ten by one point two five"),
    ]:
        assert printed in prompt and spoken in prompt


def test_nothing_that_only_works_on_a_screen(prompt):
    """A semicolon is not a sound. Live, the old prompt produced "The manual doesn't print the
    brake fluid type or spec; do you want the page opened?" and aura-2 read straight through it."""
    assert "No bullet points" in prompt
    assert "no markdown" in prompt
    assert "no semicolons, colons, dashes or brackets" in prompt


def test_no_trailing_question_and_no_offer(prompt):
    """Turn 3, live: "...do you want the page on the brake system opened?" A mechanic with both
    hands on a wheel cannot answer that, so it is not a helpful ending, it is a dead end."""
    assert "NEVER finish with a question, an offer or a check-in" in prompt
    for banned in ['"do you want the\n  page opened"', '"anything else"', '"let me know if"']:
        assert banned in prompt


def test_thanks_gets_thanks_and_nothing_else(prompt):
    """Turn 5, live, once the page-first rule was in: "thanks" was answered with "Page 139." and
    then "You're welcome." The page-first rule has to be scoped to answers that HAVE a page."""
    assert 'When he thanks you, "you\'re welcome" is the whole answer' in prompt


def test_it_is_not_an_assistant(prompt):
    assert '"as an AI"' in prompt
    assert "another\nmechanic across the bench, not an assistant" in prompt


# ---------------------------------------------------------------- grounding under a conversation


def test_a_follow_up_about_a_different_part_is_a_new_lookup(prompt):
    """THE regression, and the reason this file exists. A draft of the prompt said "a result you
    received earlier in this conversation still counts", meaning it for "which page was that?".
    gpt-4.1 read it as a licence and answered "and the front one?" straight out of context with
    "Thirty front axle nut" - the manual prints forty five. A wrong torque from a conversational
    shortcut is exactly the failure this product exists to make impossible."""
    assert "EVERY QUESTION IS A NEW QUESTION" in prompt
    assert '"And the front one?" is not a follow-up' in prompt
    assert "it gets its own function call" in prompt
    # and the narrow exception that makes "which page was that?" instant is still narrow
    assert "repeat of something you already said" in prompt
    assert "repeat it word for\nword and change nothing" in prompt


def test_a_page_number_is_treated_as_a_figure(prompt):
    """Live: "Check page 82 or 83 for the actual fluid type." Neither page was in any result. A
    page the mechanic turns to is as wrong-able as a torque, and it was not covered by the number
    rule because a page is not a torque, a capacity, a pressure or an interval."""
    assert "A PAGE NUMBER IS A FIGURE" in prompt
    assert 'never say "check page 82 or 83"' in prompt


def test_it_has_to_look_twice_before_saying_the_manual_is_silent(prompt):
    """Live: get_spec("brake fluid") came back with brake LINING thickness rows, and the agent
    said "the manual doesn't print the brake fluid type or spec" - while page 85 prints DOT 4 and
    DOT 5.1. With this rule it calls find_procedure and answers "Page 85, brake fluid DOT four or
    DOT five point one." Same grounding, one more lookup, the right answer."""
    assert "you must have looked twice" in prompt
    assert "call find_procedure with his own words" in prompt


def test_the_general_steps_licence_never_reaches_a_fluid_grade(prompt):
    """Live, with the licence written as "steps and order only": "The usual way is DOT four for
    KTM but this manual does not say." That is a specification spoken from memory of a brand,
    dressed as a general procedure. Which fluid is not a step."""
    assert "This licence covers STEPS AND ORDER ONLY" in prompt
    assert "general steps carry no figures" in prompt
    assert "which fluid, grade, oil, coolant or brake fluid to use" in prompt
    assert "those are specifications" in prompt


def test_the_grounding_rule_survived_the_rewrite(prompt):
    """The pitch quotes these two sentences verbatim off this file. They are the product."""
    assert "You do not know anything about this motorcycle" in prompt
    assert (
        "A torque, a capacity, a pressure, a clearance, a\n  gap, an interval, a fuse rating or a "
        "part number may only leave your mouth if a function result\n  you have already received "
        "printed it, word for word." in prompt
    )
    assert "NEVER tell anyone to visit, consult or contact a dealer" in prompt


# ---------------------------------------------------------------- being interrupted


def test_the_prompt_says_what_to_do_when_it_is_cut_off(prompt):
    """The client kills the audio in under 3 ms; the model still has the abandoned sentence in its
    context and will happily apologise for it or finish it. Neither is what a foreman does."""
    assert "BEING INTERRUPTED" in prompt
    assert "the\nsentence you were saying is dead" in prompt
    for banned in ['do not say "sorry"', 'do not say "as I was saying"', "do not finish the old sentence"]:
        assert banned in prompt


def test_the_prompt_knows_the_app_may_have_spoken_for_it(prompt):
    """voice-deepgram.js injects "One sec, checking the manual." with InjectAgentMessage when a
    lookup chain runs long, and Deepgram puts it in the model's own history as something the agent
    said. Without this rule the model either repeats it or apologises for the wait."""
    assert 'One sec, checking the manual.' in prompt
    assert "the app said\nit for you while a lookup ran" in prompt
    assert "Do not repeat it and do not mention the wait" in prompt


# ---------------------------------------------------------------- improvement #4


def test_find_procedure_hands_back_the_section_s_printed_text(client):
    """Improvement #4. Measured live, a procedure question was find_procedure followed by five
    read_page calls and took 6.3 s to the first word; every individual round trip was 250-650 ms,
    so the cost was the number of hops. The best section's pages now travel with it."""
    body = client.post(f"/voice/tools/find_procedure?manualId={KTM}", json={"query": "adding front brake fluid"}).json()
    best = body["sections"][0]
    assert best["text"]
    assert best["textPages"]
    assert best["textPages"][0] == best["pageStart"]
    # the text is the manual's, byte for byte, not a summary of it
    page = client.post(f"/voice/tools/read_page?manualId={KTM}", json={"page": best["textPages"][0]}).json()["text"]
    assert page.strip()[:200] in best["text"]


def test_only_the_best_section_carries_text(client):
    """Every match carrying its pages would put four sections of printed text in front of a model
    that is going to read one of them, and the think model pays for all of it in latency."""
    body = client.post(f"/voice/tools/find_procedure?manualId={KTM}", json={"query": "brake fluid"}).json()
    assert len(body["sections"]) > 1
    for extra in body["sections"][1:]:
        assert "text" not in extra


def test_the_section_text_is_bounded(client):
    """A section that runs to twenty pages must not become a twenty-page function result: the
    point of the change is fewer hops, not a bigger context."""
    from app.voice import SECTION_CHARS, SECTION_PAGES

    body = client.post(f"/voice/tools/find_procedure?manualId={BMW}", json={"query": "engine oil"}).json()
    best = body["sections"][0]
    assert len(best.get("text", "")) <= SECTION_CHARS + 64  # + the "[page N]" markers
    assert len(best.get("textPages", [])) <= SECTION_PAGES


def test_the_page_each_run_of_text_came_off_is_named(client):
    """The agent has to be able to say which page a step is printed on without a second call, so
    the text is marked with the manual's own page numbers rather than concatenated blind."""
    body = client.post(f"/voice/tools/find_procedure?manualId={KTM}", json={"query": "adding front brake fluid"}).json()
    best = body["sections"][0]
    for page in best["textPages"]:
        assert f"[page {page}]" in best["text"]


def test_find_procedure_with_no_matches_still_answers(client, monkeypatch):
    """No sections, no text, and no crash reaching for sections[0]."""
    from app.models import AskResponse

    monkeypatch.setattr("app.ask.answer", lambda *_: AskResponse(matches=[], intent="procedure"))
    body = client.post(f"/voice/tools/find_procedure?manualId={KTM}", json={"query": "how do I fly"}).json()
    assert body["sections"] == []
    assert body["firstPage"] == 0


def test_the_tool_descriptions_point_at_the_text(client):
    """The model will chain read_page out of habit unless find_procedure's own description says it
    does not have to, and read_page's says when it still should."""
    functions = client.get(SETTINGS, params={"manualId": KTM}).json()["settings"]["agent"]["think"]["functions"]
    by_name = {f["name"]: f for f in functions}
    assert "printed text back with it" in by_name["find_procedure"]["description"]
    assert "will not need read_page after it" in by_name["find_procedure"]["description"]
    assert "only when" in by_name["read_page"]["description"]

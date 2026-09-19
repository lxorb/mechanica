"""Local search behavior, with in-memory fixtures and read-only seeded regressions."""

from unittest.mock import Mock

import pytest

from app.models import Manual, Page, Section, Spec
from app.search import Hit, SpecHit
from app.search import local as local_mod
from app.search.local import LocalIndex, canon, contiguous, normalize, side_of, stem
from conftest import BMW, KTM

# app/search/local.py belongs to the search agent and its tuning constants move; read the
# confidence floor off the module instead of pinning it, so a retune is not an import error.
FLOOR = getattr(local_mod, "FLOOR", 0.0)
TITLE_EVIDENCE = getattr(local_mod, "TITLE_EVIDENCE", 0.5)


def _section(section_id, title, page=1, **kwargs):
    return Section(
        id=section_id, title=title, chapter=kwargs.pop("chapter", "Maintenance"),
        pageStart=page, pageEnd=kwargs.pop("pageEnd", page),
        keywords=kwargs.pop("keywords", []), highlights=[], **kwargs,
    )


def _page(manual_id, number, text):
    return Page(manualId=manual_id, page=number, width=595, height=842, text=text, blocks=[])


@pytest.fixture
def manual():
    # Enough unrelated sections for meaningful BM25 IDF and the confidence floor.
    titles = [
        ("front-pads", "Front brake pads"), ("rear-pads", "Rear brake pads"),
        ("oil", "Engine oil change"), ("tyres", "Tyre pressure"),
        ("chain", "Chain adjustment"), ("battery", "Battery charging"),
        ("coolant", "Coolant level"), ("headlight", "Headlight adjustment"),
        ("service", "Service schedule"), ("seat", "Seat removal"),
    ]
    return Manual(
        id="test-manual", bikeIds=[], file="/manuals/test.pdf", pages=20,
        title="Test manual", source="https://example.invalid/test.pdf", outline=[],
        sections=[_section(sid, title, page) for page, (sid, title) in enumerate(titles, 1)],
        parts=[],
    )


@pytest.fixture
def specs():
    return [
        Spec(sectionId=sid, name=name, kind=kind, value=value, unit=unit, page=page, quote=f"{name}: {value}")
        for page, (sid, name, kind, value, unit) in enumerate([
            ("rear-pads", "Rear spindle nut torque", "torque", "90 Nm", "Nm"),
            ("front-pads", "Front spindle nut torque", "torque", "50 Nm", "Nm"),
            ("oil", "Engine oil capacity", "capacity", "2 litres", "litres"),
            ("oil", "Engine oil grade", "grade", "SAE 15W-50", None),
            ("tyres", "Front tyre pressure", "pressure", "2.3 bar", "bar"),
            ("tyres", "Rear tyre pressure", "pressure", "2.5 bar", "bar"),
        ], 1)
    ]


@pytest.fixture
def local_index(manual, specs):
    index = LocalIndex()
    index.index(manual, [_page(manual.id, 6, "Disconnect the diagnostic connector.")], specs)
    return index


@pytest.mark.parametrize(("text", "expected"), [
    ("  CHECK: Tyres, 2.5 BAR!  ", "check tyres 2 5 bar"),
    ("topping-up anti-freeze", "refill antifreeze"),
    ("filled up", "filled up"),
    ("filling up", "refill"),
    ("Newton metres / N-m", "nm nm"),
    ("hand bars; head lamps; spark plugs; air filters", "handlebar headlight sparkplug airfilter"),
    ("jump-starting; quick-release; pre-load", "jumpstart quickrelease preload"),
    ("two-up one-up wheel spindle", "twoup oneup spindle"),
    ("", ""),
])
def test_normalize_phrases_case_and_punctuation(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize(("word", "expected"), [
    ("batteries", "battery"), ("checking", "check"), ("checked", "check"),
    ("boxes", "box"), ("pads", "pad"), ("brake", "brak"),
    ("pressure", "pressur"), ("glass", "glass"), ("gas", "gas"), ("", ""),
])
def test_stem_suffixes_and_short_words(word, expected):
    assert stem(word) == expected


@pytest.mark.parametrize(("rider", "manual_text"), [
    ("tire pressure", "tyre inflation"), ("back wheel", "rear rim"),
    ("chain play", "chain tension"), ("anti-freeze", "coolant"),
    ("top up", "refill"), ("tightening Newton metres", "torque nm"),
    ("wheel spindle nut", "axle bolt"), ("jump starting", "jumper"),
    ("spark plugs", "spark-plug"), ("pre-load", "suspension"),
    ("two up", "pillion"), ("one up", "solo"), ("head lamp", "bulb"),
])
def test_canon_matches_rider_vocabulary(rider, manual_text):
    assert canon(rider) == canon(manual_text)
    assert canon(rider)


def test_canon_removes_stopwords_but_preserves_order_repetition_and_numbers():
    assert canon("How do I check my bike's FRONT brake pads, please? 12 12") == [
        "check", "front", "brak", "pad", "12", "12",
    ]


@pytest.mark.parametrize("text", ["", " \t\n", "!?!", "how do I do this on my bike"])
def test_canon_empty_or_stopword_only_text(text):
    assert canon(text) == []


@pytest.mark.parametrize(("hay", "needle", "expected"), [
    (["front", "brake", "pad"], ["front", "brake"], True),
    (["front", "brake", "pad"], ["brake", "pad"], True),
    (["pad"], ["pad"], True),
    (["front", "brake", "pad"], ["front", "pad"], False),
    (["brake", "pad"], ["pad", "brake"], False),
    (["brake"], ["brake", "pad"], False),
    (["brake"], [], False), ([], ["brake"], False), ([], [], False),
])
def test_contiguous_requires_an_ordered_nonempty_phrase(hay, needle, expected):
    assert contiguous(hay, needle) is expected


@pytest.mark.parametrize(("text", "expected"), [
    ("front brake", "front"), ("back wheel", "rear"),
    ("front and rear brakes", None), ("engine oil", None), ("", None),
])
def test_side_of_requires_exactly_one_side(text, expected):
    assert side_of(canon(text)) == expected


def test_missing_manual_returns_empty_results(monkeypatch):
    store = Mock()
    store.manual.return_value = None
    monkeypatch.setattr("app.store.get_store", lambda: store)
    index = LocalIndex()

    assert index.built("missing") is None
    assert index.query("missing", ["engine oil"]) == []
    assert index.spec("missing", "engine oil") == []
    assert index.snippet("missing", "oil") == ""
    index.remove("missing")
    store.pages.assert_not_called()
    store.specs.assert_not_called()


def test_empty_manual_has_no_search_results(manual):
    index = LocalIndex()
    index.index(manual.model_copy(update={"sections": []}), [], [])
    assert index.built(manual.id) is not None
    assert index.query(manual.id, ["engine oil"]) == []
    assert index.spec(manual.id, "engine oil") == []
    assert index.snippet(manual.id, "oil") == ""


def test_store_is_loaded_lazily_cached_and_reloaded_after_remove(monkeypatch, manual, specs):
    store = Mock()
    store.manual.return_value = manual
    store.pages.return_value = [_page(manual.id, 3, "Original oil instructions.")]
    store.specs.return_value = specs
    get_store = Mock(return_value=store)
    monkeypatch.setattr("app.store.get_store", get_store)
    index = LocalIndex()
    get_store.assert_not_called()

    assert index.query(manual.id, ["engine oil change"])[0].sectionId == "oil"
    first = index.built(manual.id)
    assert index.snippet(manual.id, "oil") == "Original oil instructions."
    assert index.spec(manual.id, "engine oil")
    get_store.assert_called_once_with()
    store.manual.assert_called_once_with(manual.id)
    store.pages.assert_called_once_with(manual.id)
    store.specs.assert_called_once_with(manual.id)

    store.pages.return_value = [_page(manual.id, 3, "Updated oil instructions.")]
    index.remove(manual.id)
    index.remove(manual.id)
    assert index.snippet(manual.id, "oil") == "Updated oil instructions."
    assert index.built(manual.id) is not first
    assert get_store.call_count == 2


def test_reindex_replaces_sections_pages_and_specs_without_affecting_other_manuals(local_index, manual):
    other = manual.model_copy(update={"id": "other-manual"})
    local_index.index(other, [_page(other.id, 3, "Other manual oil instructions.")], [])
    updated = manual.model_copy(update={"sections": [_section("replacement", "Seat latch")]})
    local_index.index(updated, [_page(manual.id, 1, "New latch instructions.")], [])

    assert local_index.snippet(manual.id, "oil") == ""
    assert local_index.snippet(manual.id, "replacement") == "New latch instructions."
    assert local_index.query(manual.id, ["engine oil"]) == []
    assert local_index.spec(manual.id, "engine oil") == []
    assert local_index.query(other.id, ["engine oil change"])[0].sectionId == "oil"
    assert local_index.snippet(other.id, "oil") == "Other manual oil instructions."
    local_index.remove(manual.id)
    assert local_index.snippet(other.id, "oil") == "Other manual oil instructions."


@pytest.mark.parametrize("queries", [[], [""], [" ", "\t\n"], ["how do I"], ["!?!"], ["quasar nebula"]])
def test_query_rejects_empty_and_unrelated_input(local_index, manual, queries):
    assert local_index.query(manual.id, queries, components=["front brake pads"]) == []


@pytest.mark.parametrize(("query", "expected"), [
    ("front brake pads", "front-pads"), ("back brake pads", "rear-pads"),
    ("replace engine lube", "oil"), ("tire inflation", "tyres"),
    ("diagnostic connector", "battery"),
])
def test_query_searches_titles_page_text_and_synonyms(local_index, manual, query, expected):
    hits = local_index.query(manual.id, [query])
    assert hits and hits[0].sectionId == expected
    assert all(isinstance(hit, Hit) for hit in hits)
    assert hits[0].score == pytest.approx(1.0)
    assert all(0 < hit.score <= 1 for hit in hits)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)
    assert len({hit.sectionId for hit in hits}) == len(hits)


def test_query_searches_chapters(manual):
    manual.sections[5].chapter = "Electrical diagnostics"
    index = LocalIndex()
    index.index(manual, [], [])
    assert index.query(manual.id, ["electrical diagnostics"])[0].sectionId == "battery"


def test_query_limit_and_blank_variants(local_index, manual):
    queries = [" ", "front rear brake pads engine oil tyre chain battery coolant headlight service seat", ""]
    all_hits = local_index.query(manual.id, queries, k=100)
    assert len(all_hits) > 8
    assert local_index.query(manual.id, queries) == all_hits[:8]
    assert local_index.query(manual.id, queries, k=3) == all_hits[:3]
    assert local_index.query(manual.id, queries, k=0) == []
    assert local_index.query(manual.id, [queries[1]], k=100) == all_hits


@pytest.mark.parametrize(("component", "expected"), [("front brake", "front-pads"), ("back brake", "rear-pads")])
def test_components_disambiguate_front_and_rear(local_index, manual, component, expected):
    hits = local_index.query(manual.id, ["brake pads"], components=[component])
    assert hits[0].sectionId == expected
    assert hits[0].score > hits[1].score


def test_requesting_both_sides_does_not_penalize_either(local_index, manual):
    hits = local_index.query(manual.id, ["front and rear brake pads"])
    assert [hit.sectionId for hit in hits[:2]] == ["front-pads", "rear-pads"]
    assert hits[0].score == hits[1].score == 1.0


@pytest.mark.skipif(FLOOR <= 0, reason="no confidence floor in app/search/local.py")
@pytest.mark.parametrize(
    ("peak", "queries", "components", "kept"),
    [
        # A weak BM25 peak only means "no match" when the rider's own words match nothing printed.
        # Here they cover a printed title, so the weak peak survives:
        (FLOOR - 0.001, ["front brake pads"], None, True),
        (FLOOR - 0.001, ["front brake"], None, True),
        # one word out of a three-word title is under TITLE_EVIDENCE, so it does not:
        (FLOOR - 0.001, ["front"], None, False),
        (FLOOR - 0.001, ["quasar nebula"], None, False),
        # components are the router's guess, not something the manual prints: never a rescue.
        (FLOOR - 0.001, ["quasar nebula"], ["front brake pads"], False),
        (FLOOR - 0.001, ["front"], ["front brake pads"], False),
        # a peak at or above the floor needs no printed evidence at all:
        (FLOOR, ["quasar nebula"], None, True),
        (FLOOR + 5.0, ["quasar nebula"], None, True),
    ],
)
def test_confidence_floor_rejects_only_a_weak_peak_with_no_printed_evidence(
    local_index, manual, monkeypatch, peak, queries, components, kept
):
    """The gate is `peak < FLOOR and not evidence`; evidence is the rider's own words hitting a
    printed keyword phrase or covering at least TITLE_EVIDENCE of a printed title."""
    built = local_index.built(manual.id)
    monkeypatch.setattr(built.bm25, "get_scores", lambda tokens: [peak] + [0.0] * 9)
    hits = local_index.query(manual.id, queries, components=components)
    if kept:
        assert hits and hits[0].sectionId == "front-pads"
    else:
        assert hits == []


@pytest.mark.skipif(FLOOR <= 0, reason="no confidence floor in app/search/local.py")
@pytest.mark.parametrize("peak", [0.0, -1.0])
def test_a_zero_bm25_peak_still_answers_when_the_words_are_printed(local_index, manual, monkeypatch, peak):
    """The "torque" case: a word every section prints has ~0 IDF, so BM25 contributes nothing and
    the printed-title evidence is the only vote there is."""
    monkeypatch.setattr(local_index.built(manual.id).bm25, "get_scores", lambda tokens: [peak] + [0.0] * 9)
    hits = local_index.query(manual.id, ["front brake pads"])
    assert hits and hits[0].sectionId == "front-pads"
    assert local_index.query(manual.id, ["quasar nebula"]) == []


@pytest.mark.skipif(FLOOR <= 0, reason="no confidence floor in app/search/local.py")
def test_a_printed_keyword_is_evidence_on_its_own(manual, monkeypatch):
    """Title coverage is zero on both sections here, so only the keyword phrase can rescue."""

    def weak(tokens):
        return [0.0, FLOOR - 0.001]

    manual.sections = [_section("plain", "Procedure"), _section("keyword", "Procedure", keywords=["tyre pressure"])]
    with_keyword = LocalIndex()
    with_keyword.index(manual, [], [])
    monkeypatch.setattr(with_keyword.built(manual.id).bm25, "get_scores", weak)
    hits = with_keyword.query(manual.id, ["tyre pressure"])
    assert [h.sectionId for h in hits] == ["keyword"]

    manual.sections = [_section("plain", "Procedure"), _section("other", "Procedure")]
    without = LocalIndex()
    without.index(manual, [], [])
    monkeypatch.setattr(without.built(manual.id).bm25, "get_scores", weak)
    assert without.query(manual.id, ["tyre pressure"]) == []


@pytest.mark.parametrize("scores", [([10.0, 0.0], [0.0, 2.0]), ([2.0, -1.0], [0.0, 2.0])])
def test_query_variants_normalize_independently_and_ignore_negative_scores(local_index, manual, monkeypatch, scores):
    scorer = Mock(side_effect=[row + [0.0] * 8 for row in scores])
    monkeypatch.setattr(local_index.built(manual.id).bm25, "get_scores", scorer)
    # These terms have no title/keyword overlap, isolating the BM25 aggregation.
    hits = local_index.query(manual.id, ["zebra", "walrus"])
    assert [(hit.sectionId, hit.score) for hit in hits] == [("front-pads", 1.0), ("rear-pads", 1.0)]


@pytest.mark.parametrize(("query", "boosted"), [("tire pressure", True), ("tyre cold pressure", False)])
def test_keyword_bonus_requires_a_contiguous_phrase(manual, monkeypatch, query, boosted):
    manual.sections = [
        _section("plain", "Procedure"),
        _section("keyword", "Procedure", keywords=["tyre pressure"]),
    ]
    index = LocalIndex()
    index.index(manual, [], [])
    monkeypatch.setattr(index.built(manual.id).bm25, "get_scores", lambda tokens: [2.0, 2.0])
    hits = index.query(manual.id, [query])
    if boosted:
        assert [hit.sectionId for hit in hits] == ["keyword", "plain"]
        assert hits[0].score > hits[1].score
    else:
        assert [hit.sectionId for hit in hits] == ["plain", "keyword"]
        assert hits[0].score == hits[1].score


def test_title_coverage_breaks_a_bm25_tie(manual, monkeypatch):
    manual.sections = [_section("broad", "Engine oil service schedule"), _section("specific", "Engine oil")]
    index = LocalIndex()
    index.index(manual, [], [])
    monkeypatch.setattr(index.built(manual.id).bm25, "get_scores", lambda tokens: [2.0, 2.0])
    hits = index.query(manual.id, ["engine oil"])
    assert [hit.sectionId for hit in hits] == ["specific", "broad"]
    assert hits[0].score > hits[1].score


def test_snippet_joins_inclusive_page_range_in_order_and_collapses_whitespace(manual):
    manual.sections = [_section("span", "Instructions", 1, pageEnd=3), _section("missing", "No page", 7)]
    index = LocalIndex()
    index.index(manual, [
        _page(manual.id, 4, "Outside the section."),
        _page(manual.id, 3, " End\t of instructions. "),
        _page(manual.id, 1, " First\n  instructions. "),
    ], [])
    assert index.snippet(manual.id, "span") == "First instructions. End of instructions."
    assert index.snippet(manual.id, "missing") == ""
    assert index.snippet(manual.id, "unknown") == ""


def test_snippet_default_and_explicit_character_limits(manual):
    text = "Detailed instructions. " * 30
    index = LocalIndex()
    index.index(manual, [_page(manual.id, 3, text)], [])
    assert index.snippet(manual.id, "oil") == text[:300]
    assert index.snippet(manual.id, "oil", chars=17) == text[:17]
    assert index.snippet(manual.id, "oil", chars=0) == ""
    assert index.snippet(manual.id, "oil", chars=1000) == text.strip()


@pytest.mark.parametrize("name", ["", " \t", "how do I", "quasar nebula"])
def test_spec_rejects_empty_or_nonmatching_names(local_index, manual, name):
    assert local_index.spec(manual.id, name) == []


def test_spec_matches_synonyms_and_preserves_the_printed_record(local_index, manual, specs):
    hits = local_index.spec(manual.id, "back axle bolt tightening")
    assert hits[0] == SpecHit(spec=specs[0], score=1.0)
    assert hits[0].score > hits[1].score
    assert all(0 < hit.score <= 1 for hit in hits)


def test_spec_kind_is_a_preference_when_a_name_matches(local_index, manual, specs):
    hits = local_index.spec(manual.id, "engine oil", kind="capacity")
    assert [hit.spec for hit in hits] == [specs[2], specs[3]]
    assert hits[0].score > hits[1].score > 0
    assert local_index.spec(manual.id, "quasar", kind="capacity") == []


def test_spec_can_search_by_kind_alone(local_index, manual, specs):
    hits = local_index.spec(manual.id, "", kind="pressure")
    assert [hit.spec for hit in hits] == specs[4:]
    assert all(0 < hit.score <= 1 for hit in hits)
    assert local_index.spec(manual.id, "", kind="clearance") == []


def test_spec_scores_distinct_query_terms_and_respects_limits(local_index, manual, specs):
    hits = local_index.spec(manual.id, "engine oil quasar")
    assert [hit.spec for hit in hits] == specs[2:4]
    assert hits[0].score == hits[1].score
    assert 0 < hits[0].score < 1, "an unmatched query word must cost score"
    assert local_index.spec(manual.id, "engine engine oil quasar") == hits
    assert local_index.spec(manual.id, "engine oil quasar", k=1) == hits[:1]
    assert local_index.spec(manual.id, "engine oil quasar", k=0) == []


@pytest.mark.parametrize(("manual_id", "query", "expected"), [
    (KTM, "change the engine oil", "engine-oil-change"),
    (KTM, "check tire pressure", "tire-pressure"),
    (KTM, "check front brake pads", "front-brake-pads"),
    (KTM, "check rear brake pads", "rear-brake-pads"),
    (BMW, "top up engine oil", "engine-oil-topup"),
    (BMW, "check front brake pads", "brake-pads-front"),
    (BMW, "check rear brake pads", "brake-pads-rear"),
    (BMW, "remove the rear wheel", "rear-wheel-removal"),
])
def test_seeded_manual_procedures_rank_first(manual_id, query, expected):
    hits = LocalIndex().query(manual_id, [query])
    assert hits and hits[0].sectionId == expected
    assert hits[0].score == pytest.approx(1.0)


@pytest.mark.parametrize("manual_id", [KTM, BMW])
def test_seeded_manual_rejects_unrelated_queries(manual_id):
    assert LocalIndex().query(manual_id, ["galactic quasar nebula"]) == []


# --------------------------------------------------------------------------------------
# The product contract: a rider types a couple of words next to the bike and the printed
# section they need is the first thing the index returns. Seeded KTM 390 Duke manual.
# --------------------------------------------------------------------------------------

RIDER_QUERIES = [
    ("change the oil", "engine-oil-change"),
    ("chain slack", "chain-tension-check"),
    ("tyre pressure", "tire-pressure"),
    ("front brake pads", "front-brake-pads"),
    ("fuse", "fuses"),
    ("battery charging", "battery-charge"),
    ("coolant level", "coolant-level"),
    ("rear wheel", "rear-wheel-remove"),
    ("headlight", "headlight-range"),
    ("torque", "engine-torques"),
]


@pytest.mark.parametrize(
    ("query", "expected"),
    [pytest.param(q, s, id=q.replace(" ", "-")) for q, s in RIDER_QUERIES],
)
def test_rider_query_ranks_the_printed_section_first(query, expected):
    hits = LocalIndex().query(KTM, [query])
    assert hits, f"{query!r} returned nothing at all"
    assert hits[0].sectionId == expected, [(h.sectionId, round(h.score, 2)) for h in hits[:3]]
    assert hits[0].score == pytest.approx(1.0)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_torque_ranks_either_printed_torque_table_first():
    """'torque' may legitimately land on the engine or the chassis table, but it must land."""
    hits = LocalIndex().query(KTM, ["torque"])
    assert hits, "a word every section prints must still reach its printed table"
    assert hits[0].sectionId in {"engine-torques", "chassis-torques"}


def test_bare_headlight_beats_the_fuse_assignment_table():
    """The fuse table on p.101-103 names every headlight circuit; the procedure must still win."""
    ids = [h.sectionId for h in LocalIndex().query(KTM, ["headlight"])]
    assert ids[0] == "headlight-range"
    assert "fuses" in ids, "the fuse table stays a candidate, just not the first one"


@pytest.mark.parametrize(
    ("queries", "components", "expected"),
    [
        (["removing the rear wheel", "rear wheel removal"], ["rear wheel"], "rear-wheel-remove"),
        (["tightening torque", "tightening torques", "threaded fasteners"], ["torque"], "engine-torques"),
        (["chassis tightening torques", "nut rear wheel spindle"], ["wheel spindle"], "chassis-torques"),
        (["adjusting the headlight range", "headlight beam"], ["headlight"], "headlight-range"),
    ],
)
def test_router_rephrasings_recover_the_queries_a_bare_word_loses(queries, components, expected):
    """What /ask actually sends: ask._route turns one rider word into 2-3 manual phrasings.
    These must rank first, otherwise the confidence floor has broken the live pipeline."""
    hits = LocalIndex().query(KTM, queries, components)
    assert hits and hits[0].sectionId == expected, [(h.sectionId, round(h.score, 2)) for h in hits[:3]]


def test_spec_rear_axle_returns_the_printed_rear_wheel_spindle_torque():
    hits = LocalIndex().spec(KTM, "rear axle", "torque")
    assert hits, "no torque spec for 'rear axle'"
    top = hits[0].spec
    assert top.kind == "torque"
    assert "rear wheel spindle" in top.name.lower()
    assert "Nm" in top.value
    assert top.value in top.quote
    assert top.page > 0
    assert all(h.spec.kind == "torque" for h in hits[:2])
    assert 0 < hits[0].score <= 1


def test_spec_rear_axle_beats_the_front_spindle():
    hits = LocalIndex().spec(KTM, "rear axle", "torque", k=8)
    names = [h.spec.name.lower() for h in hits]
    rear = next(i for i, n in enumerate(names) if "rear wheel spindle" in n)
    front = next((i for i, n in enumerate(names) if "spindle, front" in n), len(names))
    assert rear < front

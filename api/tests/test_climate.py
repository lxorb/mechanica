"""Climate Fit.

The demo anchor is real data: KTM 1390 Super Adventure R 2026 US, p. 215, which prints both the
antifreeze floor and the temperature-banded oil grade. The four negative controls (Bangkok, Dubai,
Miami, Delhi) run here on purpose - a cold rule that fires in Bangkok means the nearest-station join
or a comparator is broken, and that is a safety bug, not a cosmetic one.
"""

import gzip
import io

import pytest

KTM = "ktm-1390-super-adventure-r-2026-us-om"
ANCHOR_PAGE = 215

COLD = {"Minneapolis": (44.98, -93.26), "International Falls": (48.60, -93.40)}
WARM = {"Bangkok": (13.75, 100.50), "Dubai": (25.20, 55.27),
        "Miami": (25.76, -80.19), "Delhi": (28.61, 77.21)}


# --- the ISD reducer -------------------------------------------------------------------------------

def isd_line(temp_tenths: int, quality: str = "1", day: str = "20240115") -> str:
    """One ISD record, padded to the fixed-width control section. Temperature is 1-based 88-92."""
    head = "0100" + "727470" + "14918" + day + "1200" + "4" + "+0000" + "+00000" + "FM-15"
    head = head.ljust(87)
    sign = "+" if temp_tenths >= 0 else "-"
    return head + f"{sign}{abs(temp_tenths):04d}" + quality + "9999" + "9" + "\n"


def gz(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with gzip.open(buf, "wt", encoding="latin-1") as fh:
        fh.writelines(lines)
    return buf.getvalue()


def test_reduce_parses_tenths_and_drops_bad_quality():
    from app.climate import isd

    good = [isd_line(-300), isd_line(-100), isd_line(50)]
    bad = [isd_line(-460, quality="3"), isd_line(-500, quality="7")]
    row = isd.reduce_stream(gz(good + bad))
    assert row["obs"] == 3
    assert row["minC"] == -30.0
    assert row["maxC"] == 5.0
    assert row["below"]["-25"] == 1
    assert row["below"]["-40"] == 0

    loose = isd.reduce_stream(gz(good + bad), drop_bad_quality=False)
    assert loose["obs"] == 5
    assert loose["minC"] == -50.0  # the ablation: a suspect reading moves the annual minimum


def test_missing_temperature_is_skipped():
    from app.climate import isd

    line = isd_line(0).replace("+0000" + "1", "+99991", 1)
    assert isd.reduce_stream(gz([line])) is None


def test_merge_stores_shares_not_hours():
    from app.climate import isd

    rows = [{"obs": 100, "minC": -30.0, "maxC": 10.0, "meanC": 0.0, "year": 2024, "freezeThaw": 5,
             "p01C": -28.0, "p99C": 9.0,
             "below": {t: (10 if t == "-25" else 0) for t in ("5", "0", "-5", "-10", "-15", "-20", "-25", "-30", "-35", "-40")},
             "above": {"30": 0, "35": 0, "40": 0, "45": 0}}]
    merged = isd.merge_years(rows)
    assert merged["shareBelow"]["-25"] == pytest.approx(0.1)
    assert merged["readingsBelow"]["-25"] == 10
    assert "hoursBelow" not in merged  # derived at render time, never stored as a measurement


# --- pass A / pass C -------------------------------------------------------------------------------

def test_pass_a_finds_the_demo_anchor(store):
    from app.climate.rules import DETERMINISTIC, pass_a

    page = next(p for p in store.pages(KTM) if p.page == ANCHOR_PAGE)
    rules, _windows = pass_a(KTM, page.page, page.text, DETERMINISTIC)
    kinds = {r.ruleType for r in rules}
    assert "antifreeze_floor" in kinds and "oil_grade_band" in kinds

    floor = next(r for r in rules if r.ruleType == "antifreeze_floor")
    assert floor.thresholdC == -25.0
    assert floor.comparator == "at_or_below"
    assert "−25" in floor.quote  # U+2212, the character the PDF actually prints

    grades = {r.value: r for r in rules if r.ruleType == "oil_grade_band"}
    assert grades["SAE10W/50"].comparator == "at_or_above"
    assert grades["SAE5W/40"].comparator == "below"
    assert all(g.thresholdC == 0.0 for g in grades.values())


def test_every_rule_is_grounded_in_the_page_text(store):
    from app.climate.rules import DETERMINISTIC, grounded, pass_a

    pages = {p.page: p.text for p in store.pages(KTM)}
    for page, text in pages.items():
        rules, _ = pass_a(KTM, page, text, DETERMINISTIC)
        for rule in rules:
            assert grounded(rule.quote, text)


def test_grounding_rejects_an_invented_threshold(store):
    from app.climate.rules import grounded

    page = next(p for p in store.pages(KTM) if p.page == ANCHOR_PAGE)
    assert not grounded("Antifreeze protection to at least: -40 °C", page.text)


def test_a_printed_range_yields_the_weakest_end():
    from app.climate.rules import floor_of

    # "-25 ... -45 C" is a mixing window, not a promise of -45.
    assert floor_of("Check the antifreeze in the coolant. −25 … −45 °C (−13 … −49 °F)", -45.0) == -25.0
    assert floor_of("Antifreeze protection to at least: −25 °C (−13.0 °F)", -25.0) == -25.0


# --- verdicts --------------------------------------------------------------------------------------

def test_the_demo_anchor_breaches_at_international_falls():
    from app import climate

    got = climate.fit(KTM, *COLD["International Falls"])
    assert got is not None
    assert got.station.km < 10
    floor = next(v for v in got.verdicts if v.rule.ruleType == "antifreeze_floor")
    assert floor.status == "breached"
    assert floor.rule.page == ANCHOR_PAGE
    assert "-25" in floor.evidence or "−25" in floor.evidence
    cold_oil = next(v for v in got.verdicts
                    if v.rule.ruleType == "oil_grade_band" and v.rule.value == "SAE5W/40")
    assert cold_oil.status == "breached"
    assert cold_oil.rule.page == ANCHOR_PAGE


@pytest.mark.parametrize("city", sorted(WARM))
def test_no_cold_rule_fires_in_a_warm_city(city):
    """The negative controls. A cold verdict here is a broken join, not a surprise."""
    from app import climate

    got = climate.fit(KTM, *WARM[city])
    assert got is not None
    for v in got.verdicts:
        if v.rule.ruleType in ("antifreeze_floor", "cold_start"):
            assert v.status == "ok", f"{city}: {v.rule.ruleType} -> {v.status} ({v.evidence})"
        if v.rule.ruleType == "oil_grade_band" and v.rule.comparator in ("below", "at_or_below"):
            assert v.status == "ok", f"{city}: cold oil band fired ({v.evidence})"
    cold = [v for v in got.verdicts
            if v.rule.ruleType in ("antifreeze_floor", "cold_start", "salt_wash")
            or (v.rule.ruleType == "oil_grade_band" and v.rule.comparator in ("below", "at_or_below"))]
    assert not [v for v in cold if v.status == "breached"]


def test_a_distant_station_is_unknown_not_ok():
    from app.climate.models import ClimateRule
    from app.climate.stations import evaluate

    rule = ClimateRule(id="x", manualId=KTM, ruleType="antifreeze_floor", name="Antifreeze",
                       comparator="at_or_below", thresholdC=-25.0, value="-25 °C",
                       page=ANCHOR_PAGE, quote="Antifreeze protection to at least: -25 °C")
    row = {"id": "000000-99999", "name": "NOWHERE", "worstMinC": -40.0, "shareBelow": {"-25": 0.5},
           "readingsBelow": {"-25": 500}, "years": [2024]}
    assert evaluate(rule, row, 4.0).status == "breached"
    assert evaluate(rule, row, 400.0).status == "unknown"


def test_every_verdict_carries_a_page():
    from app import climate

    got = climate.fit(KTM, *COLD["Minneapolis"])
    assert got.verdicts
    for v in got.verdicts:
        assert v.rule.page > 0
        assert v.claim  # the manual's own line, never a sentence of ours


def test_dedupe_lands_on_the_page_that_prints_both_rules():
    from app.climate.stations import dedupe, rules_for

    kept = dedupe(rules_for(KTM))
    demo = [r for r in kept if r.ruleType in ("antifreeze_floor", "oil_grade_band")]
    assert {r.page for r in demo} == {ANCHOR_PAGE}
    assert len(kept) == len({(r.ruleType, r.comparator, r.thresholdC, r.thresholdM, r.value) for r in kept})


# --- the corpus-wide findings ------------------------------------------------------------------------

def test_every_antifreeze_floor_in_the_corpus_is_the_same_number():
    """Finding 1, as the built system measures it: one number, every market."""
    from app.climate.stations import manuals_with_rules, rules_for

    per_value = {}
    for manual_id in manuals_with_rules():
        for value in {r.thresholdC for r in rules_for(manual_id) if r.ruleType == "antifreeze_floor"}:
            per_value[value] = per_value.get(value, 0) + 1
    assert per_value, "no antifreeze rules in the committed rulebook"
    assert set(per_value) == {-25.0}
    assert per_value[-25.0] > 200


# --- endpoints ---------------------------------------------------------------------------------------

def test_station_endpoint(client):
    r = client.get("/climate/station", params={"lat": 48.60, "lon": -93.40})
    assert r.status_code == 200
    body = r.json()
    assert body["km"] < 10
    assert body["obs"] > 2000
    assert r.headers["cache-control"] == "public, max-age=60"


def test_station_by_name(client):
    r = client.get("/climate/station", params={"q": "ZUERICH-FLUNTERN"})
    assert r.status_code == 200
    assert r.json()["ctry"] == "CH"


def test_fit_endpoint_costs_nothing(client, store):
    before = len(store.costs())
    r = client.post("/climate/fit", json={"manualId": KTM, "lat": 48.60, "lon": -93.40})
    assert r.status_code == 200
    body = r.json()
    assert body["breached"] >= 1
    assert body["ms"] < 250
    assert len(store.costs()) == before, "a verdict must cost 0 tokens"


def test_fit_by_place(client):
    r = client.post("/climate/fit", json={"manualId": KTM, "place": "FALLS INTERNATIONAL"})
    assert r.status_code == 200
    assert r.json()["station"]["id"] == "727470-14918"


def test_fit_needs_a_location(client):
    assert client.post("/climate/fit", json={"manualId": KTM}).status_code == 422


def test_rules_endpoint(client):
    r = client.get(f"/climate/rules/{KTM}")
    assert r.status_code == 200
    rows = r.json()
    assert rows and all(row["quote"] for row in rows)
    assert {row["ruleType"] for row in rows} >= {"antifreeze_floor", "oil_grade_band"}


def test_rules_endpoint_is_empty_for_an_unknown_manual(client):
    assert client.get("/climate/rules/not-a-manual").json() == []


def test_anomalies_endpoint(client):
    r = client.get("/climate/anomalies")
    assert r.status_code == 200
    body = r.json()
    assert body["stations"] > 5000
    floor = next(row for row in body["rows"] if row["ruleType"] == "antifreeze_floor")
    assert floor["distinct"] == 1
    assert floor["spread"] == 0.0
    assert len(floor["markets"]) >= 5

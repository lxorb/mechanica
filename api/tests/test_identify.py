"""identify.photo: the vision reading is faked, the catalog ranking is the thing under test.

The ranking is what QA's KTM 390 Duke photo broke on - it came back as eight model years of a
KTM 690 Duke - so every test here is about the step after the model speaks: does the badge beat
the name, does the make constrain the pool, and are the alternatives four different motorcycles.
"""

import pytest

from app import identify as I
from app.models import Bike


def guess(**over) -> I.PhotoGuess:
    base = dict(
        kind="motorcycle",
        badge="",
        cylinders=0,
        displacementCc=0,
        family="",
        make="KTM",
        model="690 Duke",
        generation=I.Generation(yearFrom=0, yearTo=0),
        alternatives=[],
        confidence=0.95,
    )
    base.update(over)
    return I.PhotoGuess(**base)


def bike(make: str, model: str, year: int, kind: str | None = None) -> Bike:
    slug = f"{make} {model} {year}".lower().replace(" ", "-")
    return Bike(id=slug, make=make, model=model, year=year, market="EU", kind=kind)


@pytest.fixture
def catalog() -> list[Bike]:
    rows: list[Bike] = []
    for year in (2015, 2016, 2017):
        rows += [bike("KTM", "390 Duke", year), bike("KTM", "690 Duke", year)]
        rows += [bike("KTM", "690 Duke R", year), bike("KTM", "125 Duke", year)]
        rows += [bike("Honda", "CBR650R", year), bike("Honda", "CBR500R", year)]
        rows.append(bike("Chevrolet", "Corvette", year, kind="car"))
    return rows


def models(res, rows: list[Bike]) -> list[str]:
    by_id = {b.id: b for b in rows}
    out: list[str] = []
    for c in res.candidates:
        name = by_id[c.bikeId].model
        if name not in out:
            out.append(name)
    return out


# --- the QA bug ------------------------------------------------------------------------------


def test_the_badge_on_the_tank_beats_the_name_the_model_wrote(catalog):
    """QA's repro: the model says 690 Duke, the decal says 390 DUKE. The decal wins."""
    res = I.match(guess(badge="390 DUKE", displacementCc=390, family="Duke"), catalog)
    assert models(res, catalog)[0] == "390 Duke"


def test_without_a_badge_the_displacement_still_beats_the_name(catalog):
    res = I.match(guess(displacementCc=373, family="Duke"), catalog)
    assert models(res, catalog)[0] == "390 Duke"


def test_a_photo_with_no_evidence_keeps_the_name_the_model_wrote(catalog):
    res = I.match(guess(), catalog)
    assert models(res, catalog)[0] == "690 Duke"


# --- the alternatives strip ------------------------------------------------------------------


def test_the_answer_is_several_models_not_one_model_repeated(catalog):
    """The bug QA filed: eight candidates, all of them one wrong bike at eight model years."""
    res = I.match(guess(badge="390 DUKE", displacementCc=390), catalog)
    assert len(models(res, catalog)) >= 3


def test_the_second_card_is_a_different_bike_not_a_different_year(catalog):
    res = I.match(guess(badge="390 DUKE", displacementCc=390), catalog)
    first, second = res.candidates[0], res.candidates[1]
    by_id = {b.id: b for b in catalog}
    assert by_id[first.bikeId].model != by_id[second.bikeId].model


def test_a_trim_of_the_same_bike_is_not_offered_as_an_alternative(catalog):
    """"690 Duke" and "690 Duke R" are one bike to a mechanic; two cards for them is noise."""
    res = I.match(guess(), catalog)
    named = models(res, catalog)
    assert "690 Duke" in named and "690 Duke R" not in named


def test_a_different_size_is_never_folded_into_the_same_bike():
    assert I._same_bike("690duke", "690dukeabs")
    assert not I._same_bike("cbr650r", "cbr500r")
    assert not I._same_bike("390duke", "690duke")


def test_the_models_own_second_guess_reaches_the_strip(catalog):
    """Where the truth sat on half the photos this got wrong: the model's runner-up, which a
    near-spelling of its first answer used to push off the end of the list."""
    res = I.match(
        guess(
            make="Honda",
            model="CBR500R",
            badge="CBR",
            displacementCc=471,
            alternatives=[I.Alternative(make="Honda", model="CBR650R", confidence=0.14)],
        ),
        catalog,
    )
    assert "CBR650R" in models(res, catalog)[:3]


def test_candidates_carry_a_confidence_the_confirm_screen_can_paint(catalog):
    res = I.match(guess(badge="390 DUKE", displacementCc=390), catalog)
    assert all(0.0 <= c.confidence <= 1.0 for c in res.candidates)
    assert res.candidates[0].confidence > res.candidates[-1].confidence


def test_the_answer_stays_within_eight_candidates(catalog):
    res = I.match(guess(), catalog)
    assert 0 < len(res.candidates) <= I.MAX_CANDIDATES


# --- pool and kind ---------------------------------------------------------------------------


def test_a_car_photo_never_comes_back_as_a_motorcycle(catalog):
    res = I.match(guess(kind="car", make="Chevrolet", model="Corvette"), catalog)
    by_id = {b.id: b for b in catalog}
    assert all(by_id[c.bikeId].kind == "car" for c in res.candidates)


def test_the_make_constrains_the_pool(catalog):
    res = I.match(guess(make="Honda", model="CBR650R"), catalog)
    by_id = {b.id: b for b in catalog}
    assert {by_id[c.bikeId].make for c in res.candidates} == {"Honda"}


def test_a_make_the_catalog_does_not_carry_leaves_the_pool_whole(catalog):
    """Better a fuzzy answer from the whole catalog than an empty screen."""
    res = I.match(guess(make="Bimota", model="690 Duke"), catalog)
    assert res.candidates


def test_the_generation_band_picks_the_model_year(catalog):
    res = I.match(guess(generation=I.Generation(yearFrom=2017, yearTo=2017)), catalog)
    by_id = {b.id: b for b in catalog}
    assert by_id[res.candidates[0].bikeId].year == 2017


# --- the pieces ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "md,cc",
    [("390duke", 390), ("r1250gs", 1250), ("mt07", 700), ("cbr1000rr", 1000), ("z900rs", 900)],
)
def test_a_model_name_that_prints_its_displacement(md, cc):
    assert I._displacement(md) == cc


@pytest.mark.parametrize("md", ["yzfr7", "corvette", "ninja", "camry"])
def test_a_model_name_that_does_not(md):
    """"R7" is a series number on a 689 cc twin, so it must never be read as 7 cc."""
    assert I._displacement(md) is None


def test_a_badge_that_names_another_size_is_a_veto():
    assert I._badge_term("390 DUKE", "690duke") == -1.0
    assert I._badge_term("KTM 390 DUKE", "390duke") == 1.0
    assert I._badge_term("", "390duke") is None


def test_displacement_is_not_read_off_a_car_model_name():
    assert I._size_term(5700, "corvette", "car") is None


def test_the_makes_line_is_stable_and_deduplicated(catalog):
    line = I.makes_line(catalog)
    assert line == I.makes_line(list(reversed(catalog)))
    assert line == "Chevrolet, Honda, KTM"


def test_photo_reads_once_and_ranks_against_the_store(monkeypatch, catalog):
    """The route: one paid call, then the free ranking. Nothing else may reach OpenAI."""
    calls = []

    def fake(route, model, schema, system, user, **kw):
        calls.append(route)
        assert "390 DUKE" in system or "badge" in system
        return guess(badge="390 DUKE", displacementCc=390)

    monkeypatch.setattr(I.llm, "structured", fake)
    monkeypatch.setattr(I, "get_store", lambda: type("S", (), {"bikes": lambda self: catalog})())
    monkeypatch.setattr(I, "downscale", lambda data, mime: (data, "image/jpeg"))
    res = I.photo(b"not-really-a-jpeg", "image/jpeg")
    assert calls == ["identify.photo"]
    assert models(res, catalog)[0] == "390 Duke"

"""How a vehicle is matched to a manual: the exact id, then the alias, then another language.

Three passes, strictly ordered and never mixed. What is asserted here is the part that would rot
silently and hand a rider the wrong book: that an alias only ever merges two spellings of the same
model, that it never reaches across a make, a year or a model family, and that a non-English
handbook is offered only when no English one exists - and is labelled when it is.
"""

import pytest

from app.models import Bike, RegistryEntry
from app.registry import alias_key, bikes_from_registry


def entry(make, model, years, url, lang="en", market="EU", access="free", kind=None):
    return RegistryEntry(
        id=f"{make}-{model}-{years[0]}-{lang}".lower().replace(" ", "-"),
        make=make,
        model=model,
        years=years,
        market=market,
        type="owner",
        lang=lang,
        url=url,
        access=access,
        site="example.test",
        kind=kind,
    )


# --- alias_key ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("Multistrada V4S", "Multistrada V4 S"),
        ("FC250", "FC 250"),
        ("R Nine T", "R nineT"),
        ("X-Max 250", "XMAX 250"),
        ("TT-R125LWE", "TTR125LWE"),
        ("R&G", "R and G"),
        ("125 Exc Sixdays", "125 EXC Six Days"),
    ],
)
def test_two_spellings_of_one_model_share_a_key(a, b):
    assert alias_key("Yamaha", a, 2022) == alias_key("Yamaha", b, 2022)


@pytest.mark.parametrize(
    "a, b",
    [
        ("CB500F", "CB500X"),  # one letter apart, two different bikes
        ("RS 660", "RS 457"),
        ("YZ 125", "YZ 250"),
        ("Multistrada V4 S", "Multistrada V2 S"),
    ],
)
def test_different_models_never_share_a_key(a, b):
    assert alias_key("Honda", a, 2022) != alias_key("Honda", b, 2022)


def test_an_alias_never_crosses_a_make_or_a_year():
    assert alias_key("Honda", "CB500F", 2022) != alias_key("Yamaha", "CB500F", 2022)
    assert alias_key("Honda", "CB500F", 2022) != alias_key("Honda", "CB500F", 2023)


def test_a_stub_too_short_to_be_a_model_gets_no_key():
    assert alias_key("Yamaha", "R", 2022) == ""
    assert alias_key("Yamaha", "-", 2022) == ""
    assert alias_key("Yamaha", "", 2022) == ""


# --- the three passes, end to end -----------------------------------------------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A throwaway FileStore, so each case starts from an empty registry and an empty catalogue."""
    from app import store as store_mod

    fresh = store_mod.FileStore(tmp_path)
    monkeypatch.setattr(store_mod, "_store", fresh)
    monkeypatch.setattr(store_mod, "get_store", lambda: fresh)
    monkeypatch.setattr("app.registry.get_store", lambda: fresh)
    return fresh


def test_an_exact_id_wins_and_is_not_labelled(store):
    store.put_registry([entry("Ducati", "Monster 821", [2018], "https://x.test/monster.pdf")])
    bike = {b.id: b for b in bikes_from_registry()}["ducati-monster-821-2018"]
    assert bike.manualUrl == "https://x.test/monster.pdf"
    assert bike.lang is None  # English is the default; only a foreign offer is stamped


def test_a_differently_spelled_model_is_matched_by_alias(store):
    store.put_registry([entry("Ducati", "Multistrada V4 S", [2022], "https://x.test/msv4s.pdf")])
    store.put_bikes([Bike(id="ducati-multistradav4s-2022", make="Ducati", model="Multistrada V4S", year=2022, market="EU")])
    bike = {b.id: b for b in bikes_from_registry()}["ducati-multistradav4s-2022"]
    assert bike.manualUrl == "https://x.test/msv4s.pdf"
    assert bike.lang is None


def offered(bikes, bike_id):
    """What this vehicle is offered. A seed vehicle nothing covers is dropped from the derived
    catalogue rather than kept with an empty link, so "absent" and "no manualUrl" both mean
    the same thing here: nothing was found for it."""
    found = {b.id: b for b in bikes}.get(bike_id)
    return found.manualUrl if found else None


def test_an_alias_does_not_pull_in_a_neighbouring_model(store):
    store.put_registry([entry("Honda", "CB500X", [2022], "https://x.test/cb500x.pdf")])
    store.put_bikes([Bike(id="honda-cb500f-2022", make="Honda", model="CB500F", year=2022, market="EU")])
    assert offered(bikes_from_registry(), "honda-cb500f-2022") is None


def test_an_alias_does_not_pull_in_a_neighbouring_year(store):
    store.put_registry([entry("Honda", "CB 500 F", [2021], "https://x.test/cb500f21.pdf")])
    store.put_bikes([Bike(id="honda-cb500f-2022", make="Honda", model="CB500F", year=2022, market="EU")])
    assert offered(bikes_from_registry(), "honda-cb500f-2022") is None


def test_english_beats_a_foreign_manual_for_the_same_vehicle(store):
    store.put_registry(
        [
            entry("Suzuki", "Hayabusa", [2016], "https://x.test/busa_de.pdf", lang="de", market="DE"),
            entry("Suzuki", "Hayabusa", [2016], "https://x.test/busa_en.pdf", lang="en", market="GB"),
        ]
    )
    bike = {b.id: b for b in bikes_from_registry()}["suzuki-hayabusa-2016"]
    assert bike.manualUrl == "https://x.test/busa_en.pdf"
    assert bike.lang is None


def test_a_foreign_manual_is_offered_when_no_english_one_exists_and_is_labelled(store):
    store.put_registry([entry("Suzuki", "Hayabusa", [2016], "https://x.test/busa_de.pdf", lang="de", market="DE")])
    bike = {b.id: b for b in bikes_from_registry()}["suzuki-hayabusa-2016"]
    assert bike.manualUrl == "https://x.test/busa_de.pdf"
    assert bike.lang == "de"


def test_a_foreign_manual_is_reachable_through_an_alias_too(store):
    store.put_registry([entry("Yamaha", "XMAX 250", [2020], "https://x.test/xmax_it.pdf", lang="it", market="IT")])
    store.put_bikes([Bike(id="yamaha-x-max-250-2020", make="Yamaha", model="X-Max 250", year=2020, market="EU")])
    bike = {b.id: b for b in bikes_from_registry()}["yamaha-x-max-250-2020"]
    assert bike.manualUrl == "https://x.test/xmax_it.pdf"
    assert bike.lang == "it"


def test_the_vehicles_own_market_still_wins_over_the_language_order(store):
    for lang, market in (("ja", "JP"), ("fr", "FR"), ("de", "DE")):
        store.put_registry([entry("Suzuki", "GSX-R750", [2016], f"https://x.test/gsxr_{lang}.pdf", lang=lang, market=market)])
    store.put_bikes([Bike(id="suzuki-gsx-r750-2016", make="Suzuki", model="GSX-R750", year=2016, market="JP")])
    assert {b.id: b for b in bikes_from_registry()}["suzuki-gsx-r750-2016"].lang == "ja"


def test_the_language_fallback_orders_the_rest(store):
    """No row is printed for this bike's own market, so LANG_FALLBACK decides: the big European
    printings before the maker's home language."""
    for lang, market in (("ja", "JP"), ("fr", "FR"), ("de", "DE")):
        store.put_registry([entry("Suzuki", "GSX-R750", [2016], f"https://x.test/gsxr_{lang}.pdf", lang=lang, market=market)])
    store.put_bikes([Bike(id="suzuki-gsx-r750-2016", make="Suzuki", model="GSX-R750", year=2016, market="GB")])
    assert {b.id: b for b in bikes_from_registry()}["suzuki-gsx-r750-2016"].lang == "de"


def test_a_paid_or_non_pdf_row_is_never_offered_in_any_language(store):
    store.put_registry(
        [
            entry("BMW", "R 1250 GS", [2020], "https://x.test/gs_de.pdf", lang="de", access="subscription"),
            entry("BMW", "R 1250 GS", [2020], "https://x.test/gs_viewer", lang="fr"),
        ]
    )
    assert offered(bikes_from_registry(), "bmw-r-1250-gs-2020") is None


def test_a_car_row_is_never_offered_to_a_motorcycle_through_an_alias(store):
    store.put_registry([entry("Opel", "Corsa", [2020], "https://x.test/corsa_de.pdf", lang="de", kind="car")])
    store.put_bikes([Bike(id="opel-corsa-2020", make="Opel", model="Corsa", year=2020, market="EU", kind="car")])
    bike = {b.id: b for b in bikes_from_registry()}["opel-corsa-2020"]
    assert bike.manualUrl == "https://x.test/corsa_de.pdf"
    assert bike.kind == "car" and bike.lang == "de"

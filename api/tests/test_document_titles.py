"""A document title must never become a catalog vehicle.

The Harley SIP archive, Polaris and a few WordPress sites file a row under the *document's* name
rather than the bike's — "Parts Listing", "Universal Motorcycle Quick Start Guide", "The Legend
Begins". Deriving a vehicle from that minted `harley-davidson-the-legend-begins-1903` and 191 more
like it, which headed every gap list and read as garbage in search. The rows are real documents and
stay; only the derivation is refused.
"""

import pytest

from app.models import Bike, RegistryEntry
from app.registry import bikes_from_registry, is_document_title, names_a_vehicle


@pytest.mark.parametrize(
    "name",
    [
        "Parts Listing",
        "The Legend Begins",
        "Shop Dope/Service Bulletins",
        "Oper./Maint./Spec. Book",
        "Universal Motorcycle Quick Start Guide",
        "FLHRSE3 Owner's Manual",
        "15th Anniversary Edition Fat Boy Owner's Manual Supplement",
        "Brazil Owner's Manual Compliance Addendum",
        "Owners Handbook Warranty",
        "MOTORCYCLE RIDE COMMAND USER GUIDE FOR 7IN DISPLAY (PDF)",
        "To 1951 - Cross Index of H-D Part Nos.",
        "250RR INSTRUCTION MANUALEN",
    ],
)
def test_a_document_title_is_recognised(name):
    assert is_document_title(name) and not names_a_vehicle(name)


@pytest.mark.parametrize(
    "name",
    [
        # every one of these is a real model, and several contain a word the guard looks for
        "Road Glide",
        "Street Glide Special",
        "Sport Glide",
        "Tri Glide Ultra",
        "Fat Boy",
        "Electra Glide Standard",
        "LiveWire One",
        "Ninja 400",
        "V-Strom 800",
        "Multistrada V4 S",
        "Speed Triple 1200 RS",
        "Bonneville Bobber",
    ],
)
def test_a_real_model_is_left_alone(name):
    assert not is_document_title(name) and names_a_vehicle(name)


def test_all_models_and_blanks_still_derive_nothing():
    for name in ("All models", "all models", "", "   ", None):
        assert not names_a_vehicle(name)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app import store as store_mod

    fresh = store_mod.FileStore(tmp_path)
    monkeypatch.setattr(store_mod, "_store", fresh)
    monkeypatch.setattr(store_mod, "get_store", lambda: fresh)
    monkeypatch.setattr("app.registry.get_store", lambda: fresh)
    return fresh


def entry(model, years, url="https://x.test/a.pdf"):
    return RegistryEntry(
        id=f"hd-{model}-{years[0]}".lower().replace(" ", "-"),
        make="Harley-Davidson",
        model=model,
        years=years,
        market="US",
        type="owner",
        lang="en",
        url=url,
        access="free",
        site="serviceinfo.harley-davidson.com",
    )


def test_a_document_row_is_kept_but_derives_no_vehicle(store):
    store.put_registry([entry("Parts Listing", [1930, 1931, 1932]), entry("Road Glide", [2024])])
    ids = {b.id for b in bikes_from_registry()}
    assert "harley-davidson-road-glide-2024" in ids
    assert not any("parts-listing" in i for i in ids), "a document title must not mint a vehicle"
    assert len(store.registry()) == 2, "both rows stay in the registry - they are real documents"


def test_a_document_row_cannot_be_offered_to_a_seeded_vehicle_of_the_same_name(store):
    """The old derivation also re-admitted the junk vehicle through the pdf index, so it came back."""
    store.put_registry([entry("Parts Listing", [1930])])
    store.put_bikes([Bike(id="harley-davidson-parts-listing-1930", make="Harley-Davidson", model="Parts Listing", year=1930, market="US")])
    out = {b.id: b for b in bikes_from_registry()}
    assert "harley-davidson-parts-listing-1930" not in out

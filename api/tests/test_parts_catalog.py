"""The standard parts catalogue: the taxonomy file, who it applies to, what the manual says about
it, and the route that serves it."""

import json
from pathlib import Path

import pytest

from conftest import KTM

ART_INDEX = Path(__file__).resolve().parents[2] / "web" / "store" / "icons-parts-3d" / "index.json"

KINDS = {"motorcycle", "car"}
DRIVES = {"chain", "belt", "shaft"}
COOLINGS = {"liquid", "air"}
FUELS = {"efi", "carb", "petrol", "diesel"}


@pytest.fixture
def pc():
    from app import parts_catalog

    return parts_catalog


def bike(make, model, year, **extra):
    from app.models import Bike

    return Bike(id=f"{make}-{model}-{year}".lower(), make=make, model=model, year=year, market="EU", **extra)


# --- the file ------------------------------------------------------------


def test_taxonomy_is_a_valid_catalogue(pc):
    tax = pc.taxonomy()
    groups = {g["id"] for g in tax.groups}
    assert len(groups) == len(tax.groups), "duplicate group id"
    assert len(tax.parts) > 250

    ids = [p.id for p in tax.parts]
    assert len(ids) == len(set(ids)), "duplicate part id"
    for part in tax.parts:
        assert part.group in groups, part.id
        assert part.applies.kind in KINDS, part.id
        assert part.searchHint.strip(), part.id
        assert part.synonyms, part.id
        assert set(part.applies.drive or []) <= DRIVES, part.id
        assert set(part.applies.cooling or []) <= COOLINGS, part.id
        assert set(part.applies.fuel or []) <= FUELS, part.id
        assert set(part.applies.types or []) <= set(pc.TYPES), part.id
        assert set(part.applies.notTypes or []) <= set(pc.TYPES), part.id


def test_both_vehicle_kinds_are_covered(pc):
    per_kind = {k: 0 for k in KINDS}
    for part in pc.taxonomy().parts:
        per_kind[part.applies.kind] += 1
    assert per_kind["motorcycle"] >= 120
    assert per_kind["car"] >= 140


def test_every_icon_has_an_illustration(pc):
    art = set(json.loads(ART_INDEX.read_text(encoding="utf-8")))
    missing = sorted({p.icon for p in pc.taxonomy().parts} - art)
    assert not missing, f"no illustration for {missing}"


# --- who a part applies to -----------------------------------------------


def test_profile_reads_drive_cooling_and_fuel_off_the_name(pc):
    duke = pc.profile_of(bike("KTM", "390 Duke", 2024))
    assert (duke.kind, duke.drive, duke.cooling) == ("motorcycle", "chain", "liquid")
    assert "efi" in duke.fuel

    gs = pc.profile_of(bike("BMW", "R 1300 GS", 2025))
    assert gs.drive == "shaft"

    glide = pc.profile_of(bike("Harley-Davidson", "Street Glide", 2024))
    assert glide.drive == "belt"

    enfield = pc.profile_of(bike("Royal Enfield", "Classic 350", 2023))
    assert enfield.cooling == "air"

    old = pc.profile_of(bike("Suzuki", "DR 650", 1998))
    assert old.fuel == ["carb", "petrol"]

    vespa = pc.profile_of(bike("Vespa", "Primavera 125", 2024))
    assert (vespa.type, vespa.drive) == ("scooter", "belt")

    golf = pc.profile_of(bike("Volkswagen", "Golf TDI", 2019))
    assert (golf.kind, golf.fuel[0]) == ("car", "diesel")


def test_applicability_keeps_a_part_off_the_wrong_bike(pc):
    def ids(vehicle):
        return {p.id for p in pc.parts_for(pc.profile_of(vehicle))}

    chain_bike = ids(bike("KTM", "390 Duke", 2024))
    assert "m-chain" in chain_bike and "m-rear-sprocket" in chain_bike
    assert "m-final-drive-unit" not in chain_bike
    assert "m-drive-belt" not in chain_bike
    assert "m-carburettor" not in chain_bike  # 2024: fuel injected
    assert "m-thermostat" in chain_bike  # liquid cooled
    assert not any(i.startswith("c-") for i in chain_bike)  # never a car part

    shaft_bike = ids(bike("BMW", "R 1300 GS", 2025))
    assert "m-final-drive-unit" in shaft_bike and "m-final-drive-oil" in shaft_bike
    assert "m-chain" not in shaft_bike and "m-front-sprocket" not in shaft_bike

    air_bike = ids(bike("Royal Enfield", "Classic 350", 2023))
    assert "m-coolant" not in air_bike and "m-water-pump" not in air_bike

    scooter = ids(bike("Vespa", "Primavera 125", 2024))
    assert "m-clutch-plates" not in scooter and "m-gear-lever" not in scooter
    assert "m-variator-rollers" in scooter

    car = ids(bike("Volkswagen", "Golf TDI", 2019))
    assert "c-cabin-filter" in car and "c-glow-plug" in car
    assert "c-spark-plug" not in car  # diesel
    assert not any(i.startswith("m-") for i in car)


# --- the mentions pass on the KTM fixture --------------------------------


@pytest.fixture
def ktm(pc, store):
    manual = store.manual(KTM)
    return pc.catalog(KTM, store.bike(manual.bikeIds[0]), store=store, refresh=True)


def test_catalog_is_far_bigger_than_the_manuals_own_parts(pc, ktm, store):
    manual = store.manual(KTM)
    assert len(manual.parts) < 25
    assert len(ktm.parts) > 100
    assert ktm.fromManual == len(manual.parts)
    assert ktm.profile.drive == "chain"


def test_every_row_is_part_compatible_and_grouped(pc, ktm):
    order = pc.group_order()
    seen = [row.group for row in ktm.parts]
    assert seen == sorted(seen, key=order.index), "rows are not in group order"
    for row in ktm.parts:
        assert row.id and row.name
        assert row.icon and row.group in order
        assert isinstance(row.standard, bool)
        assert row.links, row.id
    assert {g.id for g in ktm.groups} <= set(order)
    assert sum(g.count for g in ktm.groups) == len(ktm.parts)


def test_the_manuals_own_parts_keep_their_printed_spec_and_come_first(pc, ktm, store):
    manual = store.manual(KTM)
    printed = {p.id: p for p in manual.parts}
    for row in ktm.parts:
        if row.id in printed:
            assert row.spec == printed[row.id].spec
            assert row.page == printed[row.id].page
    for group in {r.group for r in ktm.parts}:
        rows = [r for r in ktm.parts if r.group == group]
        first_standard = next((i for i, r in enumerate(rows) if r.id not in printed), len(rows))
        assert all(r.id in printed for r in rows[:first_standard])


def test_mentions_carry_a_real_page_and_a_quote_from_it(pc, ktm, store):
    manual = store.manual(KTM)
    mentioned = [r for r in ktm.parts if r.mentions]
    assert len(mentioned) > 40, "the mentions pass found almost nothing"
    for row in mentioned:
        for mention in row.mentions:
            assert 1 <= mention.page <= manual.pages, (row.id, mention.page)
            assert mention.quote.strip()

    by_id = {r.id: r for r in ktm.parts}
    # parts this manual has a whole section about
    assert by_id["m-front-brake-pads"].mentions
    assert by_id["m-valve-shim"].mentions
    # and a spec it prints as a value, not as a tightening torque
    assert "0.10" in by_id["m-valve-shim"].spec


def test_a_standard_row_never_buys_on_a_torque_figure(pc, ktm):
    for row in ktm.parts:
        if row.oem or row.spec == "":
            continue
        assert "Nm" not in row.spec, (row.id, row.spec)


def test_the_scan_is_cached_per_manual(pc, store, ktm):
    path = Path(store.root) / "parts_catalog" / f"{KTM}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["manualId"] == KTM
    assert data["mentions"] and data["map"]
    assert pc.cache_read(store, KTM)["version"] == data["version"]

    # a cache built against a different taxonomy is thrown away rather than served
    assert data["taxonomy"] == pc.fingerprint()
    pc.cache_write(store, KTM, {**data, "taxonomy": "stale", "mentions": {}})
    manual = store.manual(KTM)
    assert pc.scanned(manual, store)["taxonomy"] == pc.fingerprint()
    assert pc.scanned(manual, store)["mentions"]


# --- buying a row the manual never printed -------------------------------


def test_standard_part_is_buyable_by_its_search_hint(pc):
    part = pc.standard_part("m-fork-seals", bike("KTM", "390 Duke", 2024))
    assert part is not None
    assert part.name == "Fork oil seals"
    assert part.oem is None and part.page == 0
    assert part.links and all("390" in link.url.replace("%20", "") for link in part.links)
    assert pc.standard_part("not-a-part", None) is None


def test_offers_resolves_a_catalogue_id(store):
    from app import offers as offers_mod

    manual = store.manual(KTM)
    part, hint = offers_mod.resolve(manual, "m-fork-seals", store.bike(manual.bikeIds[0]))
    assert part.name == "Fork oil seals"
    assert hint == "fork oil seal set"
    query = offers_mod.build_query(part, store.bike(manual.bikeIds[0]), hint)
    assert "fork oil seal" in query.lower() and "390 Duke 2024" in query
    with pytest.raises(Exception):
        offers_mod.resolve(manual, "nothing-like-this", None)


def test_parts_catalog_adapter_returns_rows(store):
    from app.parts.catalog import catalog as rows

    out = rows(KTM, store.manual(KTM).bikeIds[0])
    assert len(out) > 100
    row = next(r for r in out if r["id"] == "m-fork-seals")
    assert row["searchHint"] and row["group"] == "suspension" and row["links"]
    assert rows("no-such-manual") == []


# --- the route -----------------------------------------------------------


def test_route_serves_the_catalogue(client, store):
    manual = store.manual(KTM)
    res = client.get("/parts/catalog", params={"manualId": KTM, "bikeId": manual.bikeIds[0]})
    assert res.status_code == 200
    body = res.json()
    assert body["manualId"] == KTM and body["bikeId"] == manual.bikeIds[0]
    assert body["profile"]["drive"] == "chain"
    assert len(body["parts"]) > 100
    assert body["groups"][0]["label"]
    row = body["parts"][0]
    assert {"id", "name", "spec", "page", "links", "group", "icon", "standard", "mentions"} <= set(row)


def test_route_without_a_bike_falls_back_to_the_manuals_own(client):
    res = client.get("/parts/catalog", params={"manualId": KTM})
    assert res.status_code == 200
    assert res.json()["bikeId"] == "ktm-390-duke-2024"


def test_route_404s_on_an_unknown_manual(client):
    assert client.get("/parts/catalog", params={"manualId": "nope"}).status_code == 404

"""Offers: the web search and every HEAD/GET are mocked, so what is under test is the promise -
no price without a URL, no dead link, cheapest first, and a day-old answer costs nothing."""

import time

import pytest

from app import offers as mod
from app.models import Bike, Link, Part
from conftest import KTM

PART = Part(
    id="spark-plug",
    name="Spark plug",
    spec="NGK LMAR8AI-10, electrode gap 0.8 mm",
    page=41,
    oem=None,
    links=[Link(shop="RevZilla", url="https://www.revzilla.com/search?query=ngk")],
)
BIKE = Bike(id="bmw-r-1300-gs-2025", make="BMW", model="R 1300 GS", year=2025, market="EU")

LINES = """\
RevZilla | NGK Laser Iridium LMAR8AI-10 | $19.99 | https://www.revzilla.com/motorcycle/ngk-lmar8ai-10 | single | new | free over $39 | in stock
FC-Moto | NGK Zuendkerze LMAR8AI-10 | 14,50 EUR | https://www.fc-moto.de/en/NGK-spark-plug-LMAR8AI-10 | single | new | unknown | in stock
Partzilla | NGK spark plug 94319 | $12.45 | https://www.partzilla.com/product/ngk/94319 | 4-pack | new | unknown | out of stock
Shady Shop | NGK LMAR8AI-10 | $9.00 | https://shadyshop.example/gone | single | new | unknown | unknown
NoPrice Moto | NGK LMAR8AI-10 | call us | https://noprice.example/product/plug | single | new | unknown | in stock
Reddit | someone paid $8 | $8.00 | https://www.reddit.com/r/motorcycles/comments/abc | unknown | unknown | unknown | unknown
"""

DEAD = "https://shadyshop.example/gone"


@pytest.fixture
def wired(monkeypatch, fresh_store):
    """One fake store, one fake search, one fake link checker."""
    monkeypatch.setattr(mod, "get_store", lambda: fresh_store)
    monkeypatch.setattr(mod.llm, "web_search", lambda *a, **k: (LINES, 0.021))
    monkeypatch.setattr(mod, "verify", lambda offers: [o for o in offers if o.url != DEAD])
    return fresh_store


def result(store, manual_id="m1", part_id="spark-plug"):
    return mod.OffersResult.model_validate(store.offers(manual_id, part_id))


# --- parsing --------------------------------------------------------------


def test_parses_one_line_per_offer():
    offers = mod.parse_lines(LINES)
    urls = {o.url for o in offers}
    assert "https://www.revzilla.com/motorcycle/ngk-lmar8ai-10" in urls
    assert len(offers) == 4  # the dead one is still in here; the no-price and the forum are not


def test_drops_an_offer_without_a_price():
    assert not any("noprice" in o.url for o in mod.parse_lines(LINES))


def test_drops_a_line_without_a_url():
    assert mod.parse_lines("RevZilla | NGK plug | $19.99 | no link here | single") == []


def test_drops_forums_and_search_pages():
    assert not any("reddit" in o.url for o in mod.parse_lines(LINES))
    assert mod.parse_lines("Amazon | plug | $9.99 | https://www.amazon.com/s?k=ngk+plug | x") == []


def test_reads_the_fields_around_price_and_url():
    offer = next(o for o in mod.parse_lines(LINES) if o.retailer == "RevZilla")
    assert (offer.price, offer.currency) == (19.99, "USD")
    assert offer.variant == "single"
    assert offer.condition == "new"
    assert offer.shipping == "free over $39"
    assert offer.inStock is True


def test_reads_out_of_stock():
    assert next(o for o in mod.parse_lines(LINES) if "partzilla" in o.url).inStock is False


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$19.99", (19.99, "USD")),
        ("US $1,234.56", (1234.56, "USD")),
        ("14,50 EUR", (14.5, "EUR")),
        ("1.500 €", (1500.0, "EUR")),
        ("£22.31", (22.31, "GBP")),
        ("from US $199.75", (199.75, "USD")),
        ("3800 JPY", (3800.0, "JPY")),
        ("call for price", None),
        ("free", None),
        ("19.99", None),  # a number with no currency is not a price
    ],
)
def test_parse_price(text, expected):
    assert mod.parse_price(text) == expected


# --- query ----------------------------------------------------------------


def test_query_prefers_the_printed_oem_number():
    part = PART.model_copy(update={"oem": "75011088030"})
    assert mod.build_query(part, BIKE) == "75011088030 Spark plug BMW R 1300 GS 2025"


def test_query_falls_back_to_the_spec_and_the_bike():
    query = mod.build_query(PART, BIKE)
    assert query.startswith("NGK LMAR8AI-10")
    assert query.endswith("BMW R 1300 GS 2025")


def test_query_drops_spec_fragments_that_are_not_the_product():
    part = PART.model_copy(update={"spec": "110/70 ZR 17 M/C 54W Michelin Power 6, 2.0 bar (29 psi)"})
    assert "bar" not in mod.build_query(part, BIKE)


def test_query_survives_a_bike_the_store_does_not_know():
    assert mod.build_query(PART, None).endswith("Spark plug")


# --- verification ---------------------------------------------------------


class _Client:
    def __init__(self, codes):
        self.codes = codes
        self.seen = []

    def request(self, method, url):
        self.seen.append((method, url))
        code = self.codes[url]
        if isinstance(code, Exception):
            raise code
        if isinstance(code, dict):
            code = code[method]
        return type("R", (), {"status_code": code})()


def test_alive_keeps_200_and_drops_404():
    client = _Client({"a": 200, "b": 404})
    assert mod.alive("a", client) is True
    assert mod.alive("b", client) is False


def test_alive_retries_with_get_when_head_is_refused():
    client = _Client({"a": {"HEAD": 405, "GET": 200}})
    assert mod.alive("a", client) is True
    assert [m for m, _ in client.seen] == ["HEAD", "GET"]


def test_alive_keeps_a_shop_that_blocks_robots():
    assert mod.alive("a", _Client({"a": {"HEAD": 403, "GET": 403}})) is True


def test_alive_drops_a_dead_host():
    assert mod.alive("a", _Client({"a": RuntimeError("no dns")})) is False


# --- the call itself ------------------------------------------------------


def test_offers_drops_the_dead_url_and_sorts_by_price(wired, monkeypatch):
    monkeypatch.setattr(mod, "get_store", lambda: wired)
    wired.put_manual(_manual())
    out = mod.offers("m1", "spark-plug", BIKE)
    assert [o.url for o in out.offers] == [
        "https://www.partzilla.com/product/ngk/94319",  # $12.45
        "https://www.fc-moto.de/en/NGK-spark-plug-LMAR8AI-10",  # 14.50 EUR -> $15.66
        "https://www.revzilla.com/motorcycle/ngk-lmar8ai-10",  # $19.99
    ]
    assert DEAD not in [o.url for o in out.offers]
    assert all(o.price > 0 and o.url.startswith("http") for o in out.offers)
    assert out.usd == 0.021


def test_offers_echoes_the_manual_links(wired):
    wired.put_manual(_manual())
    assert mod.offers("m1", "spark-plug", BIKE).links == PART.links


def test_offers_caches_and_serves_the_cached_answer_for_free(wired, monkeypatch):
    wired.put_manual(_manual())
    first = mod.offers("m1", "spark-plug", BIKE)
    assert wired.offers("m1", "spark-plug") is not None

    def boom(*a, **k):
        raise AssertionError("a warm call must not search")

    monkeypatch.setattr(mod.llm, "web_search", boom)
    warm = mod.offers("m1", "spark-plug", BIKE)
    assert warm.usd == 0.0
    assert [o.url for o in warm.offers] == [o.url for o in first.offers]


def test_offers_refetches_when_the_cache_is_a_day_old(wired):
    wired.put_manual(_manual())
    mod.offers("m1", "spark-plug", BIKE)
    stale = result(wired).model_copy(update={"fetchedAt": time.time() - mod.FRESH - 1})
    wired.put_offers("m1", "spark-plug", stale.model_dump())
    assert mod.offers("m1", "spark-plug", BIKE).usd == 0.021


def test_an_empty_answer_is_only_cached_for_an_hour(wired, monkeypatch):
    wired.put_manual(_manual())
    monkeypatch.setattr(mod.llm, "web_search", lambda *a, **k: ("nothing for sale", 0.019))
    assert mod.offers("m1", "spark-plug", BIKE).offers == []
    empty = result(wired).model_copy(update={"fetchedAt": time.time() - mod.FRESH_EMPTY - 1})
    wired.put_offers("m1", "spark-plug", empty.model_dump())
    monkeypatch.setattr(mod.llm, "web_search", lambda *a, **k: (LINES, 0.021))
    assert len(mod.offers("m1", "spark-plug", BIKE).offers) == 3


def test_a_failed_search_still_hands_back_the_search_links(wired, monkeypatch):
    wired.put_manual(_manual())

    def boom(*a, **k):
        raise RuntimeError("openai is down")

    monkeypatch.setattr(mod.llm, "web_search", boom)
    out = mod.offers("m1", "spark-plug", BIKE)
    assert out.offers == [] and out.links == PART.links
    assert wired.offers("m1", "spark-plug") is None  # an outage is never cached


def test_unknown_part_is_404(wired):
    wired.put_manual(_manual())
    with pytest.raises(Exception) as caught:
        mod.offers("m1", "nope", BIKE)
    assert getattr(caught.value, "status_code", None) == 404


def _manual():
    from app.models import Manual

    return Manual(
        id="m1",
        bikeIds=["bmw-r-1300-gs-2025"],
        file="x.pdf",
        pages=10,
        title="test",
        source="test",
        outline=[],
        sections=[],
        parts=[PART],
    )


# --- the store pair -------------------------------------------------------


def test_file_store_round_trips_one_part(fresh_store):
    assert fresh_store.offers("m1", "spark-plug") is None
    fresh_store.put_offers("m1", "spark-plug", {"manualId": "m1", "offers": []})
    assert fresh_store.offers("m1", "spark-plug") == {"manualId": "m1", "offers": []}
    assert fresh_store.offers("m1", "other") is None  # one blob per part, not per manual


def test_both_stores_answer_the_same_pair():
    from app.store import FileStore, Store
    from app.store_blob import BlobStore

    for store in (FileStore, BlobStore, Store):
        assert callable(getattr(store, "offers")) and callable(getattr(store, "put_offers"))


# --- the route ------------------------------------------------------------


def test_route_returns_offers(client, monkeypatch):
    monkeypatch.setattr(mod.llm, "web_search", lambda *a, **k: (LINES, 0.021))
    monkeypatch.setattr(mod, "verify", lambda offers: [o for o in offers if o.url != DEAD])
    from app.store import get_store

    manual = get_store().manual(KTM)
    part = manual.parts[0]
    body = client.post("/parts/offers", json={"manualId": KTM, "partId": part.id}).json()
    assert body["partId"] == part.id
    assert body["offers"] and all(o["price"] > 0 for o in body["offers"])
    assert body["query"]


def test_route_404s_on_an_unknown_manual(client):
    assert client.post("/parts/offers", json={"manualId": "nope", "partId": "x"}).status_code == 404

"""Offers: the web search and every HEAD/GET are mocked, so what is under test is the promise -
no price without a URL, no dead link, cheapest first, and a day-old answer costs nothing."""

import threading
import time

import pytest

from app import offers as mod
from app.models import Bike, Link, Manual, Part
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

# the same shop, three real products and two sizes of one of them
SAME_SHOP = """\
RevZilla | Motorex DOT 4 brake fluid | $12.99 | https://www.revzilla.com/motorcycle/motorex-dot-4?sku_id=1 | 250 ml | new | unknown | in stock
RevZilla | Motorex DOT 4 brake fluid | $21.99 | https://www.revzilla.com/motorcycle/motorex-dot-4?sku_id=2 | 1 l | new | unknown | in stock
RevZilla | Lucas synthetic DOT 4 | $6.49 | https://www.revzilla.com/motorcycle/lucas-dot-4 | 355 ml | new | unknown | in stock
RevZilla | Motorex DOT 4 brake fluid | $12.99 | https://www.revzilla.com/motorcycle/motorex-dot-4?sku_id=1 | 250 ml | new | unknown | in stock
"""

DEAD = "https://shadyshop.example/gone"


def fake_verify(offers, on_live=None):
    live = [o for o in offers if o.url != DEAD]
    for offer in live:
        if on_live:
            on_live(offer)
    return live


@pytest.fixture(autouse=True)
def no_lookups_left_over():
    mod._running.clear()
    yield
    mod._running.clear()


def fake_stream(text=LINES, usd=0.021, chunk=17, before=0.0):
    """The search as the model actually delivers it: text in pieces that do not respect line ends,
    then the bill. `before` is the dead time a real search spends looking things up first."""

    def stream(*a, **k):
        if before:
            time.sleep(before)
        for i in range(0, len(text), chunk):
            yield "delta", text[i : i + chunk]
        yield "usd", usd

    return stream


@pytest.fixture
def wired(monkeypatch, fresh_store):
    """One fake store, one fake streamed search, one fake link checker."""
    monkeypatch.setattr(mod, "get_store", lambda: fresh_store)
    monkeypatch.setattr(mod, "stream_lines", fake_stream())
    monkeypatch.setattr(mod.llm, "web_search", lambda *a, **k: (LINES, 0.021))
    monkeypatch.setattr(mod, "verify", fake_verify)
    monkeypatch.setattr(mod, "Checker", FakeChecker)
    # These tests are about what the finished answer contains. The early return is real behaviour
    # and has its own tests below; here it would only make every assertion a race.
    monkeypatch.setattr(mod, "ENOUGH", 999)
    return fresh_store


class FakeChecker:
    """The real Checker with the network taken out: same contract, same ordering."""

    def __init__(self, on_live):
        self.on_live = on_live
        self.seen = set()

    def add(self, offer):
        if offer.url in self.seen or offer.url == DEAD:
            return
        self.seen.add(offer.url)
        self.on_live(offer)

    def close(self):
        pass


def result(store, manual_id="m1", part_id="spark-plug"):
    return mod.OffersResult.model_validate(store.offers(manual_id, part_id))


def wait_for_cache(store, manual_id="m1", part_id="spark-plug", seconds=10.0):
    """The finished answer lands from the background thread; never sleep a fixed amount for it."""
    until = time.time() + seconds
    while time.time() < until:
        raw = store.offers(manual_id, part_id)
        if raw:
            return raw
        time.sleep(0.01)
    return None


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


def test_offers_drops_the_dead_url_and_sorts_by_price(wired):
    wired.put_manual(_manual())
    out = mod.offers("m1", "spark-plug", BIKE)
    assert [o.url for o in out.offers] == [
        "https://www.partzilla.com/product/ngk/94319",  # $12.45
        "https://www.fc-moto.de/en/NGK-spark-plug-LMAR8AI-10",  # 14.50 EUR -> $15.66
        "https://www.revzilla.com/motorcycle/ngk-lmar8ai-10",  # $19.99
    ]
    assert DEAD not in [o.url for o in out.offers]
    assert all(o.price > 0 and o.url.startswith("http") for o in out.offers)
    assert out.usd == 0.063 and out.complete is True  # three legs, one bill


def test_every_offer_carries_a_usd_price_beside_the_shop_price(wired):
    wired.put_manual(_manual())
    out = mod.offers("m1", "spark-plug", BIKE)
    euro = next(o for o in out.offers if o.currency == "EUR")
    assert (euro.price, euro.currency) == (14.5, "EUR")
    assert euro.priceUsd == round(14.5 * mod.TO_USD["EUR"], 2)
    assert [o.priceUsd for o in out.offers] == sorted(o.priceUsd for o in out.offers)
    assert all(o.priceUsd > 0 for o in out.offers)


def test_one_shop_may_hold_several_products_and_several_sizes(wired, monkeypatch):
    monkeypatch.setattr(mod, "stream_lines", fake_stream(text=SAME_SHOP))
    wired.put_manual(_manual())
    out = mod.offers("m1", "spark-plug", BIKE)
    assert {o.retailer for o in out.offers} == {"RevZilla"}
    assert [o.priceUsd for o in out.offers] == [6.49, 12.99, 21.99]  # the repeated line folded, nothing else


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
    assert mod.offers("m1", "spark-plug", BIKE).usd == 0.063


def test_an_empty_answer_is_only_cached_for_an_hour(wired, monkeypatch):
    wired.put_manual(_manual())
    monkeypatch.setattr(mod, "stream_lines", fake_stream(text="nothing for sale", usd=0.019))
    assert mod.offers("m1", "spark-plug", BIKE).offers == []
    empty = result(wired).model_copy(update={"fetchedAt": time.time() - mod.FRESH_EMPTY - 1})
    wired.put_offers("m1", "spark-plug", empty.model_dump())
    monkeypatch.setattr(mod, "stream_lines", fake_stream())
    assert len(mod.offers("m1", "spark-plug", BIKE).offers) == 3


def test_a_failed_search_still_hands_back_the_search_links(wired, monkeypatch):
    wired.put_manual(_manual())

    def boom(*a, **k):
        raise RuntimeError("openai is down")

    monkeypatch.setattr(mod, "stream_lines", boom)
    monkeypatch.setattr(mod.llm, "web_search", boom)
    out = mod.offers("m1", "spark-plug", BIKE)
    assert out.offers == [] and out.links == PART.links
    assert wired.offers("m1", "spark-plug") is None  # an outage is never cached


SECOND = PART.model_copy(update={"id": "brake-fluid", "name": "Brake fluid", "spec": "DOT 4"})


def _manual(parts=None):
    return Manual(
        id="m1",
        bikeIds=["bmw-r-1300-gs-2025"],
        file="x.pdf",
        pages=10,
        title="test",
        source="test",
        outline=[],
        sections=[],
        parts=parts or [PART],
    )


# --- the deadline ---------------------------------------------------------


def test_a_slow_search_answers_at_the_deadline_and_finishes_in_the_background(wired, monkeypatch):
    """A search that has not written a single line by the deadline still has to answer: the request
    leaves empty, the lookup keeps going, and the next click is the one that pays off."""
    wired.put_manual(_manual())
    monkeypatch.setattr(mod, "stream_lines", fake_stream(before=0.4))
    monkeypatch.setattr(mod, "DEADLINE", 0.05)

    out = mod.offers("m1", "spark-plug", BIKE)
    assert out.complete is False and out.offers == [] and out.usd == 0.0
    assert out.links == PART.links  # the rider still gets somewhere to click

    assert wait_for_cache(wired) is not None
    assert len(mod.offers("m1", "spark-plug", BIKE).offers) == 3


def test_the_request_leaves_as_soon_as_enough_shops_are_verified(wired, monkeypatch):
    """The point of streaming: the deadline is a ceiling, not the wait. Three verified offers with
    ENOUGH at 3 must come back in a fraction of a search that is still writing."""
    wired.put_manual(_manual())
    monkeypatch.setattr(mod, "stream_lines", fake_stream(text=LINES + "\n" + "x" * 4000, chunk=400))
    monkeypatch.setattr(mod, "ENOUGH", 3)
    monkeypatch.setattr(mod, "DEADLINE", 5.0)

    started = time.time()
    out = mod.offers("m1", "spark-plug", BIKE)
    assert time.time() - started < 4.0
    assert len(out.offers) >= 3


def test_an_offer_is_verified_while_the_search_is_still_writing(wired, monkeypatch):
    """Each line is handed to the checker as its newline lands, not after the last one."""
    wired.put_manual(_manual())
    order = []
    monkeypatch.setattr(mod, "stream_lines", fake_stream(chunk=9))

    class Watching(FakeChecker):
        def add(self, offer):
            order.append(offer.url)
            super().add(offer)

    monkeypatch.setattr(mod, "Checker", Watching)
    mod.offers("m1", "spark-plug", BIKE)
    assert order and order[0] == "https://www.revzilla.com/motorcycle/ngk-lmar8ai-10"


def test_a_stream_that_cannot_be_opened_falls_back_to_the_plain_search(wired, monkeypatch):
    wired.put_manual(_manual())

    def broken(*a, **k):
        raise RuntimeError("no stream here")
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(mod, "stream_lines", broken)
    out = mod.offers("m1", "spark-plug", BIKE)
    assert len(out.offers) == 3 and out.usd == 0.063


def test_a_half_finished_answer_is_never_served_from_the_cache(wired):
    wired.put_manual(_manual())
    wired.put_offers(
        "m1",
        "spark-plug",
        mod.OffersResult(
            manualId="m1", partId="spark-plug", query="q", offers=[], fetchedAt=time.time(), complete=False
        ).model_dump(),
    )
    assert mod.offers("m1", "spark-plug", BIKE).complete is True  # it searched instead


def test_two_clicks_on_one_part_share_a_single_search(wired, monkeypatch):
    """Two legs for the one lookup, and the second click joins it rather than starting another."""
    wired.put_manual(_manual())
    calls = []

    def counted(route, *a, **k):
        calls.append(route)
        return fake_stream(before=0.2)()

    monkeypatch.setattr(mod, "stream_lines", counted)
    monkeypatch.setattr(mod, "DEADLINE", 0.01)
    mod.offers("m1", "spark-plug", BIKE)
    mod.offers("m1", "spark-plug", BIKE)
    assert wait_for_cache(wired) is not None
    assert calls.count("offers") == 1 and calls.count("offers.fast") == len(mod.FAST_FOCUS)


def test_a_prefetch_does_not_pay_for_the_leg_that_answers_first(wired, monkeypatch):
    """Nobody waits on /parts/offers/warm, so it buys depth only."""
    wired.put_manual(_manual())
    calls = []
    monkeypatch.setattr(mod, "stream_lines", lambda route, *a, **k: (calls.append(route), fake_stream()())[1])
    mod.warm("m1", BIKE, ["spark-plug"])
    assert wait_for_cache(wired) is not None
    assert calls == ["offers"]


# --- warming --------------------------------------------------------------


def test_warm_queues_the_manuals_parts_and_skips_the_cached_ones(wired):
    wired.put_manual(_manual([PART, SECOND]))
    mod.offers("m1", "spark-plug", BIKE)  # this one is now cached

    out = mod.warm("m1", BIKE)

    assert out["cached"] == ["spark-plug"]
    assert out["queued"] == ["brake-fluid"]
    assert wait_for_cache(wired, part_id="brake-fluid") is not None
    assert mod.offers("m1", "brake-fluid", BIKE).complete is True


def test_warm_takes_the_ids_it_is_given_and_reports_unknown_ones(wired):
    wired.put_manual(_manual([PART, SECOND]))
    out = mod.warm("m1", BIKE, ["brake-fluid", "not-a-part"])
    assert out["queued"] == ["brake-fluid"] and out["unknown"] == ["not-a-part"]
    assert wait_for_cache(wired, part_id="brake-fluid") is not None


def test_warm_never_starts_more_than_a_dozen(wired):
    parts = [PART.model_copy(update={"id": f"p{n}"}) for n in range(20)]
    wired.put_manual(_manual(parts))
    out = mod.warm("m1", BIKE)
    assert len(out["queued"]) == mod.WARM_PARTS
    for part_id in out["queued"]:
        assert wait_for_cache(wired, part_id=part_id) is not None


def test_warm_404s_on_an_unknown_manual(wired):
    with pytest.raises(Exception) as caught:
        mod.warm("nope", BIKE)
    assert getattr(caught.value, "status_code", None) == 404


# --- catalogue ids --------------------------------------------------------


def test_a_catalogue_id_resolves_through_the_catalogue_module(wired, monkeypatch):
    """Parts the manual never prints come from GET /parts/catalog, with a searchHint instead of a
    printed spec. The module is another agent's, so this only has to survive its shape."""
    rows = [{"id": "chain-lube", "name": "Chain lube", "searchHint": "Motorex chain lube 500 ml"}]
    monkeypatch.setattr(mod, "_catalogue", lambda m, b, pid: mod._catalogue_row(rows, pid))
    wired.put_manual(_manual())
    out = mod.offers("m1", "chain-lube", BIKE)
    assert out.query == "Motorex chain lube 500 ml BMW R 1300 GS 2025"
    assert out.offers


def test_an_id_no_one_knows_is_still_a_404(wired):
    wired.put_manual(_manual())
    with pytest.raises(Exception) as caught:
        mod.offers("m1", "invented", BIKE)
    assert getattr(caught.value, "status_code", None) == 404


# --- entries cached before priceUsd existed -------------------------------


def _old_schema_doc():
    """What the store held before Offer carried priceUsd: no such key at all."""
    doc = mod.OffersResult(
        manualId="m1", partId="spark-plug", query="q", offers=[], fetchedAt=time.time()
    ).model_dump()
    doc["offers"] = [
        {"retailer": "FC-Moto", "title": "plug", "price": 14.5, "currency": "EUR",
         "url": "https://www.fc-moto.de/en/plug"},
        {"retailer": "Partzilla", "title": "plug", "price": 12.45, "currency": "USD",
         "url": "https://www.partzilla.com/product/ngk/94319"},
        {"retailer": "Webike", "title": "plug", "price": 3800.0, "currency": "JPY",
         "url": "https://www.webike.net/sd/1"},
    ]
    return doc


def test_a_cache_written_before_priceusd_is_repaired_on_read(wired):
    wired.put_manual(_manual())
    wired.put_offers("m1", "spark-plug", _old_schema_doc())

    out = mod.offers("m1", "spark-plug", BIKE)

    assert [o.priceUsd for o in out.offers] == [12.45, 15.66, 25.46]
    assert [o.retailer for o in out.offers] == ["Partzilla", "FC-Moto", "Webike"]
    assert [o.price for o in out.offers] == [12.45, 14.5, 3800.0]  # the shop's own price is untouched
    assert out.usd == 0.0  # mending a row never costs a search


def test_the_repair_is_written_back_and_does_not_repeat(wired, monkeypatch):
    wired.put_manual(_manual())
    wired.put_offers("m1", "spark-plug", _old_schema_doc())
    mod.offers("m1", "spark-plug", BIKE)

    assert all(o["priceUsd"] > 0 for o in wired.offers("m1", "spark-plug")["offers"])

    writes = []
    monkeypatch.setattr(wired, "put_offers", lambda *a: writes.append(a))
    assert len(mod.offers("m1", "spark-plug", BIKE).offers) == 3
    assert writes == []


def test_a_zero_price_row_is_not_invented_into_a_usd_price(wired):
    doc = _old_schema_doc()
    doc["offers"] = [{"retailer": "X", "title": "t", "price": 0.0, "currency": "USD",
                      "url": "https://x.example/p", "priceUsd": 0.0}]
    wired.put_manual(_manual())
    wired.put_offers("m1", "spark-plug", doc)
    assert mod.offers("m1", "spark-plug", BIKE).offers[0].priceUsd == 0.0


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
    monkeypatch.setattr(mod, "verify", fake_verify)
    from app.store import get_store

    manual = get_store().manual(KTM)
    part = manual.parts[0]
    body = client.post("/parts/offers", json={"manualId": KTM, "partId": part.id}).json()
    assert body["partId"] == part.id
    assert body["offers"] and all(o["price"] > 0 for o in body["offers"])
    assert body["query"]


def test_route_404s_on_an_unknown_manual(client):
    assert client.post("/parts/offers", json={"manualId": "nope", "partId": "x"}).status_code == 404

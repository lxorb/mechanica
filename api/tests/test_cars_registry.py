"""The car adapters, against canned payloads. No network: every HTTP helper is monkeypatched.

Two adapters are covered end to end because they are the two shapes every other car adapter copies:
GM parses one flat Solr document list, Ford walks a library page and then one detail page per
model year. What is asserted is the part that silently rots - the field mapping, the noise filter,
the `kind` flag and the `needsUa` that decides whether the ingest fetch succeeds.
"""

import json
from contextlib import contextmanager

import pytest

from app.registry import cars_ford, cars_gm

# --- GM -------------------------------------------------------------------------------------------

GM_DOCS = [
    {  # the real thing: one file filed under two models
        "path": "https://contentdelivery.ext.gm.com/content/dam/cope/en_us/public/a/22_CHEV_Tahoe_OM.pdf",
        "source": "aem",
        "channel": "OWNERS_MANUALS_BROWSE",
        "locale": "en_US",
        "file_type": "application/pdf",
        "category_key": ["2022", "CHEVROLET", "TAHOE", "SUBURBAN", "OWNERS_MANUALS_BROWSE"],
        "category_translated": ["2022", "Chevrolet", "Tahoe", "Suburban", "OWNERS_MANUALS_BROWSE"],
        "title_en": "2022 Chevrolet Tahoe/Suburban Owner Manual",
    },
    {  # inquira rows carry an internal staging path that does not resolve outside GM
        "path": "/resources/sites/GMA/content/staging/MANUALS/8000/MA8790/en_US/2.0/24_CAD_XT4_OM.pdf",
        "source": "inquira-live",
        "channel": "MANUALS",
        "locale": "en_US",
        "file_type": "application/pdf",
        "category_key": ["2024", "CADILLAC", "XT4", "OWNERS_MANUALS_BROWSE"],
        "category_translated": ["2024", "Cadillac", "XT4", "OWNERS_MANUALS_BROWSE"],
        "title_en": "2024 Cadillac XT4 Owner Manual",
    },
    {  # a quick-reference guide is a real PDF but not the handbook
        "path": "https://contentdelivery.ext.gm.com/content/dam/cope/en_us/public/a/GTK_2016_Escalade.pdf",
        "source": "aem",
        "channel": "QUICK_REFERENCE_MANUALS_BROWSE",
        "locale": "en_US",
        "file_type": "application/pdf",
        "category_key": ["2016", "CADILLAC", "ESCALADE", "QUICK_REFERENCE_MANUALS_BROWSE"],
        "category_translated": ["2016", "Cadillac", "Escalade", "QUICK_REFERENCE_MANUALS_BROWSE"],
        "title_en": "2016 Cadillac Escalade Convenience and Personalization Guide",
    },
    {  # an advisor/infotainment category must never be emitted as if it were a model
        "path": "https://contentdelivery.ext.gm.com/content/dam/cope/en_us/public/a/19_GMC_Sierra_OM.pdf",
        "source": "aem",
        "channel": "OWNERS_MANUALS_BROWSE",
        "locale": "en_US",
        "file_type": "application/pdf",
        "category_key": ["2019", "GMC", "SIERRA", "CAC", "INTELLILINK", "OWNERS_MANUALS_BROWSE"],
        "category_translated": ["2019", "GMC", "Sierra", "cac", "GMC IntelliLink", "OWNERS_MANUALS_BROWSE"],
        "title_en": "2019 GMC Sierra Owner Manual",
    },
    {  # a non-English locale is out of scope for the English ingest path
        "path": "https://contentdelivery.ext.gm.com/content/dam/cope/fr_ca/public/a/13_GMC_Yukon.pdf",
        "source": "aem",
        "channel": "OWNERS_MANUALS_BROWSE",
        "locale": "fr_CA",
        "file_type": "application/pdf",
        "category_key": ["2013", "GMC", "YUKON", "OWNERS_MANUALS_BROWSE"],
        "category_translated": ["2013", "GMC", "Yukon", "OWNERS_MANUALS_BROWSE"],
        "title_en": "2013 GMC Yukon Guide du proprietaire",
    },
]


@contextmanager
def _no_client(*a, **kw):
    yield object()


@pytest.fixture
def gm(monkeypatch):
    calls: list[dict] = []

    def fake_json(_client, _url, params=None, **_kw):
        calls.append(params or {})
        start = int((params or {}).get("start", 0))
        page = int((params or {}).get("rows", 500))
        return {"response": {"numFound": len(GM_DOCS), "docs": GM_DOCS[start : start + page]}}

    monkeypatch.setattr(cars_gm, "client", _no_client)
    monkeypatch.setattr(cars_gm, "get_json", fake_json)
    monkeypatch.setattr(cars_gm, "Throttle", lambda _rate: type("N", (), {"wait": lambda _s: None})())
    return calls


def test_gm_maps_one_file_onto_every_model_it_covers(gm):
    rows = list(cars_gm.rows())
    tahoe = [r for r in rows if r.model == "Tahoe"]
    suburban = [r for r in rows if r.model == "Suburban"]
    assert len(tahoe) == len(suburban) == 1
    assert tahoe[0].url == suburban[0].url  # one PDF, two catalog models
    assert tahoe[0].years == [2022]
    assert tahoe[0].make == "Chevrolet"
    assert tahoe[0].market == "US"
    assert tahoe[0].type == "owner"
    assert tahoe[0].access == "free"
    assert tahoe[0].id != suburban[0].id


def test_gm_every_row_is_a_fetchable_english_car(gm):
    rows = list(cars_gm.rows())
    assert rows, "adapter produced nothing"
    for r in rows:
        assert r.kind == "car"
        assert r.lang == "en"
        assert r.url.startswith("https://contentdelivery.ext.gm.com/")
        # the CDN 403s the default crawler UA, so the hint is what makes the ingest fetch work
        assert r.needsUa == "browser"


def test_gm_drops_unreachable_and_non_handbook_rows(gm):
    models = {r.model for r in cars_gm.rows()}
    assert "XT4" not in models  # source:inquira-live, internal staging host
    assert "Escalade" not in models  # quick-reference guide, not the owner's manual
    assert "Yukon" not in models  # fr_CA
    assert "Sierra" in models
    assert models.isdisjoint({"cac", "GMC IntelliLink", "OWNERS_MANUALS_BROWSE", "2019", "GMC"})


# --- Ford -----------------------------------------------------------------------------------------

FORD_LIBRARY = """
  <a href="/support/owner-manuals-details/super-duty/2023/">2023 Super Duty</a>
  <a href="/support/owner-manuals-details/f-150/2021/">2021 F-150</a>
  <a href="/support/owner-manuals-details/f-150/2021/">dup</a>
"""

_DOC = '\\"title\\":\\"{title}\\",\\"link\\":\\"{link}\\",\\"category\\":\\"Owner Manual\\"'
FORD_DETAIL = "".join(
    _DOC.format(title=t, link=u)
    for t, u in [
        ("Owner’s Manual Printing 1 (PDF)", "https://www.fordservicecontent.com/Ford_Content/Catalog/owner_information/a_om.pdf"),
        ("Warranty Guide Printing 8", "https://www.fordservicecontent.com/Ford_Content/Catalog/owner_information/a_wty.pdf"),
        ("Owner’s Manual Printing 1 (PDF)", "https://www.fordservicecontent.com/Ford_Content/Catalog/owner_information/a_om.pdf"),
    ]
)


@pytest.fixture
def ford(monkeypatch):
    asked: list[str] = []

    def fake_text(_client, url, **_kw):
        asked.append(url)
        if url.endswith("/owner-manuals-library"):
            return FORD_LIBRARY if "www.ford.com" in url else ""
        return FORD_DETAIL

    monkeypatch.setattr(cars_ford, "client", _no_client)
    monkeypatch.setattr(cars_ford, "get_text", fake_text)
    monkeypatch.setattr(cars_ford.THROTTLE, "wait", lambda: None)
    return asked


def test_ford_walks_the_library_then_one_page_per_model_year(ford):
    rows = list(cars_ford.rows())
    detail = [u for u in ford if "owner-manuals-details" in u and not u.endswith("library")]
    assert sorted(detail) == [
        "https://www.ford.com/support/owner-manuals-details/f-150/2021/",
        "https://www.ford.com/support/owner-manuals-details/super-duty/2023/",
    ]
    assert {(r.model, r.years[0]) for r in rows} == {("Super Duty", 2023), ("F-150", 2021)}


def test_ford_keeps_the_handbook_and_nothing_else(ford):
    rows = list(cars_ford.rows())
    assert len(rows) == 2, [r.title for r in rows]  # warranty guide dropped, duplicate link collapsed
    for r in rows:
        assert r.kind == "car"
        assert r.make == "Ford"
        assert r.market == "US"
        assert r.url.endswith("a_om.pdf")
        # Akamai drops Chrome and Googlebot UAs on this host; the default crawler UA is the one
        # that works, so a needsUa hint here would break the ingest fetch.
        assert r.needsUa is None


def test_ford_pretty_prints_the_slug():
    assert cars_ford._pretty("super-duty") == "Super Duty"
    assert cars_ford._pretty("f-150") == "F-150"
    assert cars_ford._pretty("mustang-mach-e") == "Mustang Mach-E"


# --- the fragments the adapters check in ------------------------------------------------------------


def test_car_fragments_are_valid_and_tagged(tmp_path):
    from app.config import settings
    from app.models import RegistryEntry

    # *.drop.json sits next to the fragments and is a plain list of ids for the merge to retract.
    files = [p for p in sorted((settings.data_dir / "registry-fragments").glob("cars-*.json")) if not p.name.endswith(".drop.json")]
    assert files, "no car fragments checked in"
    total = 0
    for path in files:
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert rows, f"{path.name} is empty"
        for raw in rows:
            entry = RegistryEntry.model_validate(raw)
            assert entry.kind == "car", f"{path.name}: {entry.id} is not tagged as a car"
            assert entry.url.startswith("http")
            total += 1
    assert total > 1000

"""Toyota Japan: the production-month range that becomes the model years, and the document name
that becomes the docKind. Pure functions over the portal's own markup, so no network is needed.

The year parse is the part that matters: `manual.toyota.jp` files one handbook per production
*range*, so a row that kept only the first year would leave every later car in the range with
nothing, and a row that opened the range too far would claim years Toyota never printed.
"""

import datetime

import pytest

from app.registry.cars_toyota_jp import _kind, _years

NEXT_YEAR = datetime.date.today().year + 1


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2013年02月～2014年11月", [2013, 2014]),
        ("2011年12月～2013年01月", [2011, 2012, 2013]),
        ("2015年04月～2015年11月", [2015]),
        ("2020年05月", [2020]),
    ],
)
def test_a_closed_production_range_covers_every_year_in_it(text, expected):
    assert _years(text, newest=False) == expected


def test_the_newest_open_range_runs_to_next_model_year():
    """`2026年07月～` is the book for the car on sale now, so it has to cover the year ahead too."""
    assert _years("2026年07月～", newest=True) == list(range(2026, NEXT_YEAR + 1)) or NEXT_YEAR < 2026


def test_an_open_range_that_is_not_the_newest_is_not_extended():
    assert _years("2013年02月～", newest=False) == [2013]


def test_a_range_with_no_year_produces_no_row():
    assert _years("生産年月不明", newest=True) == []
    assert _years("", newest=False) == []


@pytest.mark.parametrize(
    "title, kind",
    [
        ("取扱説明書", "owner"),
        ("取扱説明書 （ハイブリッド車）", "owner"),
        # Toyota's newest PDFs are the printed excerpt, not the complete book
        ("取扱説明書 抜粋版（ハイブリッド車）", "quickstart"),
        ("ナビゲーションシステム 取扱説明書", "infotainment"),
        ("ディスプレイオーディオ 取扱説明書", "infotainment"),
        ("アクセサリー", "supplement"),
    ],
)
def test_a_document_name_becomes_a_dockind(title, kind):
    assert _kind(title) == kind

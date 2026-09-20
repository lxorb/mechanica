"""Honda Japan: how a romanised folder name becomes a model name, and how a category becomes a
docKind. Both are pure functions over the portal's own `search.json`, so no network is needed.

This is the part that would rot silently: every name in that file is Japanese, `slug()` strips
non-ASCII, and a bad split would file 119 nameplates under a handful of ids.
"""

import pytest

from app.registry.honda_jp import _kind, families, model_name

# The real folder list, trimmed to the shapes that exercise every branch.
FOLDERS = {
    "accord",
    "accordtourer",
    "accordplug-inhybrid",
    "actystreet",
    "actytruck",
    "actyvan",
    "avancier",
    "civic",
    "civictyper",
    "civictyperlimitededition",
    "clarityfuelcell",
    "clarityphev",
    "cr-v",
    "cr-vhybrid",
    "beat",
}
KNOWN = families(FOLDERS)


@pytest.mark.parametrize(
    "folder, expected",
    [
        ("accord", "Accord"),
        ("accordtourer", "Accord Tourer"),
        ("accordplug-inhybrid", "Accord Plug-in Hybrid"),
        ("avancier", "Avancier"),  # nothing to split, one word
        ("beat", "Beat"),
        ("cr-v", "CR-V"),  # a hyphen Honda spells is kept, not turned into a space
        ("cr-vhybrid", "CR-V Hybrid"),
        ("civictyper", "Civic Type R"),
        ("civictyperlimitededition", "Civic Type R Limited Edition"),
    ],
)
def test_a_folder_name_becomes_the_nameplate(folder, expected):
    assert model_name(folder, KNOWN) == expected


def test_a_family_that_is_not_a_folder_is_found_from_the_shared_prefix():
    """`acty` and `clarity` are never folders of their own; two siblings each are what reveal them."""
    assert "acty" in KNOWN and "clarity" in KNOWN
    assert model_name("actytruck", KNOWN) == "Acty Truck"
    assert model_name("clarityphev", KNOWN) == "Clarity PHEV"


def test_a_prefix_shorter_than_four_characters_is_not_a_family():
    assert families({"cr-v", "cr-z"}) == {"cr-v", "cr-z"}  # "cr-" is too short to split on


def test_every_folder_still_gets_its_own_name():
    """The split must stay injective: two nameplates that collapse to one name lose a whole model."""
    names = [model_name(f, KNOWN) for f in sorted(FOLDERS)]
    assert len(set(names)) == len(FOLDERS)


@pytest.mark.parametrize(
    "category, kind",
    [
        ("オーナーズマニュアル", "owner"),
        ("オーナーズガイド", "owner"),
        ("インターナビシステム", "infotainment"),
        # the navigation book calls itself a digital owner's manual; it is still the navigation book
        ("インターナビシステム（デジタルオーナーズマニュアル）", "infotainment"),
        ("簡単ナビガイド", "quickstart"),
        ("追補版", "supplement"),
        ("ETC車載器", "supplement"),
        ("車いす仕様車", "supplement"),
        ("Honda CONNECT ディスプレイ", "infotainment"),
    ],
)
def test_a_document_category_becomes_a_dockind(category, kind):
    assert _kind(category) == kind

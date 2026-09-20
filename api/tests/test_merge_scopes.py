"""`merge-fragments` retraction: a fragment may only replace a scope it does not share.

Two adapters can write one site — `triumph.py` and `triumph_pdf.py` both write
`triumphtechnicalinformation.com` — and then neither fragment is the whole truth for it. Replacing
one fragment's scope used to delete the other's rows whenever they were not merged together; in
cycle 5 that retracted 16,124 rows in one run. These cases pin the guard that stops it.
"""

import json

import pytest

from app.models import RegistryEntry
from tools import registry as cli


def entry(eid, site, model, url, kind_hint=None):
    return RegistryEntry(
        id=eid,
        make="Triumph",
        model=model,
        years=[2024],
        market="GB",
        type="owner",
        lang="en",
        url=url,
        access="free",
        site=site,
        docKind=kind_hint,
    ).model_dump(exclude_none=True)


@pytest.fixture
def merge(tmp_path, monkeypatch):
    """A throwaway store and fragment directory; returns a runner for the CLI command."""
    from app import store as store_mod

    fresh = store_mod.FileStore(tmp_path / "data")
    frag = tmp_path / "fragments"
    frag.mkdir(parents=True)
    monkeypatch.setattr(store_mod, "_store", fresh)
    monkeypatch.setattr(store_mod, "get_store", lambda: fresh)
    monkeypatch.setattr("app.registry.get_store", lambda: fresh)
    monkeypatch.setattr(cli, "get_store", lambda: fresh)
    monkeypatch.setattr(cli, "FRAGMENTS", frag)

    def write(name, rows):
        (frag / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")

    def run(*argv):
        cli.main(["merge-fragments", *argv])
        return {e.id for e in fresh.registry()}

    return write, run, fresh


def test_replacing_a_shared_scope_keeps_the_other_fragments_rows(merge):
    write, run, _store = merge
    write("handbooks", [entry("t-1", "example.test", "Bonneville", "https://example.test/1.pdf")])
    write("everything-else", [entry("t-2", "example.test", "Bonneville", "https://example.test/2.pdf", "spec")])
    run()
    # `handbooks` is re-keyed wholesale: same files, new ids. It owns none of the scope on its own.
    write("handbooks", [entry("t-1-new", "example.test", "Bonneville", "https://example.test/1.pdf")])
    ids = run("--replace", "handbooks")
    assert "t-2" in ids, "the co-owner's row must survive a replace of the scope it shares"
    assert "t-1-new" in ids and "t-1" not in ids, "the replaced fragment's own rows are still re-keyed"


def test_a_shared_scope_is_not_replaced_when_a_co_owner_is_held_back(merge, capsys):
    write, run, _store = merge
    write("handbooks", [entry("t-1", "example.test", "Bonneville", "https://example.test/1.pdf")])
    write("everything-else", [entry("t-2", "example.test", "Bonneville", "https://example.test/2.pdf", "spec")])
    run()
    write("handbooks", [entry("t-1-new", "example.test", "Bonneville", "https://example.test/1.pdf")])
    ids = run("--replace", "handbooks", "--skip", "everything-else")
    assert "t-2" in ids and "t-1" in ids, "nothing may be retracted while a co-owner is skipped"
    assert "refusing scope example.test" in capsys.readouterr().err


def test_a_scope_one_fragment_owns_alone_is_still_replaced(merge):
    write, run, _store = merge
    write("solo", [entry("s-1", "solo.test", "Tiger", "https://solo.test/1.pdf")])
    run()
    write("solo", [entry("s-2", "solo.test", "Tiger", "https://solo.test/2.pdf")])
    assert run("--replace", "solo") == {"s-2"}, "an unshared scope is the fragment's to replace"


def test_the_auto_replace_guess_never_fires_on_a_shared_scope(merge, capsys):
    """The heuristic is a guess. On a shared scope it must stand down rather than delete a sibling."""
    write, run, _store = merge
    write("handbooks", [entry(f"t-{n}", "example.test", "Bonneville", f"https://example.test/{n}.pdf") for n in range(10)])
    write("everything-else", [entry("keep-me", "example.test", "Bonneville", "https://example.test/0.pdf", "spec")])
    run()
    # Same ten files, all ten ids new: exactly the shape that used to trigger the auto-replace.
    write("handbooks", [entry(f"new-{n}", "example.test", "Bonneville", f"https://example.test/{n}.pdf") for n in range(10)])
    ids = run()
    assert "keep-me" in ids
    assert "NOT replacing, it shares a scope" in capsys.readouterr().out

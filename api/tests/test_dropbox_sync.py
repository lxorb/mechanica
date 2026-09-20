"""The shop's Dropbox folder -> the same ingest an OEM manual goes through.

No token exists on this machine, so every test drives the module the way production will: a fake
Dropbox behind httpx.MockTransport, a real cursor, a real %PDF body, and ingest stubbed out so the
suite tests the sync path rather than PyMuPDF. The four routes checked here are exactly the four
`api/app/dropbox_sync.py` documents against the published spec:
files/list_folder, files/list_folder/continue, files/download, and the webhook handshake.
"""

import hashlib
import hmac
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app import dropbox_sync as dbx
from conftest import DATA_DIR

PDF = b"%PDF-1.4\nfake service manual\n%%EOF\n"
SECRET = "app-secret"


# ---------------------------------------------------------------- a fake Dropbox


class FakeDropbox:
    """list_folder / continue / download / longpoll with the real JSON shapes.

    Pages are served in order and list_folder rewinds, so a second pass against a fresh instance
    behaves like a folder that still holds the same files - which is the case under test."""

    def __init__(self, pages: list[list[dict]], body: bytes = PDF, bodies: dict[str, bytes] | None = None):
        self.pages = pages
        self.body = body
        self.bodies = bodies or {}
        self.at = 0
        self.calls: list[tuple[str, dict]] = []
        self.auth: dict[str, str | None] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        route = request.url.path.removeprefix("/2/")
        self.auth[route] = request.headers.get("Authorization")
        if route == "files/download":
            arg = json.loads(request.headers["Dropbox-API-Arg"])
            self.calls.append((route, arg))
            return httpx.Response(200, content=self.bodies.get(arg["path"], self.body))
        arg = json.loads(request.content or b"{}")
        self.calls.append((route, arg))
        if route == "files/list_folder":
            self.at = 0
            return httpx.Response(200, json=self._page())
        if route == "files/list_folder/continue":
            if arg["cursor"] == "stale":
                return httpx.Response(409, json={"error": {".tag": "reset"}, "error_summary": "reset/"})
            return httpx.Response(200, json=self._page())
        if route == "files/list_folder/longpoll":
            return httpx.Response(200, json={"changes": False})
        return httpx.Response(404, json={"error_summary": "unknown"})

    def _page(self) -> dict:
        entries = self.pages[self.at] if self.at < len(self.pages) else []
        self.at += 1
        return {"entries": entries, "cursor": f"cur-{self.at}", "has_more": self.at < len(self.pages)}


def entry(name: str, *, file_id: str | None = None, rev: str = "a1") -> dict:
    return {
        ".tag": "file",
        "name": name.rsplit("/", 1)[-1],
        "id": file_id or f"id:{name}",
        "path_display": name,
        "path_lower": name.lower(),
        "rev": rev,
        "size": len(PDF),
    }


@pytest.fixture
def dropbox(monkeypatch, tmp_path):
    """A token, a private data dir with the real catalog in it, no watcher thread, and every HTTP
    call on a MockTransport. The catalog is copied rather than shared because a shop's manual
    re-points a bike, and no other test may see that."""
    shutil.copy(DATA_DIR / "bikes.json", tmp_path / "bikes.json")
    monkeypatch.setattr(dbx.settings, "dropbox_token", f"token-123\n{SECRET}")
    monkeypatch.setattr(dbx.settings, "data_dir", tmp_path)
    monkeypatch.setenv("DROPBOX_FOLDER", "/Manuals")
    monkeypatch.setattr(dbx, "start", lambda: False)
    dbx._makes = (0.0, [])

    def make(pages, body: bytes = PDF, bodies: dict[str, bytes] | None = None) -> FakeDropbox:
        fake = FakeDropbox(pages, body, bodies)
        monkeypatch.setattr(
            dbx, "_client", lambda longpoll=False: httpx.Client(transport=httpx.MockTransport(fake.handler))
        )
        return fake

    yield make
    dbx._makes = (0.0, [])


@pytest.fixture
def ingested(monkeypatch):
    """ingest.run is the product; here it only has to say it succeeded."""
    seen: list[tuple] = []

    def run(job_id, source, manual_id, bike_ids, make, model, year, **kw):
        seen.append((source, manual_id, make, model, year))
        from app.models import IngestJob
        from app.store import get_store

        get_store().put_job(IngestJob(id=job_id, manualId=manual_id, status="done", pages=12, done=12))

    monkeypatch.setattr(dbx.ingest_mod, "run", run)
    return seen


# ---------------------------------------------------------------- configuration


def test_disabled_without_a_token(monkeypatch):
    monkeypatch.setattr(dbx.settings, "dropbox_token", None)
    assert dbx.enabled() is False
    assert dbx.token() is None
    assert dbx.sync_once() == {"enabled": False, "queued": 0, "reason": "no token"}


def test_secret_file_carries_token_then_app_secret(monkeypatch):
    monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)
    monkeypatch.setattr(dbx.settings, "dropbox_token", "  tok\nsec  \n")
    assert (dbx.token(), dbx.app_secret()) == ("tok", "sec")


def test_folder_root_is_empty_string_not_slash(monkeypatch):
    """Dropbox rejects "/" for the root of an app folder."""
    monkeypatch.setenv("DROPBOX_FOLDER", "/")
    assert dbx.folder() == ""
    monkeypatch.setenv("DROPBOX_FOLDER", "/Manuals/")
    assert dbx.folder() == "/Manuals"


def test_config_route_hides_the_button_without_a_key(client):
    body = client.get("/dropbox/config").json()
    assert body == {"enabled": False, "folder": "/", "webhook": False, "watching": False}


def test_sync_route_503s_without_a_token(client):
    assert client.post("/dropbox/sync").status_code == 503


# ---------------------------------------------------------------- path -> bike


@pytest.mark.parametrize(
    "path,expect",
    [
        ("/Manuals/Yamaha MT-07 2019 service manual.pdf", ("Yamaha", "MT 07", 2019)),
        ("/Manuals/Yamaha/MT-07/2019.pdf", ("Yamaha", "MT 07", 2019)),
        ("/Shop/2024 KTM 390 Duke workshop.pdf", ("KTM", "390 Duke", 2024)),
        ("/Manuals/BMW R 12 G_S 2025 rider handbook.pdf", ("BMW", "R 12 G S", 2025)),
        ("/Manuals/harley street glide 2018 scan.pdf", ("Harley-Davidson", "street glide", 2018)),
    ],
)
def test_parse_meta_reads_the_shop_s_filing(path, expect):
    assert dbx.parse_meta(path) == expect


@pytest.mark.parametrize(
    "path",
    [
        "/Manuals/invoice 2019.pdf",  # a year but no make
        "/Manuals/Yamaha MT-07 service manual.pdf",  # a make but no year
        "/Manuals/scan0001.pdf",
    ],
)
def test_parse_meta_refuses_to_guess(path):
    """A manual filed under the wrong bike is the one failure this product exists to prevent."""
    assert dbx.parse_meta(path) is None


# ---------------------------------------------------------------- the sync pass


def test_first_pass_lists_downloads_and_ingests(dropbox, ingested):
    fake = dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    result = dbx.sync_once()

    assert result["enabled"] and result["seen"] == 1 and result["queued"] == 1 and result["done"] == 1
    record = result["files"][0]
    assert (record["make"], record["model"], record["year"]) == ("Yamaha", "MT 07", 2019)
    assert record["manualId"] == "yamaha-mt-07-2019-shop"
    assert record["state"] == "done"
    assert record["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert Path(record["file"]).read_bytes() == PDF

    routes = [r for r, _ in fake.calls]
    assert routes[0] == "files/list_folder"
    assert fake.calls[0][1] == {"path": "/Manuals", "recursive": True, "include_deleted": False, "limit": 2000}
    assert ("files/download", {"path": "id:/Manuals/Yamaha MT-07 2019 service manual.pdf"}) in fake.calls
    assert fake.auth["files/download"] == "Bearer token-123"
    assert ingested and ingested[0][1] == "yamaha-mt-07-2019-shop"


def test_shop_copy_never_overwrites_the_free_owner_s_manual(dropbox, ingested):
    """`-shop`, not `-om`: the OEM handbook another vehicle points at must survive."""
    dropbox([[entry("/Manuals/KTM 390 Duke 2024 workshop.pdf")]])
    result = dbx.sync_once()
    record = result["files"][0]
    assert record["manualId"].endswith("-shop")
    assert record["bikeId"] == "ktm-390-duke-2024"

    from app.store import get_store

    bike = get_store().bike("ktm-390-duke-2024")
    assert bike is not None and bike.manualId == "ktm-390-duke-2024-shop"
    assert record["replaced"] == "ktm-390-duke-2024-om-en"  # recorded, so the swap is visible and reversible


def test_pagination_follows_has_more(dropbox, ingested):
    fake = dropbox(
        [
            [entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")],
            [entry("/Manuals/KTM 390 Duke 2024 workshop.pdf", rev="b2")],
        ],
        bodies={"id:/Manuals/KTM 390 Duke 2024 workshop.pdf": PDF + b"ktm\n"},
    )
    result = dbx.sync_once()
    assert result["seen"] == 2 and result["done"] == 2
    assert [r for r, _ in fake.calls].count("files/list_folder/continue") == 1
    assert dbx.state()["cursor"] == "cur-2"


def test_second_pass_uses_the_cursor_and_skips_settled_files(dropbox, ingested):
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    dbx.sync_once()
    fake = dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    result = dbx.sync_once()
    assert [r for r, _ in fake.calls] == ["files/list_folder/continue"]
    assert result["queued"] == 0
    assert len(ingested) == 1  # ingested once, not twice


def test_a_changed_revision_is_ingested_again(dropbox, ingested):
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    dbx.sync_once()
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf", rev="b2")]], body=PDF + b"v2\n")
    result = dbx.sync_once()
    assert result["queued"] == 1 and len(ingested) == 2


def test_identical_bytes_under_a_second_name_are_a_duplicate(dropbox, ingested):
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    dbx.sync_once()
    dropbox([[entry("/Manuals/copy of Yamaha MT-07 2019 manual.pdf", file_id="id:copy")]])
    result = dbx.sync_once()
    assert result["files"][0]["state"] == "duplicate"
    assert result["files"][0]["of"] == "yamaha-mt-07-2019-shop"
    assert len(ingested) == 1


def test_a_file_we_cannot_place_is_reported_not_guessed(dropbox, ingested):
    dropbox([[entry("/Manuals/scan0001.pdf")]])
    result = dbx.sync_once()
    assert result["unmatched"] == 1
    assert result["files"][0]["state"] == "unmatched"
    assert not ingested


def test_a_file_that_is_not_a_pdf_is_skipped(dropbox, ingested):
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]], body=b"<html>login</html>")
    result = dbx.sync_once()
    assert result["files"][0]["state"] == "skipped"
    assert not ingested


def test_non_pdf_entries_and_folders_are_ignored(dropbox, ingested):
    dropbox(
        [
            [
                {".tag": "folder", "name": "Yamaha", "id": "id:f", "path_display": "/Manuals/Yamaha"},
                entry("/Manuals/KTM 390 Duke 2024 invoice.xlsx", file_id="id:x"),
            ]
        ]
    )
    result = dbx.sync_once()
    assert result["seen"] == 2 and result["queued"] == 0


def test_an_ingest_that_explodes_does_not_stop_the_folder(dropbox, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("pymupdf said no")

    monkeypatch.setattr(dbx.ingest_mod, "run", boom)
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    result = dbx.sync_once()
    assert result["files"][0]["state"] == "error"
    assert "pymupdf said no" in result["files"][0]["reason"]


def test_an_invalidated_cursor_is_thrown_away_and_the_folder_relisted(dropbox, ingested):
    fake = dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    data = dbx.state()
    data["cursor"] = "stale"
    dbx._save(data)
    result = dbx.sync_once()
    assert [r for r, _ in fake.calls][:2] == ["files/list_folder/continue", "files/list_folder"]
    assert result["done"] == 1


def test_a_429_is_reported_with_its_retry_after_and_nothing_is_lost(dropbox, monkeypatch, ingested):
    dropbox([[]])

    def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"retry_after": 7}}, text='{"error": {"retry_after": 7}}')

    monkeypatch.setattr(dbx, "_client", lambda longpoll=False: httpx.Client(transport=httpx.MockTransport(limited)))
    result = dbx.sync_once()
    assert result["retryAfter"] == 7 and result["queued"] == 0
    assert dbx.state()["lastError"].startswith("dropbox 429")


def test_longpoll_is_unauthenticated_by_design(dropbox):
    """files.stone: `auth = "noauth"` - the cursor is the credential, so the token never rides a
    480-second socket."""
    fake = dropbox([[]])
    assert dbx.longpoll("cur-1") is False
    assert fake.auth["files/list_folder/longpoll"] is None
    assert fake.calls[-1][1] == {"cursor": "cur-1", "timeout": 480}


# ---------------------------------------------------------------- routes, with a token


def test_status_route_reports_every_file_and_its_state(dropbox, ingested, client):
    dropbox(
        [
            [
                entry("/Manuals/Yamaha MT-07 2019 service manual.pdf"),
                entry("/Manuals/scan0001.pdf", file_id="id:scan"),
            ]
        ]
    )
    dbx.sync_once()
    body = client.get("/dropbox/status").json()
    assert body["enabled"] and body["folder"] == "/Manuals" and body["cursor"] is True
    assert body["counts"] == {"done": 1, "unmatched": 1}
    assert {f["state"] for f in body["files"]} == {"done", "unmatched"}


def test_sync_route_runs_a_pass_when_asked_to_wait(dropbox, ingested, client):
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    body = client.post("/dropbox/sync?wait=true").json()
    assert body["done"] == 1
    assert client.get("/dropbox/config").json() == {
        "enabled": True,
        "folder": "/Manuals",
        "webhook": True,
        "watching": False,
    }


def test_webhook_verification_echoes_the_challenge_with_nosniff(client):
    r = client.get("/dropbox/webhook?challenge=abc123")
    assert r.status_code == 200
    assert r.text == "abc123"
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_webhook_rejects_a_body_that_is_not_signed(dropbox, client):
    dropbox([[]])
    body = json.dumps({"list_folder": {"accounts": ["dbid:AAH"]}}).encode()
    assert client.post("/dropbox/webhook", content=body).status_code == 403
    assert client.post("/dropbox/webhook", content=body, headers={"X-Dropbox-Signature": "00"}).status_code == 403


def test_webhook_accepts_a_correct_hmac_sha256_of_the_raw_body(dropbox, ingested, client):
    dropbox([[entry("/Manuals/Yamaha MT-07 2019 service manual.pdf")]])
    body = json.dumps({"list_folder": {"accounts": ["dbid:AAH"]}}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = client.post("/dropbox/webhook", content=body, headers={"X-Dropbox-Signature": sig})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(ingested) == 1  # the notification names an account, so the pass is what finds the file


def test_webhook_503s_without_an_app_secret(monkeypatch, client):
    monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)
    monkeypatch.setattr(dbx.settings, "dropbox_token", "token-only")
    assert client.post("/dropbox/webhook", content=b"{}").status_code == 503

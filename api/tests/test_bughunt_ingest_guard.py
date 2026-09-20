"""BUG-09: POST /ingest is admin-only, registry-hosts-only, and the fetcher refuses private targets.

The product path is untouched and is asserted here too: /manuals/ensure resolves the PDF server-side
and /ingest/upload takes a file, so neither carries an operator-supplied URL.
"""

from importlib import import_module

import httpx
import pytest

from app import ingest as ingest_mod
from app.config import settings
from app.ingest.fetch import BlockedTarget, _guard, _public, fetch

# app.ingest re-exports the fetch *function*, so the module has to be reached by name.
fetch_mod = import_module("app.ingest.fetch")

TOKEN = "test-admin-token"
GOOD = "https://www.ktm.com/content/dam/owners-manual/390-duke-2024.pdf"
BODY = {"url": GOOD, "make": "KTM", "model": "390 Duke", "year": 2024}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    yield {"X-Admin-Token": TOKEN}


@pytest.fixture
def hosts(monkeypatch):
    """A fixed allowlist, so the test does not depend on what the seeded registry happens to hold."""
    monkeypatch.setattr(ingest_mod, "known_pdf_hosts", lambda: frozenset({"www.ktm.com", "ktm.com"}))
    yield


@pytest.fixture
def never_starts(monkeypatch):
    started: list[tuple] = []
    monkeypatch.setattr(
        "app.main._start_job",
        lambda tasks, source, make, model, year, market: started.append((source, make, model, year))
        or ingest_mod.IngestJob(id="fake", manualId="fake-om", status="queued"),
    )
    return started


# ------------------------------------------------------------------------- the token


def test_no_token_is_401(client, admin, hosts, never_starts):
    assert client.post("/ingest", json=BODY).status_code == 401
    assert not never_starts


def test_a_wrong_token_is_401(client, admin, hosts, never_starts):
    assert client.post("/ingest", json=BODY, headers={"X-Admin-Token": "nope"}).status_code == 401
    assert not never_starts


def test_a_prefix_of_the_token_is_401(client, admin, hosts, never_starts):
    assert client.post("/ingest", json=BODY, headers={"X-Admin-Token": TOKEN[:-1]}).status_code == 401


def test_an_unconfigured_deployment_refuses_everyone(client, hosts, never_starts, monkeypatch):
    """No secret file and no env var -> the route is closed, not open."""
    monkeypatch.setattr(settings, "admin_token", None)
    assert client.post("/ingest", json=BODY, headers={"X-Admin-Token": ""}).status_code == 401
    assert client.post("/ingest", json=BODY, headers={"X-Admin-Token": "anything"}).status_code == 401
    assert not never_starts


# -------------------------------------------------------------------------- the host


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/manual.pdf",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8080/x.pdf",
        "file:///c:/Users/me/agent-secrets/openai.txt",
        "ftp://www.ktm.com/x.pdf",
        "https://www.ktm.com.evil.example/x.pdf",
        "not a url at all",
        "",
    ],
)
def test_a_host_the_registry_does_not_publish_is_403(client, admin, hosts, never_starts, url):
    got = client.post("/ingest", json={**BODY, "url": url}, headers=admin)
    assert got.status_code == 403, got.text
    assert not never_starts


def test_a_registry_host_passes_the_gate(client, admin, hosts, never_starts):
    assert client.post("/ingest", json=BODY, headers=admin).status_code == 200
    assert never_starts and never_starts[0][0] == GOOD


def test_a_subdomain_of_a_registry_host_passes(client, admin, hosts, never_starts):
    url = "https://cdn.www.ktm.com/x.pdf"
    assert client.post("/ingest", json={**BODY, "url": url}, headers=admin).status_code == 200


def test_known_pdf_hosts_reads_the_registry_and_the_verified_list(store):
    found = ingest_mod.known_pdf_hosts()
    assert found, "the seeded registry must yield at least one host"
    assert all(h == h.lower() and "/" not in h for h in found)
    assert any(ingest_mod.known_pdf_host(e.url) for e in store.registry()[:50])


# ------------------------------------------------------------------ the fetcher's own guard


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1"],
)
def test_private_and_loopback_targets_are_refused(host):
    assert _public(host) is False
    bare = f"[{host}]" if ":" in host else host
    with pytest.raises(BlockedTarget):
        _guard(httpx.Request("GET", f"http://{bare}/manual.pdf"))


def test_a_name_that_does_not_resolve_is_refused():
    assert _public("no-such-host.invalid") is False


def test_the_guard_runs_on_every_redirect_hop(monkeypatch, tmp_path):
    """The interesting SSRF is not the first URL, it is the 302 that follows it."""
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:9/secret.pdf"})
        return httpx.Response(200, content=b"%PDF-1.7 leaked")

    real_client = httpx.Client

    def client_with_mock(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(fetch_mod.httpx, "Client", client_with_mock)
    monkeypatch.setattr(fetch_mod, "_public", lambda host: host == "public.example")

    with pytest.raises(BlockedTarget):
        fetch("http://public.example/manual.pdf", tmp_path / "out.pdf")
    assert hops == ["http://public.example/manual.pdf"], "the redirect must never have been sent"
    assert not (tmp_path / "out.pdf").exists()


def test_the_escape_hatch_is_opt_in(monkeypatch):
    with pytest.raises(BlockedTarget):
        _guard(httpx.Request("GET", "http://127.0.0.1/x.pdf"))
    monkeypatch.setenv("TTM_ALLOW_PRIVATE_FETCH", "1")
    _guard(httpx.Request("GET", "http://127.0.0.1/x.pdf"))  # no raise


# ----------------------------------------------------------------- the product path is untouched


def test_manuals_ensure_takes_no_url_and_needs_no_token(client):
    assert client.post("/manuals/ensure", json={"bikeId": "no-such-bike"}).status_code == 404
    assert client.post("/manuals/ensure", json={"url": "https://evil.example/x.pdf"}).status_code == 422


def test_ingest_upload_needs_no_token_and_still_validates(client):
    got = client.post(
        "/ingest/upload",
        files={"file": ("x.pdf", b"not a pdf", "application/pdf")},
        params={"make": "KTM", "model": "390 Duke", "year": 2024},
    )
    assert got.status_code == 415


# -------------------------------------------------------------------- the concurrency cap


def test_concurrent_ingests_are_capped():
    assert 1 <= ingest_mod.MAX_CONCURRENT <= 8
    held = [ingest_mod._slots.acquire(timeout=0.1) for _ in range(ingest_mod.MAX_CONCURRENT)]
    try:
        assert all(held)
        assert ingest_mod._slots.acquire(timeout=0.05) is False
    finally:
        for got in held:
            if got:
                ingest_mod._slots.release()

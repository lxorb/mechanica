"""Regressions for the second bug-hunt pass, 2026-09-20: the on-demand job lifecycle.

BUG-13  a dead ingest job is reported as dead, and two replicas never ingest the same manual
BUG-14  climate's manual_ids() never downloads a Manual
BUG-15  the early, section-less manual is never cached
BUG-16  ingest-failure markers are shared, not per-replica
BUG-18  HEAD answers wherever GET answers
BUG-19  `vin` has a length cap
BUG-20  main._pushed is bounded and claimed atomically

See docs/qa/BUGS.md for the repro of each one.
"""

import json
import threading
import time

import pytest

from app import main as main_mod
from app import ondemand
from app.models import Bike, IngestJob, Manual
from app.store import FileStore


# ---------------------------------------------------------------- a store that can compare-and-set


class FakeBlobStore(FileStore):
    """A FileStore that also speaks the three shared-document methods BlobStore has, with real
    ETag semantics: read a version, merge, write only if nothing moved. That compare-and-set is
    the one cross-replica primitive the deployed store offers, and the ingest lease is built on it.
    """

    def __init__(self, root):
        super().__init__(root)
        self.docs: dict[str, tuple[int, object]] = {}
        self.cas_calls = 0
        self.gate = None  # run between a _cas read and its write, to interleave two callers
        self._docs_lock = threading.Lock()

    @staticmethod
    def _copy(value):
        return json.loads(json.dumps(value)) if value is not None else None

    def _read_json(self, name, default=None):
        with self._docs_lock:
            hit = self.docs.get(name)
        return self._copy(hit[1]) if hit else default

    def _write_json(self, name, data, metadata=None) -> None:
        with self._docs_lock:
            version = self.docs.get(name, (0, None))[0]
            self.docs[name] = (version + 1, self._copy(data))

    def _cas(self, name, merge, retries: int = 10) -> None:
        self.cas_calls += 1
        for _ in range(retries):
            with self._docs_lock:
                version, current = self.docs.get(name, (0, None))
            new = merge(self._copy(current))
            if self.gate:
                self.gate(name)
            with self._docs_lock:
                if self.docs.get(name, (0, None))[0] != version:
                    continue  # somebody wrote while we were deciding: re-read and merge again
                self.docs[name] = (version + 1, self._copy(new))
                return
        raise RuntimeError(f"{name}: lost {retries} ETag races")


def _manual(manual_id: str, sections=None) -> Manual:
    return Manual(
        id=manual_id,
        bikeIds=[],
        file=f"/manuals/{manual_id}.pdf",
        pages=100,
        title="Provisional",
        source="https://example.invalid/x.pdf",
        outline=[],
        sections=sections or [],
        parts=[],
    )


BIKE = Bike(id="fake-bike-2026", make="Fake", model="One", year=2026, market="EU")
SOURCE = ondemand.Source(url="https://example.invalid/one.pdf", manualId="fake-one-2026-om", needsUa=None)


@pytest.fixture
def blobbish(tmp_path, monkeypatch):
    """A store two "replicas" share, wired into ondemand, with the module globals reset."""
    store = FakeBlobStore(tmp_path)
    store.put_bikes([BIKE])
    monkeypatch.setattr(ondemand, "get_store", lambda: store)
    monkeypatch.setattr(ondemand, "source_for", lambda bike, vin=None: SOURCE)
    ondemand._jobs.clear()
    ondemand._fails.clear()
    yield store
    # no worker thread may outlive the monkeypatched store and write into the seeded one
    for thread in threading.enumerate():
        if thread.name.startswith(("ondemand-", "beat-")):
            thread.join(10)
    ondemand._jobs.clear()
    ondemand._fails.clear()


@pytest.fixture
def local_jobs():
    """ondemand's process-local dicts, empty before and after."""
    ondemand._jobs.clear()
    ondemand._fails.clear()
    yield ondemand._jobs
    ondemand._jobs.clear()
    ondemand._fails.clear()


# ---------------------------------------------------------------- BUG-13  the lease


def test_the_second_replica_is_handed_the_first_ones_job(blobbish):
    """_jobs is process-local, so with two replicas both used to start - and pay for - the same
    ingest. The lease is the only thing that can stop that."""
    assert ondemand.take_lease("fake-one-2026-om", "job-a") == "job-a"
    assert ondemand.take_lease("fake-one-2026-om", "job-b") == "job-a"
    assert ondemand.lease_holder("fake-one-2026-om") == "job-a"


def test_a_lapsed_lease_is_taken_over(blobbish):
    ondemand.take_lease("fake-one-2026-om", "job-a")
    blobbish._write_json(
        ondemand._lease_name("fake-one-2026-om"),
        {"jobId": "job-a", "at": time.time() - ondemand.STALE_AFTER - 1},
    )
    assert ondemand.lease_holder("fake-one-2026-om") is None
    assert ondemand.take_lease("fake-one-2026-om", "job-b") == "job-b"


def test_a_late_renewal_never_steals_the_manual_back(blobbish):
    """A beat that was starved past the TTL must not reclaim a manual somebody else has started."""
    ondemand.take_lease("fake-one-2026-om", "job-a")
    blobbish._write_json(
        ondemand._lease_name("fake-one-2026-om"),
        {"jobId": "job-a", "at": time.time() - ondemand.STALE_AFTER - 1},
    )
    assert ondemand.take_lease("fake-one-2026-om", "job-b") == "job-b"
    assert ondemand.renew_lease("fake-one-2026-om", "job-a") is False
    assert ondemand.lease_holder("fake-one-2026-om") == "job-b"


def test_the_owner_releases_the_manual_when_it_is_done(blobbish):
    ondemand.take_lease("fake-one-2026-om", "job-a")
    ondemand.release_lease("fake-one-2026-om", "job-a")
    assert ondemand.lease_holder("fake-one-2026-om") is None
    assert ondemand.take_lease("fake-one-2026-om", "job-b") == "job-b"


def test_only_one_of_two_replicas_wins_the_lease_race(blobbish):
    """Both replicas read the same free lease before either writes - the interleaving that makes a
    read-then-write lock useless. The compare-and-set turns it into one winner and one joiner."""
    reading = threading.Event()
    written = threading.Event()

    def gate(name):
        if not reading.is_set():
            reading.set()
            written.wait(5)  # hold the first writer between its read and its write

    blobbish.gate = gate
    winners: dict[str, str] = {}

    first = threading.Thread(target=lambda: winners.update(a=ondemand.take_lease("fake-one-2026-om", "job-a")))
    first.start()
    assert reading.wait(5), "the first replica never reached the lease"
    winners["b"] = ondemand.take_lease("fake-one-2026-om", "job-b")  # lands while the first is held
    written.set()
    first.join(10)
    blobbish.gate = None

    assert winners["a"] == winners["b"], winners
    assert ondemand.lease_holder("fake-one-2026-om") == winners["a"]


def test_a_second_replica_joins_the_running_job_instead_of_starting_one(blobbish, monkeypatch):
    """End to end: ensure() twice with the process-local dict wiped in between, which is exactly
    what a second replica looks like. One ingest, one job id, one bill."""
    runs: list[str] = []
    release = threading.Event()

    def slow_run(job_id, url, manual_id, *args, **kwargs):
        runs.append(job_id)
        blobbish.put_job(IngestJob(id=job_id, manualId=manual_id, status="running", updatedAt=time.time()))
        release.wait(10)
        raise RuntimeError("stopped by the test")

    monkeypatch.setattr(ondemand.ingest, "run", slow_run)

    first = ondemand.ensure(BIKE.id)
    assert first["status"] == "running" and first["jobId"]
    for _ in range(200):  # the worker thread has to reach slow_run before the second replica asks
        if runs:
            break
        time.sleep(0.01)

    ondemand._jobs.clear()  # replica B: same blob, its own empty dict
    second = ondemand.ensure(BIKE.id)
    release.set()

    assert second["status"] == "running"
    assert second["jobId"] == first["jobId"]
    assert len(runs) == 1, runs


def test_a_replica_that_died_does_not_hold_the_manual(blobbish, monkeypatch):
    """The other half: a lease whose owner stopped beating must not block the manual for ever."""
    runs: list[str] = []

    def quick_run(job_id, url, manual_id, *args, **kwargs):
        runs.append(job_id)
        blobbish.put_job(IngestJob(id=job_id, manualId=manual_id, status="running", updatedAt=time.time()))
        raise RuntimeError("stopped by the test")

    monkeypatch.setattr(ondemand.ingest, "run", quick_run)
    blobbish._write_json(
        ondemand._lease_name(SOURCE.manualId),
        {"jobId": "ghost", "at": time.time() - ondemand.STALE_AFTER - 1},
    )
    blobbish.put_job(
        IngestJob(id="ghost", manualId=SOURCE.manualId, status="running", updatedAt=time.time() - 600)
    )

    answer = ondemand.ensure(BIKE.id)
    assert answer["status"] == "running"
    assert answer["jobId"] != "ghost"
    assert len(runs) == 1


# ---------------------------------------------------------------- BUG-13  the staleness rule


def _job(**kw) -> IngestJob:
    base = {"id": "j1", "manualId": "fake-one-2026-om", "status": "running", "updatedAt": time.time()}
    return IngestJob(**{**base, **kw})


def test_a_fresh_heartbeat_is_alive(blobbish):
    assert ondemand.alive(_job()) is True
    assert ondemand.stalled(_job()) is False


def test_a_job_nobody_has_written_for_a_minute_is_stalled(blobbish):
    old = _job(updatedAt=time.time() - ondemand.STALE_AFTER - 1)
    assert ondemand.alive(old) is False
    assert ondemand.stalled(old) is True


def test_a_silent_job_whose_lease_is_live_is_not_stalled(blobbish):
    """Waiting for one of the three ingest slots, and one slow LLM batch, are both legitimately
    silent for minutes. The lease is what tells them apart from a dead replica."""
    old = _job(status="queued", updatedAt=time.time() - ondemand.STALE_AFTER - 1)
    ondemand.take_lease(old.manualId, old.id)
    assert ondemand.alive(old) is True
    assert ondemand.stalled(old) is False


def test_a_lease_held_by_another_job_does_not_keep_this_one_alive(blobbish):
    old = _job(updatedAt=time.time() - ondemand.STALE_AFTER - 1)
    ondemand.take_lease(old.manualId, "somebody-else")
    assert ondemand.stalled(old) is True


def test_a_finished_job_is_never_stalled(blobbish):
    assert ondemand.stalled(_job(status="done", updatedAt=0.0)) is False
    assert ondemand.stalled(_job(status="error", error="no text layer", updatedAt=0.0)) is False
    assert ondemand.stalled(None) is False


def test_a_job_from_before_the_field_existed_falls_back_to_the_lease(blobbish):
    """updatedAt is None on a job written by the old build: no heartbeat, so the lease decides."""
    assert ondemand.stalled(_job(updatedAt=None)) is True
    ondemand.take_lease("fake-one-2026-om", "j1")
    assert ondemand.stalled(_job(updatedAt=None)) is False


def test_ensure_starts_a_fresh_job_once_the_old_one_is_stalled(blobbish, monkeypatch):
    """The dict still names the dead job; ensure() must not hand it out again."""
    started: list[str] = []

    def run(job_id, url, manual_id, *args, **kwargs):
        started.append(job_id)
        blobbish.put_job(IngestJob(id=job_id, manualId=manual_id, status="running", updatedAt=time.time()))
        raise RuntimeError("stopped by the test")

    monkeypatch.setattr(ondemand.ingest, "run", run)
    blobbish.put_job(
        IngestJob(id="dead", manualId=SOURCE.manualId, status="running", updatedAt=time.time() - 600)
    )
    ondemand._jobs[SOURCE.manualId] = "dead"

    answer = ondemand.ensure(BIKE.id)
    assert answer["jobId"] not in ("dead", None)
    assert started and started[0] == answer["jobId"]


# ---------------------------------------------------------------- BUG-13  the beat


def test_the_beat_keeps_a_silent_job_alive(blobbish, monkeypatch):
    monkeypatch.setattr(ondemand, "HEARTBEAT", 0.02)
    blobbish.put_job(
        IngestJob(id="beating", manualId=SOURCE.manualId, status="queued", updatedAt=time.time() - 600)
    )
    beat = ondemand.Beat("beating", SOURCE.manualId).start()
    try:
        for _ in range(200):
            if beat.beats:
                break
            time.sleep(0.01)
        assert beat.beats, "the beat never ran"
        assert ondemand.lease_holder(SOURCE.manualId) == "beating"
        assert ondemand.stalled(blobbish.job("beating")) is False
    finally:
        beat.stop()
    seen = beat.beats
    time.sleep(0.1)
    assert beat.beats == seen, "stop() must end the beat"


def test_the_beat_stops_itself_once_the_job_is_done(blobbish, monkeypatch):
    monkeypatch.setattr(ondemand, "HEARTBEAT", 0.02)
    blobbish.put_job(IngestJob(id="finished", manualId=SOURCE.manualId, status="done", updatedAt=0.0))
    beat = ondemand.Beat("finished", SOURCE.manualId).start()
    try:
        time.sleep(0.15)
        assert beat.beats == 0
        assert blobbish.job("finished").status == "done"
    finally:
        beat.stop()


def test_settle_repairs_a_job_a_late_beat_put_back_to_running(blobbish):
    """The one interleaving left: the beat writes back the document it read a moment before the
    worker's own "done" landed. settle() runs after the beat is joined, so done is the last word."""
    blobbish.put_job(
        IngestJob(id="late", manualId=SOURCE.manualId, status="running", pages=12, done=12, updatedAt=time.time())
    )
    ondemand.settle("late")
    job = blobbish.job("late")
    assert job.status == "done" and job.done == 12 and job.stage == "done"


def test_settle_leaves_a_terminal_job_alone(blobbish):
    blobbish.put_job(IngestJob(id="bad", manualId=SOURCE.manualId, status="error", error="no text layer"))
    ondemand.settle("bad")
    assert blobbish.job("bad").status == "error"


def test_touch_moves_the_heartbeat_and_nothing_else(blobbish):
    blobbish.put_job(
        IngestJob(id="t1", manualId=SOURCE.manualId, status="running", pages=9, done=4, stage="pages", updatedAt=1.0)
    )
    assert ondemand.touch("t1") is True
    job = blobbish.job("t1")
    assert job.updatedAt > 1.0
    assert (job.status, job.pages, job.done, job.stage) == ("running", 9, 4, "pages")
    assert ondemand.touch("missing") is False


def test_the_job_route_reports_a_stalled_job_as_an_error(client, store, local_jobs):
    """What the Confirm screen polls. Reported as running, it polls a dead id for fifteen minutes."""
    store.put_job(
        IngestJob(id="stale-job", manualId="nobody-om", status="running", pages=100, done=40,
                  updatedAt=time.time() - ondemand.STALE_AFTER - 1)
    )
    body = client.get("/ingest/stale-job").json()
    assert body["status"] == "error"
    assert body["error"] == "stalled"
    assert body["done"] == 40, "the progress it reached is still reported"
    assert store.job("stale-job").status == "running", "the stored job is not rewritten by a GET"


def test_the_job_route_leaves_a_beating_job_alone(client, store, local_jobs):
    store.put_job(
        IngestJob(id="live-job", manualId="nobody-om", status="running", updatedAt=time.time())
    )
    body = client.get("/ingest/live-job").json()
    assert body["status"] == "running" and body["error"] is None
    assert client.get("/ingest/live-job").headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- BUG-16  shared failure markers


def test_a_failure_marker_is_shared_by_every_replica(blobbish):
    """DATA_DIR is the container's own ephemeral disk: replica A refused a broken manual for six
    hours while replica B retried it on every poll."""
    ondemand.remember_failure("fake-one-2026-om", SOURCE.url, "ValueError: no text layer")
    assert blobbish._read_json("failed/fake-one-2026-om.json", None), "the marker is in the store"

    ondemand._fails.clear()  # another replica: same store, its own memory
    record = ondemand.recent_failure("fake-one-2026-om")
    assert record and "no text layer" in record["error"]

    ondemand.forget_failure("fake-one-2026-om")
    ondemand._fails.clear()
    assert ondemand.recent_failure("fake-one-2026-om") is None


def test_a_stale_failure_marker_expires(blobbish):
    ondemand.remember_failure("fake-one-2026-om", SOURCE.url, "boom")
    blobbish._write_json(
        "failed/fake-one-2026-om.json",
        {"manualId": "fake-one-2026-om", "url": SOURCE.url, "error": "boom",
         "at": time.time() - ondemand.FAIL_COOLDOWN - 1},
    )
    ondemand._fails.clear()
    assert ondemand.recent_failure("fake-one-2026-om") is None


def test_a_filestore_still_keeps_its_markers_on_disk(tmp_path, monkeypatch, local_jobs):
    """No compare-and-set on this store, so the record falls back to DATA_DIR - where a
    single-process deployment is the only reader anyway."""
    monkeypatch.setattr(ondemand, "get_store", lambda: FileStore(tmp_path))
    monkeypatch.setattr(ondemand.settings, "data_dir", tmp_path)
    ondemand.remember_failure("disk-om", "https://example.invalid/x.pdf", "boom")
    assert (tmp_path / "failed" / "disk-om.json").exists()
    ondemand._fails.clear()
    assert ondemand.recent_failure("disk-om")
    ondemand.forget_failure("disk-om")
    assert not (tmp_path / "failed" / "disk-om.json").exists()


def test_the_lease_falls_back_to_a_file_without_a_compare_and_set(tmp_path, monkeypatch, local_jobs):
    monkeypatch.setattr(ondemand, "get_store", lambda: FileStore(tmp_path))
    monkeypatch.setattr(ondemand.settings, "data_dir", tmp_path)
    assert ondemand.take_lease("disk-om", "job-a") == "job-a"
    assert ondemand.take_lease("disk-om", "job-b") == "job-a"
    assert (tmp_path / "leases" / "disk-om.json").exists()
    ondemand.release_lease("disk-om", "job-a")
    assert ondemand.take_lease("disk-om", "job-b") == "job-b"


# ---------------------------------------------------------------- BUG-14  climate wants ids only


class _NoDownloads:
    root = None

    def __init__(self):
        self.summaries = 0

    def manual_summaries(self):
        self.summaries += 1
        return [{"id": "b-om", "pages": 10}, {"id": "a-om", "pages": 20}]

    def manuals(self):
        raise AssertionError("climate must never download every Manual to read its id")


def test_climate_reads_manual_ids_from_the_listing():
    from app.climate import rules

    store = _NoDownloads()
    assert rules.manual_ids(store) == ["a-om", "b-om"]
    assert store.summaries == 1


def test_climate_falls_back_when_the_listing_breaks():
    from app.climate import rules

    class _Broken(_NoDownloads):
        def manual_summaries(self):
            raise RuntimeError("blob unreachable")

        def manuals(self):
            return [_manual("only-om")]

    assert rules.manual_ids(_Broken()) == ["only-om"]


# ---------------------------------------------------------------- BUG-15  the early manual


@pytest.fixture
def provisional(store, data_dir):
    """The section-less document an ingest publishes so the PDF is readable at once."""
    manual = _manual("zz-provisional-om")
    store.put_manual(manual)
    yield manual
    (data_dir / "manuals" / f"{manual.id}.json").unlink(missing_ok=True)


def test_a_section_less_manual_is_never_cached(client, provisional):
    res = client.get(f"/manuals/{provisional.id}")
    assert res.status_code == 200
    assert res.json()["sections"] == []
    assert res.headers["cache-control"] == "no-store"


def test_a_real_manual_still_carries_the_minute(client):
    res = client.get("/manuals/ktm-390-duke-2024-om-en")
    assert res.status_code == 200 and res.json()["sections"]
    assert res.headers["cache-control"] == "public, max-age=60"


# ---------------------------------------------------------------- BUG-18  HEAD


@pytest.mark.parametrize("path", ["/health", "/manuals", "/manuals/ktm-390-duke-2024-om-en", "/cost"])
def test_head_answers_wherever_get_does(client, path):
    head = client.head(path)
    get = client.get(path)
    assert head.status_code == get.status_code == 200
    assert head.content == b""
    assert head.headers.get("content-type") == get.headers.get("content-type")


def test_head_on_an_unknown_id_is_still_a_404(client):
    assert client.head("/manuals/not-a-manual").status_code == 404


def test_head_does_not_reach_a_post_route(client):
    """Only GET routes grew a HEAD; a POST-only path still says so."""
    assert client.head("/ask").status_code == 405
    assert client.head("/identify/vin").status_code == 405


def test_the_openapi_schema_is_unchanged_by_head(client):
    """The fix is a layer above the router, so no route grew a second operation."""
    schema = client.get("/openapi.json").json()
    assert "head" not in schema["paths"]["/health"]
    assert set(schema["paths"]["/health"]) == {"get"}


# ---------------------------------------------------------------- BUG-19  the vin cap


def test_a_five_thousand_character_vin_is_refused(client):
    body = {"bikeId": "ktm-390-duke-2024", "vin": "a" * 5000}
    assert client.post("/manuals/ensure", json=body).status_code == 422


def test_a_real_vin_is_still_accepted(client):
    body = {"bikeId": "ktm-390-duke-2024", "vin": "VBKJSA40XR1234567"}
    assert client.post("/manuals/ensure", json=body).status_code == 200
    assert len("VBKJSA40XR1234567") <= main_mod.MAX_VIN


# ---------------------------------------------------------------- BUG-20  the push marker


def test_only_one_thread_claims_a_push():
    main_mod._pushed.clear()
    claims = []
    start = threading.Barrier(8, timeout=5)

    def claim():
        start.wait()
        claims.append(main_mod._claim_push("one-om"))

    threads = [threading.Thread(target=claim) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert claims.count(True) == 1, claims
    main_mod._pushed.clear()


def test_a_failed_push_can_be_retried(tmp_path, monkeypatch):
    main_mod._pushed.clear()
    calls: list[str] = []

    class _Store:
        def put_pdf(self, manual_id, path):
            calls.append(manual_id)
            if len(calls) == 1:
                raise RuntimeError("blob down")

    monkeypatch.setattr(main_mod, "get_store", lambda: _Store())
    main_mod._push_pdf("one-om", tmp_path / "x.pdf")
    assert main_mod._pushed == set(), "a failed upload must not be remembered as done"
    main_mod._push_pdf("one-om", tmp_path / "x.pdf")
    main_mod._push_pdf("one-om", tmp_path / "x.pdf")
    assert calls == ["one-om", "one-om"], "and the one that worked is never repeated"
    main_mod._pushed.clear()


def test_the_push_marker_is_bounded():
    main_mod._pushed.clear()
    for n in range(main_mod._PUSHED_MAX * 2 + 5):
        main_mod._claim_push(f"m{n}")
    assert len(main_mod._pushed) <= main_mod._PUSHED_MAX
    main_mod._pushed.clear()

import re
import secrets
import threading
import time
import uuid
from collections import defaultdict

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from . import ask as ask_mod
from . import chat as chat_mod
from .climate.routes import router as climate_router
from . import offers as offers_mod
from . import parts_catalog as parts_catalog_mod
from . import cost_ttc
from . import dropbox_sync
from . import identify as identify_mod
from . import ingest as ingest_mod
from . import ondemand
from . import voice
from . import voice_elevenlabs
from .config import settings
from .llm import naive_usd
from .models import (
    AskRequest,
    AskResponse,
    Bike,
    CostSummary,
    IdentifyResponse,
    IngestJob,
    IngestRequest,
    Manual,
    PartClass,
    RegistryEntry,
    VinRequest,
)
from .store import get_store, max_manual_pages

MAX_UPLOAD = 60 * 1024 * 1024
MAX_IMAGE = 12 * 1024 * 1024
# A VIN is 17 characters. The field is passed on to the per-make dynamic resolvers, so it is
# capped here rather than a few calls deeper (docs/qa/BUGS.md BUG-19).
MAX_VIN = 32

app = FastAPI(title="Trust the manual", version="0.1.0")


class HeadAsGet:
    """Answer HEAD wherever we answer GET.

    FastAPI's APIRoute does not add HEAD to a GET route the way Starlette's Route does, so every
    route answered 405 (docs/qa/BUGS.md BUG-18). Rewriting the method one layer above the router
    is the whole fix: the route runs exactly as it would for GET, the headers are therefore the
    ones GET would send, and the body is dropped on the way out - which is what HEAD means. Doing
    it here instead of adding HEAD to `route.methods` also keeps the OpenAPI schema (and its
    operation ids) unchanged.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "HEAD":
            return await self.app(scope, receive, send)

        async def drop_body(message):
            if message.get("type") == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, drop_body)


app.add_middleware(
    GZipMiddleware,
    minimum_size=1024,
    compresslevel=6,
    exclude_content_types=(*DEFAULT_EXCLUDED_CONTENT_TYPES, "application/pdf"),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://.*" if settings.cors_origins == ["*"] else None,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "Content-Encoding"],
)
# Added last, so it is the outermost layer: everything below it only ever sees GET.
app.add_middleware(HeadAsGet)
app.include_router(voice.router)
app.include_router(voice_elevenlabs.router)
app.include_router(cost_ttc.router)
app.include_router(dropbox_sync.router)
app.include_router(climate_router)


def slug(*parts: str | int) -> str:
    return re.sub(r"[^a-z0-9]+", "-", " ".join(str(p) for p in parts).lower()).strip("-")


def pdf_url(manual_id: str) -> str | None:
    """Public blob URL when the store has one; the browser then fetches the PDF without an API hop."""
    resolve = getattr(get_store(), "pdf_url", None)
    return resolve(manual_id) if resolve else None


def public(manual: Manual) -> Manual:
    url = pdf_url(manual.id) or f"{settings.public_base}/manuals/{manual.id}/file"
    return manual.model_copy(update={"file": url})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/catalog", response_model=list[Bike])
def catalog():
    return get_store().bikes()


@app.get("/catalog/suggest", response_model=list[Bike])
def suggest(q: str = ""):
    needle = re.sub(r"[^a-z0-9]", "", q.lower())
    if not needle:
        return []
    out = []
    for b in get_store().bikes():
        hay = re.sub(r"[^a-z0-9]", "", f"{b.make}{b.model}{b.year}".lower())
        if needle in hay:
            out.append(b)
    return out[:50]


@app.get("/manuals")
def manuals():
    store = get_store()
    # thousands of manuals: BlobStore answers this from a cached blob listing instead of
    # downloading every document. Same four fields either way.
    summaries = getattr(store, "manual_summaries", None)
    if summaries is not None:
        return summaries()
    return [
        {"id": m.id, "title": m.title, "bikeIds": m.bikeIds, "pages": m.pages, "sections": len(m.sections)}
        for m in store.manuals()
    ]


class EnsureRequest(BaseModel):
    bikeId: str
    vin: str | None = Field(default=None, max_length=MAX_VIN)


@app.post("/manuals/ensure")
def manuals_ensure(req: EnsureRequest):
    if not get_store().bike(req.bikeId):
        raise HTTPException(404)
    return ondemand.ensure(req.bikeId, req.vin)


@app.get("/manuals/{manual_id}", response_model=Manual)
def manual(manual_id: str, response: Response):
    m = get_store().manual(manual_id)
    if not m:
        raise HTTPException(404)
    # An ingest publishes the manual early - outline and PDF, no sections - so the rider can read
    # it at once, and overwrites it minutes later with the real one. Cached for the Worker's
    # minute, that provisional document outlives the real one in the browser and Pick shows no
    # sections (docs/qa/BUGS.md BUG-15), so it is the one manual shape that is never cached.
    response.headers["Cache-Control"] = "public, max-age=60" if m.sections else "no-store"
    return public(m)


# Bounded, and claimed atomically. The set grew with every manual this replica ever served, and
# `add` outside a lock let a second request return early while the first was still uploading - or
# had already failed (docs/qa/BUGS.md BUG-20). Past the ceiling the whole set is dropped: an entry
# only ever saves a repeat upload, and once the blob exists pdf_url() answers before the route
# gets here at all.
_PUSHED_MAX = 512
_pushed: set[str] = set()
_push_lock = threading.Lock()


def _claim_push(manual_id: str) -> bool:
    with _push_lock:
        if manual_id in _pushed:
            return False
        if len(_pushed) >= _PUSHED_MAX:
            _pushed.clear()
        _pushed.add(manual_id)
        return True


def _push_pdf(manual_id: str, path) -> None:
    """A PDF an on-demand ingest just wrote is local to one replica. Hand it to blob so every other
    replica - and the browser - can reach it. Once per process; a failure only means we serve it again."""
    store = get_store()
    upload = getattr(store, "put_pdf", None)
    if upload is None or not _claim_push(manual_id):
        return
    try:
        upload(manual_id, path)
    except Exception:
        with _push_lock:
            _pushed.discard(manual_id)


@app.get("/manuals/{manual_id}/file")
def manual_file(manual_id: str, tasks: BackgroundTasks):
    url = pdf_url(manual_id)
    if url:
        return RedirectResponse(url, status_code=307)
    path = ingest_mod.pdf_path(manual_id)
    if not path.exists():
        raise HTTPException(404)
    tasks.add_task(_push_pdf, manual_id, path)
    return FileResponse(path, media_type="application/pdf", filename=f"{manual_id}.pdf")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not get_store().manual(req.manualId):
        raise HTTPException(404)
    return ask_mod.answer(req.manualId, req.query)


class ChatRequest(BaseModel):
    manualId: str
    messages: list[dict]


@app.post("/chat")
def chat(req: ChatRequest):
    if not get_store().manual(req.manualId):
        raise HTTPException(404)
    return StreamingResponse(chat_mod.answer(req.manualId, req.messages), media_type="text/event-stream")


class OffersRequest(BaseModel):
    manualId: str
    partId: str
    bikeId: str | None = None


@app.post("/parts/offers")
def parts_offers(req: OffersRequest):
    store = get_store()
    if not store.manual(req.manualId):
        raise HTTPException(404)
    bike = store.bike(req.bikeId) if req.bikeId else None
    return offers_mod.offers(req.manualId, req.partId, bike)


class WarmRequest(BaseModel):
    manualId: str
    bikeId: str | None = None
    partIds: list[str] | None = None


@app.post("/parts/offers/warm")
def parts_offers_warm(req: WarmRequest):
    """Fire-and-forget prefetch for the Parts view: a cold retailer search takes longer than the
    counter waits, so the list warms the cache on open and a click lands on a finished answer."""
    store = get_store()
    if not store.manual(req.manualId):
        raise HTTPException(404)
    bike = store.bike(req.bikeId) if req.bikeId else None
    return offers_mod.warm(req.manualId, bike, req.partIds)


@app.get("/parts/catalog", response_model=parts_catalog_mod.CatalogResult)
def parts_catalog(manualId: str, bikeId: str | None = None):
    """Every part a mechanic would search for on this bike, not only the ones the manual printed."""
    store = get_store()
    if not store.manual(manualId):
        raise HTTPException(404)
    return parts_catalog_mod.catalog(manualId, store.bike(bikeId) if bikeId else None)


@app.post("/identify/photo", response_model=IdentifyResponse)
async def identify_photo(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_IMAGE:
        raise HTTPException(413)
    return identify_mod.photo(data, file.content_type or "image/jpeg")


@app.post("/identify/vin", response_model=IdentifyResponse)
def identify_vin(req: VinRequest):
    return identify_mod.vin(req.vin)


@app.post("/identify/part", response_model=list[PartClass])
async def identify_part(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_IMAGE:
        raise HTTPException(413)
    return identify_mod.part(data, file.content_type or "image/jpeg")


def _start_job(tasks: BackgroundTasks, source: str, make: str, model: str, year: int, market: str) -> IngestJob:
    store = get_store()
    bike_id = slug(make, model, year)
    manual_id = f"{bike_id}-om"
    job = IngestJob(id=uuid.uuid4().hex[:12], manualId=manual_id, status="queued", updatedAt=time.time())
    store.put_job(job)
    bike = store.bike(bike_id) or Bike(id=bike_id, make=make, model=model, year=year, market=market)
    store.put_bikes([bike])

    def run_and_link() -> None:
        # The same heartbeat an on-demand ingest gets: ingest.run() stamps the job on every write,
        # but the wait for one of the three ingest slots is silent for up to ten minutes, and a
        # client polling this job must not be told its replica died (docs/qa/BUGS.md BUG-13).
        beat = ondemand.Beat(job.id, manual_id).start()
        try:
            ingest_mod.run(job.id, source, manual_id, [bike_id], make, model, year)
            beat.stop()
            ondemand.settle(job.id)  # the beat must not be the last writer; see ondemand.settle
        finally:
            beat.stop()
            ondemand.release_lease(manual_id, job.id)
        if (done := store.job(job.id)) and done.status == "done":
            store.put_bikes([bike.model_copy(update={"manualId": manual_id})])

    tasks.add_task(run_and_link)
    return job


@app.post("/ingest", response_model=IngestJob)
def ingest_url(
    req: IngestRequest,
    tasks: BackgroundTasks,
    x_admin_token: str | None = Header(default=None),
):
    """Admin only. This is the one route that takes a URL from a human and fetches it.

    The product never comes through here: a rider gets a manual through POST /manuals/ensure, which
    resolves the PDF from the registry server-side, or by uploading a file to POST /ingest/upload.
    Left open it was a request-forgery primitive with a 180 s timeout that also wrote an
    attacker-named vehicle into the catalogue every browser downloads (docs/qa/BUGS.md BUG-09).
    """
    expected = settings.admin_token
    if not expected or not secrets.compare_digest(x_admin_token or "", expected):
        raise HTTPException(401)
    if not ingest_mod.known_pdf_host(req.url):
        raise HTTPException(403, "host is not one the registry publishes manuals from")
    return _start_job(tasks, req.url, req.make, req.model, req.year, req.market)


@app.post("/ingest/upload", response_model=IngestJob)
async def ingest_upload(
    tasks: BackgroundTasks,
    file: UploadFile = File(...),
    make: str = "",
    model: str = "",
    year: int = 0,
    market: str = "EU",
):
    if not (make and model and year):
        raise HTTPException(422)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413)
    if not data.startswith(b"%PDF"):
        raise HTTPException(415)
    path = settings.data_dir / "uploads" / f"{uuid.uuid4().hex}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _start_job(tasks, str(path), make, model, year, market)


@app.get("/ingest/{job_id}", response_model=IngestJob)
def ingest_status(job_id: str, response: Response):
    job = get_store().job(job_id)
    if not job:
        raise HTTPException(404)
    response.headers["Cache-Control"] = "no-store"
    if ondemand.stalled(job):
        # The replica that was building this manual is gone (recycled, crashed, or wedged): it has
        # not written this job for ondemand.STALE_AFTER seconds and it no longer holds the manual's
        # lease. Reported as running, the Confirm screen polls a dead id for the full fifteen
        # minutes; reported as an error, the client retries and ensure() starts a fresh job
        # (docs/qa/BUGS.md BUG-13).
        return job.model_copy(update={"status": "error", "error": "stalled"})
    return job


@app.get("/registry", response_model=list[RegistryEntry])
def registry(make: str | None = None, model: str | None = None, year: int | None = None):
    return get_store().registry(make, model, year)


@app.get("/cost", response_model=CostSummary)
def cost():
    events = get_store().costs()
    by_route: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    for e in events:
        by_route[e.route] += e.usd
        by_model[e.model] += e.usd
    return CostSummary(
        total=sum(e.usd for e in events),
        count=len(events),
        byRoute=dict(by_route),
        byModel=dict(by_model),
        naivePerAsk=naive_usd(max_manual_pages()),
        asks=sum(1 for e in events if e.route.startswith("ask")),
    )

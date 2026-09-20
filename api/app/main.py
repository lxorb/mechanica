import re
import uuid
from collections import defaultdict

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
from .store import get_store

MAX_UPLOAD = 60 * 1024 * 1024
MAX_IMAGE = 12 * 1024 * 1024

app = FastAPI(title="Trust the manual", version="0.1.0")
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
    vin: str | None = None


@app.post("/manuals/ensure")
def manuals_ensure(req: EnsureRequest):
    if not get_store().bike(req.bikeId):
        raise HTTPException(404)
    return ondemand.ensure(req.bikeId, req.vin)


@app.get("/manuals/{manual_id}", response_model=Manual)
def manual(manual_id: str):
    m = get_store().manual(manual_id)
    if not m:
        raise HTTPException(404)
    return public(m)


_pushed: set[str] = set()


def _push_pdf(manual_id: str, path) -> None:
    """A PDF an on-demand ingest just wrote is local to one replica. Hand it to blob so every other
    replica - and the browser - can reach it. Once per process; a failure only means we serve it again."""
    store = get_store()
    upload = getattr(store, "put_pdf", None)
    if upload is None or manual_id in _pushed:
        return
    _pushed.add(manual_id)
    try:
        upload(manual_id, path)
    except Exception:
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
    job = IngestJob(id=uuid.uuid4().hex[:12], manualId=manual_id, status="queued")
    store.put_job(job)
    bike = store.bike(bike_id) or Bike(id=bike_id, make=make, model=model, year=year, market=market)
    store.put_bikes([bike])

    def run_and_link() -> None:
        ingest_mod.run(job.id, source, manual_id, [bike_id], make, model, year)
        if (done := store.job(job.id)) and done.status == "done":
            store.put_bikes([bike.model_copy(update={"manualId": manual_id})])

    tasks.add_task(run_and_link)
    return job


@app.post("/ingest", response_model=IngestJob)
def ingest_url(req: IngestRequest, tasks: BackgroundTasks):
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
def ingest_status(job_id: str):
    job = get_store().job(job_id)
    if not job:
        raise HTTPException(404)
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
    pages = [m.pages for m in get_store().manuals()] or [143]
    return CostSummary(
        total=sum(e.usd for e in events),
        count=len(events),
        byRoute=dict(by_route),
        byModel=dict(by_model),
        naivePerAsk=naive_usd(max(pages)),
        asks=sum(1 for e in events if e.route.startswith("ask")),
    )

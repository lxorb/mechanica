import re
import uuid
from collections import defaultdict

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import ask as ask_mod
from . import identify as identify_mod
from . import ingest as ingest_mod
from . import voice
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

app = FastAPI(title="Trust the manual", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://.*" if settings.cors_origins == ["*"] else None,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(voice.router)


def slug(*parts: str | int) -> str:
    return re.sub(r"[^a-z0-9]+", "-", " ".join(str(p) for p in parts).lower()).strip("-")


def public(manual: Manual) -> Manual:
    return manual.model_copy(update={"file": f"{settings.public_base}/manuals/{manual.id}/file"})


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
    return [
        {"id": m.id, "title": m.title, "bikeIds": m.bikeIds, "pages": m.pages, "sections": len(m.sections)}
        for m in get_store().manuals()
    ]


@app.get("/manuals/{manual_id}", response_model=Manual)
def manual(manual_id: str):
    m = get_store().manual(manual_id)
    if not m:
        raise HTTPException(404)
    return public(m)


@app.get("/manuals/{manual_id}/file")
def manual_file(manual_id: str):
    path = ingest_mod.pdf_path(manual_id)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename=f"{manual_id}.pdf")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not get_store().manual(req.manualId):
        raise HTTPException(404)
    return ask_mod.answer(req.manualId, req.query)


@app.post("/identify/photo", response_model=IdentifyResponse)
async def identify_photo(file: UploadFile = File(...)):
    return identify_mod.photo(await file.read(), file.content_type or "image/jpeg")


@app.post("/identify/vin", response_model=IdentifyResponse)
def identify_vin(req: VinRequest):
    return identify_mod.vin(req.vin)


@app.post("/identify/part", response_model=list[PartClass])
async def identify_part(file: UploadFile = File(...)):
    return identify_mod.part(await file.read(), file.content_type or "image/jpeg")


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
    path = settings.data_dir / "uploads" / f"{uuid.uuid4().hex}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(await file.read())
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

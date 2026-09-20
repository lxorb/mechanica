"""The four Climate Fit endpoints. None of them calls a model and none of them leaves the machine."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from . import fit as compute_fit
from . import station_at, station_named
from .models import ClimateFit, ClimateRule, StationClimate
from .stations import anomalies as anomalies_table
from .stations import climatology, manuals_with_rules, rules_for

router = APIRouter(prefix="/climate", tags=["climate"])

# Repeat views of the same page are free: the worker already honours this header on /catalog.
CACHE = "public, max-age=60"
_fits: dict[tuple, ClimateFit] = {}
_FIT_CACHE = 500


class FitRequest(BaseModel):
    manualId: str
    bikeId: str | None = None
    lat: float | None = None
    lon: float | None = None
    place: str | None = None  # a typed city, resolved against stations.json - no external geocoder


@router.get("/station", response_model=StationClimate)
def station(response: Response, lat: float | None = None, lon: float | None = None, q: str | None = None):
    """Nearest reporting station, with its reduced climatology. `q` resolves a typed city name."""
    found = station_named(q) if q else (station_at(lat, lon) if lat is not None and lon is not None else None)
    if found is None:
        raise HTTPException(404, "no station")
    response.headers["Cache-Control"] = CACHE
    return found


@router.post("/fit", response_model=ClimateFit)
def climate_fit(req: FitRequest, response: Response):
    lat, lon = req.lat, req.lon
    named = None
    if req.place:
        named = station_named(req.place)
        if named is None:
            raise HTTPException(404, "no station")
        lat, lon = named.lat, named.lon
    if lat is None or lon is None:
        raise HTTPException(422, "lat/lon or place required")
    key = (req.manualId, round(lat, 2), round(lon, 2))
    hit = _fits.get(key)
    if hit is None:
        hit = compute_fit(req.manualId, lat, lon, req.bikeId)
        if hit is None:
            raise HTTPException(404, "no climatology")
        if len(_fits) > _FIT_CACHE:
            _fits.clear()
        _fits[key] = hit
    response.headers["Cache-Control"] = CACHE
    out = hit.model_copy(update={"bikeId": req.bikeId or hit.bikeId})
    if named is not None:  # typed name: the station IS the answer, so report no distance
        out = out.model_copy(update={"station": out.station.model_copy(update={"km": None})})
    return out


@router.get("/rules/{manual_id}", response_model=list[ClimateRule])
def rules(manual_id: str, response: Response):
    response.headers["Cache-Control"] = CACHE
    return rules_for(manual_id)


@router.get("/anomalies")
def anomalies(response: Response, ruleType: str | None = None, make: str | None = None):
    """The cross-OEM / model-year table: who prints what, and how little it varies."""
    rows = anomalies_table()
    if ruleType:
        rows = [r for r in rows if r.get("ruleType") == ruleType]
    if make:
        rows = [r for r in rows if make.lower() in {m.lower() for m in (r.get("makes") or {})}]
    response.headers["Cache-Control"] = CACHE
    return {"rows": rows, "manualsWithRules": len(manuals_with_rules()), "stations": len(climatology())}

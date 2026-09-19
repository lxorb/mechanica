"""Yamaha Europe: one call returns every owner's manual with its CDN PDF."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import client, get_json, keep_lang, log, slug

API = "https://www.yamaha-motor.eu/services/api/owner-manuals"
SITE = "yamaha-motor.eu"


def yamaha() -> Iterable[RegistryEntry]:
    with client() as c:
        rows = get_json(c, API, params={"category": "Motorcycles"})
    if not isinstance(rows, list):
        return
    seen: set[str] = set()
    for row in rows:
        url = (row or {}).get("cdnUrl")
        if not url:
            continue
        years = sorted({int(y) for y in (row.get("years") or []) if str(y).isdigit()})
        models = row.get("modelNames") or []
        codes = {(lg or {}).get("languageCode", "").lower() for lg in (row.get("languages") or [])}
        codes = {c2 for c2 in codes if c2}
        for lang in sorted(codes) or ["en"]:
            if not keep_lang(lang):
                continue
            for model in models or [row.get("manualId", "")]:
                eid = slug(SITE, model, years[0] if years else "", lang, "owner", row.get("manualId", "")[:8])
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="Yamaha",
                    model=str(model),
                    years=years,
                    market="EU",
                    type="owner",
                    lang=lang,
                    url=url,
                    access="free",
                    site=SITE,
                    title=f"{model} {row.get('segmentName') or ''}".strip(),
                )
    log.info("yamaha: %d entries", len(seen))

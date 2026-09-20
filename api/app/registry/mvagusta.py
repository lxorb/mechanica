"""MV Agusta: the manuals page ships its picker as a JSON literal (family -> model -> model years)
and answers the picker with a plain GET. Owner's manuals are OM_*.pdf on the MV file bucket; MM_* is
the maintenance manual. Model years come as ranges ("2021-2023")."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import BROWSER_UA, client, get_text, log, pmap, slug

PAGE = "https://www.mvagusta.com/us/en/manuals"
SITE = "mvagusta.com"
OPTIONS = re.compile(r"omListOptions\s*=\s*(\{.*?\})\s*;", re.S)
PDF = re.compile(r"https://mva-files\.s3\.amazonaws\.com/manuals/([A-Z]{2})_([^\"'<> ]+\.pdf)", re.I)
ENGLISH = re.compile(r"_(USA|UK|EN|ENG)(?:_|\.)", re.I)
KIND = {"OM": "owner", "MM": "service"}


def _years(label: str) -> list[int]:
    bits = [int(b) for b in re.findall(r"(?:19|20)\d{2}", label)]
    return list(range(bits[0], bits[-1] + 1)) if len(bits) == 2 else bits


def mv_agusta() -> Iterable[RegistryEntry]:
    with client(ua=BROWSER_UA) as c:
        page = get_text(c, PAGE) or ""
        hit = OPTIONS.search(page)
        if not hit:
            log.warning("mv_agusta: no picker options")
            return
        try:
            tree = json.loads(hit.group(1))
        except Exception:
            log.warning("mv_agusta: picker options are not json")
            return
        todo = [(fam, model, label) for fam, models in tree.items() for model, labels in models.items() for label in labels]

        def pick(job: tuple[str, str, str]):
            fam, model, label = job
            html = get_text(c, PAGE, params={"family": fam, "model": model, "my": label}) or ""
            return job, sorted(set(PDF.findall(html)))

        seen: set[str] = set()
        for (fam, model, label), docs in pmap(pick, todo):
            name = f"{fam} {model}".strip()
            years = _years(label)
            owner = [d for d in docs if d[0].upper() == "OM"]
            english = [d for d in owner if ENGLISH.search(d[1])] or ([owner[0]] if len(owner) == 1 else [])
            for prefix, tail in english + [d for d in docs if d[0].upper() == "MM"]:
                kind = KIND.get(prefix.upper())
                if not kind:
                    continue
                url = f"https://mva-files.s3.amazonaws.com/manuals/{prefix}_{tail}"
                eid = slug(SITE, name, years[0] if years else "", "US", "en", kind, tail[:18])
                if eid in seen:
                    continue
                seen.add(eid)
                yield RegistryEntry(
                    id=eid,
                    make="MV Agusta",
                    model=name,
                    years=years,
                    market="US",
                    type=kind,
                    lang="en",
                    url=url,
                    access="free",
                    site=SITE,
                    title=f"{name} {label} {'Owner' if kind == 'owner' else 'Maintenance'} Manual",
                )
        log.info("mv_agusta: %d entries from %d model years", len(seen), len(todo))

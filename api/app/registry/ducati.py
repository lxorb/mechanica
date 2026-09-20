"""Ducati owner's manuals. The PDFs are free and sit on Contentful, which serves them to anyone; the
page that names them sits behind Akamai, which serves them to nobody scriptable.

What is behind the wall (checked 2026-09-20):

* `www.ducati.com/ww/en/service-maintenance/owner-manuals` - 403 to httpx with any User-Agent, 403 to
  a *headless* Chrome, 200 to a headful Chrome. Akamai is fingerprinting the client, not the UA, so
  the only way in is a real browser; this adapter drives one over CDP and does its fetching from
  inside the page.
* The picker is three `<select>`s (family -> model -> year) whose options are filled in by the page's
  own bundle with no network call, so the tree can only be read off the DOM - hence the walk below.
* `GET /ww/en/api/bikes/bike-documents?family=&model=&year=&category=user-manuals` is the payload
  call. All three keys are required: leave `year` out and it answers `BAD_REQUEST`. The response is
  `categories[].documents[]`, each with `locales`, `years` and an `asset.url`.
* That `asset.url` is `assets.ctfassets.net/...pdf` - **no Akamai, no cookies, plain httpx gets the
  PDF**. So the browser is needed once, at crawl time, to learn the URLs; the ingest path never is.

12 families, 192 family/model pairs, 519 model years, 388 of which publish a manual.

Needs Chrome. Without it `rows()` logs and yields nothing rather than taking the crawl down.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from ..models import RegistryEntry
from ._http import log, slug

SITE = "ducati.com"
BASE = "https://www.ducati.com"
PAGE = BASE + "/ww/en/service-maintenance/owner-manuals"
DOCS = "/ww/en/api/bikes/bike-documents?family={0}&model={1}&year={2}&category=user-manuals"
CHROME = os.getenv(
    "CHROME_PATH",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)
BATCH = 60  # model years per in-page fetch loop; one CDP round trip each
PAUSE_MS = 120  # between the page's own fetches, i.e. < 2 req/s at ducati.com

# The picker prints model names in caps. Registry models elsewhere are written the way the OEM does.
_SMALL = {"and", "of", "the"}


def _pretty(name: str) -> str:
    def word(w: str) -> str:
        if not w or any(c.isdigit() for c in w) or len(w) <= 2:
            return w
        return w.lower() if w.lower() in _SMALL else w.capitalize()

    return " ".join("-".join(word(p) for p in tok.split("-")) for tok in (name or "").split())


# --- the smallest CDP client that can drive a page ------------------------------------------------


class _Browser:
    """One headful Chrome on a throwaway profile, one tab, `js()` to run code in it."""

    def __init__(self, ws, session: str):
        self.ws, self.session, self.n = ws, session, 0

    async def _call(self, method: str, params: dict) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params, "sessionId": self.session}))
        while True:
            got = json.loads(await self.ws.recv())
            if got.get("id") == self.n:
                if "error" in got:
                    raise RuntimeError(got["error"])
                return got.get("result", {})

    async def goto(self, url: str, settle: float = 12.0) -> None:
        await self._call("Page.navigate", {"url": url})
        await asyncio.sleep(settle)

    async def js(self, expr: str):
        got = await self._call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        return got.get("result", {}).get("value")


@contextmanager
def _chrome() -> Iterator[object]:
    """Yields a coroutine runner bound to a live tab, or raises if Chrome is not installed."""
    import websockets  # noqa: PLC0415  - only this adapter needs it

    if not os.path.exists(CHROME):
        raise FileNotFoundError(CHROME)
    port = random.randint(9400, 9899)
    profile = tempfile.mkdtemp(prefix="ducati-cdp")
    proc = subprocess.Popen(
        [
            CHROME,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-features=Translate,OptimizationHints",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        endpoint = None
        for _ in range(60):
            try:
                endpoint = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2))["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        if not endpoint:
            raise RuntimeError("chrome did not open a debugging port")

        def runner(work):
            async def main():
                async with websockets.connect(endpoint, max_size=256 * 1024 * 1024) as ws:
                    target = await _unsessioned(ws, 1, "Target.createTarget", {"url": "about:blank"})
                    attached = await _unsessioned(ws, 2, "Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
                    page = _Browser(ws, attached["sessionId"])
                    await page._call("Page.enable", {})
                    await page._call("Runtime.enable", {})
                    return await work(page)

            return asyncio.run(main())

        yield runner
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


async def _unsessioned(ws, mid: int, method: str, params: dict) -> dict:
    await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
    while True:
        got = json.loads(await ws.recv())
        if got.get("id") == mid:
            return got.get("result", {})


# --- the walk -------------------------------------------------------------------------------------

_TREE = """
(async()=>{
  const nap=ms=>new Promise(r=>setTimeout(r,ms));
  const box=n=>document.querySelector('select[name='+n+']');
  const opts=n=>[...box(n).options].map(o=>({v:o.value,t:o.text.trim()})).filter(o=>o.v);
  const pick=async(n,v)=>{const e=box(n);e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}));await nap(160);};
  const out=[];
  for(const f of opts('family')){
    await pick('family',f.v);
    for(const m of opts('model')){
      await pick('model',m.v);
      out.push({family:f.v,familyName:f.t,model:m.v,modelName:m.t,years:opts('year')});
    }
  }
  return JSON.stringify(out);
})()
"""

_FETCH = """
(async(tpl,pause,jobs)=>{
  const nap=ms=>new Promise(r=>setTimeout(r,ms));
  const out=[];
  for(const j of jobs){
    const u=tpl.replace('{0}',encodeURIComponent(j.family))
               .replace('{1}',encodeURIComponent(j.model))
               .replace('{2}',encodeURIComponent(j.year));
    let body=null;
    for(let a=0;a<3;a++){
      try{const r=await fetch(u,{headers:{'Accept':'application/json'}});if(r.ok){body=await r.json();break}}catch(e){}
      await nap(900);
    }
    out.push({job:j,body:body});
    await nap(pause);
  }
  return JSON.stringify(out);
})(%s,%d,%s)
"""


def _harvest() -> list[dict]:
    """Every (model year -> documents) the picker can reach. One browser, one page, many fetches."""
    with _chrome() as runner:

        async def work(page):
            await page.goto(PAGE, 14.0)
            raw = await page.js(_TREE)
            tree = json.loads(raw) if isinstance(raw, str) else []
            jobs = [
                {"family": row["family"], "familyName": row["familyName"], "model": row["model"], "modelName": row["modelName"], "year": y["v"], "yearName": y["t"]}
                for row in tree
                for y in row["years"]
            ]
            log.info("ducati: %d family/model pairs, %d model years", len(tree), len(jobs))
            found: list[dict] = []
            for start in range(0, len(jobs), BATCH):
                chunk = json.dumps(jobs[start : start + BATCH])
                got = await page.js(_FETCH % (json.dumps(DOCS), PAUSE_MS, chunk))
                if isinstance(got, str):
                    found += json.loads(got)
            return found

        return runner(work)


def _years(year_value: str, label: str) -> list[int]:
    """'MT|MS1|MS1200|15' + '2015' -> [2015]. The label is authoritative; the code is the fallback."""
    if label.isdigit() and len(label) == 4:
        return [int(label)]
    tail = year_value.rsplit("|", 1)[-1]
    if tail.isdigit() and len(tail) == 2:
        return [2000 + int(tail)]
    return []


def rows() -> Iterable[RegistryEntry]:
    try:
        harvest = _harvest()
    except Exception as exc:
        log.warning("ducati: no browser, no rows (%s: %s)", type(exc).__name__, exc)
        return
    seen: set[str] = set()
    kept = 0
    for item in harvest:
        job, body = item.get("job") or {}, item.get("body")
        if not isinstance(body, dict):
            continue
        model = _pretty(job.get("modelName") or "")
        years = _years(job.get("year") or "", job.get("yearName") or "")
        if not model or not years:
            continue
        for category in body.get("categories") or []:
            for doc in (category or {}).get("documents") or []:
                asset = (doc or {}).get("asset") or {}
                url = asset.get("url") or ""
                if not url.lower().endswith(".pdf"):
                    continue
                lang = _lang(asset.get("fileName") or "", doc.get("locales") or [])
                eid = slug(SITE, model, years[0], lang, "owner", url.rsplit("/", 2)[-2][:8])
                if eid in seen:
                    continue
                seen.add(eid)
                kept += 1
                kind = category.get("title") or "Owner's Manual"
                yield RegistryEntry(
                    id=eid,
                    make="Ducati",
                    model=model,
                    years=years,
                    market="WW",
                    type="owner",
                    lang=lang,
                    url=url,
                    access="free",
                    site=SITE,
                    title=f"{years[0]} {model} {kind}".strip(),
                )
    log.info("ducati: %d entries", kept)


_FILE_LANG = re.compile(r"-\s*([A-Z]{2})\s*-\s*MY", re.I)


def _lang(file_name: str, locales: list[str]) -> str:
    """'OM - Desert X - EN - MY23' -> 'en'. Falls back to the first locale the document declares."""
    hit = _FILE_LANG.search(file_name)
    if hit:
        return hit.group(1).lower()
    for loc in locales:
        if loc:
            return str(loc).split("-")[0].lower()
    return "en"

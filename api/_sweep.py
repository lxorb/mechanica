"""Fetch candidate pages, report status + how many .pdf links they expose."""
import re, sys, json
from concurrent.futures import ThreadPoolExecutor
from app.registry._http import client, request, BROWSER_UA
PDF = re.compile(r'https?://[^\s"\'<>()]+?\.pdf|(?<=["\'])/[^\s"\'<>()]+?\.pdf', re.I)
def one(u):
    try:
        with client(ua=BROWSER_UA) as c:
            r = request(c, "GET", u)
    except Exception as e:
        return u, f"ERR {type(e).__name__}", []
    if r is None: return u, "UNREACHABLE", []
    t = r.text if "text" in (r.headers.get("content-type") or "") or "json" in (r.headers.get("content-type") or "") else ""
    pdfs = sorted(set(PDF.findall(t)))
    return u, f"{r.status_code} {(r.headers.get('content-type') or '?').split(';')[0]} {len(t)}b", pdfs
urls = [l.strip() for l in sys.stdin if l.strip()]
with ThreadPoolExecutor(max_workers=6) as ex:
    for u, st, pdfs in ex.map(one, urls):
        print(f"{st:<34} {len(pdfs):>4} pdf  {u[:95]}")
        for p in pdfs[:4]: print(f"        {p[:130]}")

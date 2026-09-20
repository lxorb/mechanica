"""Fetch candidate pages: status, .pdf links found, and any url whose path mentions a manual."""
import re, sys
from concurrent.futures import ThreadPoolExecutor
from app.registry._http import client, request, BROWSER_UA
PDF = re.compile(r'https?://[^\s"\'<>()]+?\.pdf|(?<=["\'])/[^\s"\'<>()]+?\.pdf', re.I)
MAN = re.compile(r'https?://[^\s"\'<>()]*(?:manual|handbook|bedienung|anleitung|betriebs|owner|download|support|service)[^\s"\'<>()]*', re.I)
def one(u):
    try:
        with client(ua=BROWSER_UA) as c:
            r = request(c, "GET", u)
    except Exception as e:
        return u, f"ERR {type(e).__name__}", [], []
    if r is None: return u, "UNREACHABLE", [], []
    try: t = r.text
    except Exception: t = ""
    return u, f"{r.status_code} {(r.headers.get('content-type') or '?').split(';')[0]} {len(t)}b", sorted(set(PDF.findall(t))), sorted(set(MAN.findall(t)))
urls = [l.strip() for l in sys.stdin if l.strip()]
show = int(sys.argv[1]) if len(sys.argv)>1 else 5
with ThreadPoolExecutor(max_workers=5) as ex:
    for u, st, pdfs, mans in ex.map(one, urls):
        print(f"{st:<34} {len(pdfs):>4} pdf {len(mans):>4} man  {u[:90]}")
        for p in pdfs[:show]: print(f"    PDF {p[:140]}")
        if not pdfs:
            for m in mans[:show]: print(f"    MAN {m[:140]}")

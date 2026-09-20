"""Which of these hosts run WordPress and expose PDFs via wp-json media?"""
import sys, json
from concurrent.futures import ThreadPoolExecutor
from app.registry._http import client, request, BROWSER_UA
def one(host):
    url=f"https://{host}/wp-json/wp/v2/media?media_type=application&per_page=5"
    try:
        with client(ua=BROWSER_UA) as c:
            r=request(c,"GET",url)
    except Exception as e: return host,f"ERR {type(e).__name__}",0,[]
    if r is None: return host,"-",0,[]
    total=r.headers.get("X-WP-Total","?")
    try: items=r.json()
    except Exception: return host,f"{r.status_code} not-json",0,[]
    if not isinstance(items,list): return host,f"{r.status_code} {str(items)[:60]}",0,[]
    return host,f"{r.status_code} total={total}",len(items),[i.get("source_url","") for i in items[:4]]
hosts=[l.strip() for l in sys.stdin if l.strip()]
with ThreadPoolExecutor(max_workers=6) as ex:
    for h,st,n,urls in ex.map(one,hosts):
        print(f"{h:<32}{st}")
        for u in urls: print(f"      {u[:120]}")

import re
from app.registry._http import client, request
PDF = re.compile(r"fordservicecontent\.com[^\"'\ <>]+\.pdf", re.I)
cands = [
 "https://www.lincoln.com/support/owner-manuals/",
 "https://www.lincoln.com/owner-manuals/",
 "https://www.lincoln.com/support/owner-manuals-details/navigator/2024/",
 "https://www.lincoln.com/support/owner-manuals-details/owner-manuals-library/",
 "https://owner.lincoln.com/how-tos/owner-manuals.html",
 "https://www.lincoln.com/robots.txt",
 "https://www.ford.com/support/owner-manuals-details/navigator/2024/",
]
with client() as c:
    for u in cands:
        r = request(c, "GET", u)
        if r is None:
            print("DEAD ", u); continue
        t = r.text
        print(f"{r.status_code} len={len(t):<9} pdf={len(set(PDF.findall(t))):<4} {u[:70]} -> {str(r.url)[:70]}")

import re
from app.registry._http import client, request
PDF = re.compile(r"fordservicecontent\.com[^\"'\ <>]+\.pdf", re.I)
PAIR = re.compile(r"owner-manuals?[a-z-]*/([a-z0-9][a-z0-9-]*)/((?:19|20)\d{2})")
cands = [
 "https://www.lincoln.com/support/owner-manuals/navigator/2024/",
 "https://www.lincoln.com/support/owner-manuals/sitemap/",
 "https://www.lincoln.com/support/owner-manuals/owner-manuals-library",
 "https://www.lincoln.com/support/owner-manuals-library",
 "https://www.lincoln.com/support/owner-manual-details/navigator/2024/",
 "https://www.lincoln.com/support/owner-manuals/details/navigator/2024/",
 "https://www.ford.com/support/owner-manuals-details/owner-manuals-library?brand=lincoln",
]
with client() as c:
    for u in cands:
        r = request(c, "GET", u)
        if r is None:
            print("DEAD ", u[:80]); continue
        t = r.text
        print(f"{r.status_code} len={len(t):<8} pdf={len(set(PDF.findall(t))):<3} pairs={len(set(PAIR.findall(t))):<4} {u[:75]}")

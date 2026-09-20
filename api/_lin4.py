import re
from app.registry._http import client, get_text
with client() as c:
    t = get_text(c, "https://www.lincoln.com/support/owner-manuals/") or ""
    for m in re.finditer(r"Owner Manuals Sitemap", t):
        print("CTX:", t[max(0,m.start()-400):m.start()+120].replace("\n"," ")[-500:])
    js = get_text(c, "https://www.lincoln.com/support/owner-manuals/static/js/support-pages-owner-manual-owner-manual.370b194d.chunk.js")
print("js len", len(js or ""))
if js:
    for pat in (r'"/[a-z0-9/_.{}$-]{4,80}"', r'`[^`]{4,90}\$\{[^`]{0,60}`'):
        hits = sorted(set(re.findall(pat, js, re.I)))
        print("##", pat, len(hits))
        for h in hits[:40]: print("   ", h[:130])

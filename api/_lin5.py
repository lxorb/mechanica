import re
from app.registry._http import client, get_text
with client() as c:
    t = get_text(c, "https://www.lincoln.com/support/owner-manuals/") or ""
for pat in (r'"name":"sitemap[^}]{0,300}', r'owner-manuals[a-z0-9/-]*', r'"value":"/support/[^"]{0,90}"'):
    hits = sorted(set(re.findall(pat, t, re.I)))
    print("##", pat, len(hits))
    for h in hits[:25]: print("   ", h[:200])

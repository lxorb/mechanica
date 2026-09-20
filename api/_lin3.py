import re
from app.registry._http import client, get_text
with client() as c:
    t = get_text(c, "https://www.lincoln.com/support/owner-manuals/") or ""
print("len", len(t))
for pat in (r'https?://[^"\'\s<>]*api[^"\'\s<>]*', r'"[^"]*owner[^"]*manual[^"]*"', r'/cs/[^"\'\s<>]+', r'\.js["\']'):
    hits = sorted(set(re.findall(pat, t, re.I)))
    print("##", pat, len(hits))
    for h in hits[:14]: print("   ", h[:150])

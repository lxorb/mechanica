"""Default-UA probe. `page` fetches urls; `site` walks robots.txt -> declared sitemaps."""

import re
import sys
from concurrent.futures import ThreadPoolExecutor

from app.registry._http import client, get_text, request

PDF = re.compile(r"https?://[^\s\"'<>\\]+?\.pdf", re.I)
JSON = re.compile(r"[\"'][^\"']{2,120}\.json[\"']", re.I)
MAN = re.compile(
    r"https?://[^\s\"'<>\\]*(?:manual|handbook|torisetsu|owner|support|download|service|setsumei)[^\s\"'<>\\]*",
    re.I,
)


def page(u):
    try:
        with client() as c:
            r = request(c, "GET", u)
    except Exception as e:
        return u, "ERR %s" % type(e).__name__, [], []
    if r is None:
        return u, "DEAD", [], []
    t = r.text
    hits = sorted(set(PDF.findall(t)))[:4] + sorted(set(JSON.findall(t)))[:6]
    return u, "%s %sb -> %s" % (r.status_code, len(t), str(r.url)[:58]), hits, sorted(set(MAN.findall(t)))


def site(host):
    try:
        with client() as c:
            rb = get_text(c, "https://%s/robots.txt" % host) or ""
            sms = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rb) or ["https://%s/sitemap.xml" % host]
            man, pdf = set(), set()
            for sm in sms[:5]:
                t = get_text(c, sm) or ""
                subs = re.findall(r"<loc>([^<]+)</loc>", t)[:10] if "<sitemapindex" in t[:400] else []
                for s in subs or [None]:
                    body = get_text(c, s) if s else t
                    man |= set(MAN.findall(body or ""))
                    pdf |= set(PDF.findall(body or ""))
            return host, "%d sitemap(s)" % len(sms), sorted(pdf)[:5], sorted(man)
    except Exception as e:
        return host, "ERR %s" % type(e).__name__, [], []


mode, targets = sys.argv[1], [l.strip() for l in sys.stdin if l.strip()]
fn = page if mode == "page" else site
with ThreadPoolExecutor(max_workers=4) as ex:
    for t, st, hits, man in ex.map(fn, targets):
        print("%4dhit %4dman  %-60s %s" % (len(hits), len(man), st, t[:68]))
        for u in hits[:8]:
            print("    HIT %s" % u[:125])
        if not hits:
            for u in man[:6]:
                print("    MAN %s" % u[:125])

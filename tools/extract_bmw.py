import json
import sys
from pathlib import Path

import pymupdf

PDF = Path(__file__).resolve().parents[1] / "public" / "manuals" / "bmw-r12gs-2025-rm-en.pdf"


def doc():
    return pymupdf.open(PDF)


def info(d):
    print(f"pages {d.page_count}")
    print(f"meta {json.dumps(d.metadata, ensure_ascii=False)}")
    r = d[0].rect
    print(f"page0 {r.width:.1f}x{r.height:.1f}")


def outline(d):
    for lvl, title, page in d.get_toc():
        print(f"{'  ' * (lvl - 1)}{lvl}\t{page}\t{title}")


def frac(page, r, pad=0.004):
    w, h = page.rect.width, page.rect.height
    return {
        "x": round(r.x0 / w, 4),
        "y": round(max(0.0, r.y0 / h - pad), 4),
        "w": round((r.x1 - r.x0) / w, 4),
        "h": round((r.y1 - r.y0) / h + 2 * pad, 4),
    }


def search(d, phrases, lo=1, hi=None):
    hi = hi or d.page_count
    for phrase in phrases:
        print(f"== {phrase}")
        for i in range(lo - 1, hi):
            page = d[i]
            for r in page.search_for(phrase):
                f = frac(page, r)
                print(f"  p{i + 1}\t{f['x']},{f['y']},{f['w']},{f['h']}")


def text(d, lo, hi=None):
    hi = hi or lo
    for i in range(lo - 1, hi):
        print(f"----- page {i + 1} -----")
        print(d[i].get_text())


def lines(d, lo, hi=None):
    hi = hi or lo
    for i in range(lo - 1, hi):
        page = d[i]
        print(f"----- page {i + 1} -----")
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                s = "".join(sp["text"] for sp in l["spans"])
                if not s.strip():
                    continue
                r = pymupdf.Rect(l["bbox"])
                f = frac(page, r)
                print(f"{f['x']},{f['y']},{f['w']},{f['h']}\t{s}")


def grep(d, needle, lo=1, hi=None):
    hi = hi or d.page_count
    n = needle.lower()
    for i in range(lo - 1, hi):
        t = d[i].get_text()
        if n in t.lower():
            hit = [l.strip() for l in t.splitlines() if n in l.lower()]
            print(f"p{i + 1}\t{' | '.join(hit)[:200]}")


def main():
    d = doc()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "info":
        info(d)
    elif cmd == "outline":
        outline(d)
    elif cmd == "search":
        search(d, sys.argv[2:])
    elif cmd == "text":
        text(d, int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else None)
    elif cmd == "lines":
        lines(d, int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else None)
    elif cmd == "grep":
        grep(d, sys.argv[2])
    else:
        raise SystemExit("info|outline|search|text|lines|grep")


if __name__ == "__main__":
    main()

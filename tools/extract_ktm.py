import json
import sys

import pymupdf

sys.stdout.reconfigure(encoding="utf-8")

PDF = "public/manuals/ktm-390-duke-2024-om-en.pdf"


def doc():
    return pymupdf.open(PDF)


def frac(page, r, pad=0.004):
    w, h = page.rect.width, page.rect.height
    return {
        "page": page.number + 1,
        "x": round(r.x0 / w, 4),
        "y": round(max(r.y0 / h - pad, 0.0), 4),
        "w": round((r.x1 - r.x0) / w, 4),
        "h": round(min((r.y1 - r.y0) / h + 2 * pad, 1.0), 4),
    }


def cmd_info(d):
    print("page_count", d.page_count)
    print("metadata", json.dumps(d.metadata, ensure_ascii=False))
    p = d[0]
    print("page0_rect", p.rect)
    print("cover_text", json.dumps(p.get_text().strip()))


def cmd_toc(d):
    for lvl, title, page in d.get_toc():
        print(f"{lvl}\t{page}\t{title}")


def cmd_toc_json(d):
    print(json.dumps(d.get_toc(), ensure_ascii=False))


def cmd_search(d, phrases):
    for phrase in phrases:
        print(f"== {phrase}")
        for page in d:
            hits = page.search_for(phrase)
            if hits:
                print(f"  p{page.number + 1}: " + json.dumps([frac(page, r) for r in hits]))


def cmd_text(d, args):
    lo = int(args[0])
    hi = int(args[1]) if len(args) > 1 else lo
    for n in range(lo, hi + 1):
        print(f"=== PDF page {n} ===")
        print(d[n - 1].get_text())


def cmd_grep(d, args):
    needle = args[0].lower()
    for page in d:
        t = page.get_text()
        if needle in t.lower():
            for line in t.splitlines():
                if needle in line.lower():
                    print(f"p{page.number + 1}\t{line.strip()}")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "info"
    d = doc()
    if cmd == "info":
        cmd_info(d)
    elif cmd == "toc":
        cmd_toc(d)
    elif cmd == "toc-json":
        cmd_toc_json(d)
    elif cmd == "search":
        cmd_search(d, args[1:])
    elif cmd == "text":
        cmd_text(d, args[1:])
    elif cmd == "grep":
        cmd_grep(d, args[1:])
    else:
        raise SystemExit("info | toc | toc-json | search <phrase..> | text <from> [to] | grep <needle>")


if __name__ == "__main__":
    main()

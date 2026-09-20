"""Fetch one licence-clean photo per (make, model) from Wikimedia Commons.

Writes, and owns, only these paths:
  web/store/img/bikes/<make-model>.webp        640 px long side, q80
  web/store/img/bikes/<make-model>-thumb.webp  160 px long side, q75
  web/store/bike-images.json                   {"<make>|<model>": {image, thumb, ...}}
  web/store/CREDITS-bikes.md                   attribution table (CREDITS.md format)

The key shape matches `imageKey()` in web/counter/js/ttm.js exactly: lowercase,
NFD with combining marks dropped, runs of whitespace/dashes folded to one "-",
trimmed.  "KTM", "390 Duke" -> "ktm|390-duke".

Images are per model family, not per model-year: the roster reuses one photo for
every year of a model, which is what riders actually recognise.

    api/.venv/Scripts/python api/tools/images.py --budget-mb 120

Politeness: a single global token bucket caps every outbound request (search and
download alike) at --rps, default 2/s, with a descriptive User-Agent carrying a
contact URL, per the Wikimedia API etiquette.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import threading
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image, ImageChops

# Commons titles are full Unicode; a redirected stdout on Windows is cp1252.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - older/!TextIO streams
        pass

ROOT = Path(__file__).resolve().parents[2]
BIKES = ROOT / "api" / "data" / "bikes.json"
REGISTRY = ROOT / "api" / "data" / "registry.json"
IMG_DIR = ROOT / "web" / "store" / "img" / "bikes"
OUT_JSON = ROOT / "web" / "store" / "bike-images.json"
OUT_CREDITS = ROOT / "web" / "store" / "CREDITS-bikes.md"

API = "https://commons.wikimedia.org/w/api.php"
UA = (
    "TrustTheManualBikeImages/1.0 "
    "(https://trustthemanual.workers.dev; motorcycle manual search; "
    "one photo per model, Wikimedia Commons free licences only) httpx/0.28"
)

# The five hand-picked files that predate this tool. Never overwrite them.
PROTECTED = {
    "honda-cb650r-2021",
    "kawasaki-z650-2020",
    "suzuki-sv650-2019",
    "yamaha-mt-07-2021",
    "yamaha-yzf-r7-2022",
}

# Titles that are not a photo of a whole bike.
REJECT_WORDS = (
    "logo emblem engine badge detail tank drawing sketch diagram blueprint "
    "poster brochure advert advertisement sticker decal manual cover chart "
    "graph map speedometer tachometer dashboard cockpit instrument gauge "
    "exhaust muffler silencer carburet piston cylinder crankshaft gearbox "
    "sprocket brake caliper headlight headlamp taillight mirror seat saddle "
    "swingarm wheel rim tyre tire spoke chain clutch radiator fairing "
    "screenshot icon signature stamp coin postage grave memorial interior "
    "assembly cutaway frame_only"
).split()

CC_OK = re.compile(r"^cc[\s_-]*by(?:[\s_-]*sa)?[\s_-]*\d", re.I)
CC_BAD = re.compile(r"\b(nc|nd|noncommercial|noderiv)\b", re.I)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")
EXT = re.compile(r"\.[a-z0-9]{2,5}$", re.I)


# --------------------------------------------------------------------------- keys


def fold(value: str) -> str:
    """Mirror of imageKey()'s `part()` in ttm.js."""
    s = str(value or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[\s-]+", "-", s)
    return s.strip("-")


def image_key(make: str, model: str) -> str:
    return f"{fold(make)}|{fold(model)}"


def slug(value: str) -> str:
    s = unicodedata.normalize("NFD", str(value or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def norm(text: str) -> str:
    """Lowercase, accent-free, punctuation-as-space."""
    s = unicodedata.normalize("NFD", str(text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return WS.sub(" ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def squash(text: str) -> str:
    return norm(text).replace(" ", "")


def has_token(text_n: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text_n) is not None


def glued(haystack: str, needle: str) -> bool:
    """`needle` sits in `haystack` without a letter running into it.

    Both are squashed (alphanumerics only), so "sv650" is found inside
    "sv650al7" -- a digit then a letter starts a new word -- while "r1150r" is
    NOT found inside "r1150rs", because a letter glued to a letter continues the
    same model code and "R 1150 RS" is a different motorcycle from an R 1150 R.

    Only the character AFTER the match is tested. Squashing has already run the
    make into the model ("Kawasaki KX 500" -> "kawasakikx500"), so a letter in
    front of the match is the norm, not a signal.
    """
    at = haystack.find(needle)
    while at >= 0:
        after = haystack[at + len(needle) : at + len(needle) + 1]
        if not (after.isalpha() and needle[-1:].isalpha()):
            return True
        at = haystack.find(needle, at + 1)
    return False


def mentions(text: str, name: str) -> bool:
    """Does `text` name this bike?

    Three ways, in falling order of strictness:

    1. the tokens run consecutively, however they are punctuated -- "R 1250 GS"
       matches "BMW R 1250 GS" but not "BMW R 1250 R";
    2. the whole name, squashed, appears squashed in the text -- "CB650R"
       matches a title that spells it "CB 650 R";
    3. every token appears somewhere, in any order -- "390 Duke" matches
       "KTM Duke 390". Only for names carrying two or more tokens of three
       characters or more, and only when the text repeats a token as often as
       the name does: otherwise "R 12" matches a BMW M2 and "R 1250 R" matches
       an R 1250 GS, both of which it did.
    """
    tokens = norm(name).split()
    if not tokens:
        return False
    text_n = norm(text)
    run = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(re.escape(t) for t in tokens) + r"(?![a-z0-9])"
    if re.search(run, text_n):
        return True
    if glued(squash(text), squash(name)):
        return True
    if sum(1 for t in tokens if len(t) >= 3) < 2:
        return False
    counts = defaultdict(int)
    for t in text_n.split():
        counts[t] += 1
    need = defaultdict(int)
    for t in tokens:
        need[t] += 1
    return all(counts[t] >= n for t, n in need.items())


def strip_html(value: str) -> str:
    return WS.sub(" ", html.unescape(TAG.sub(" ", str(value or "")))).strip()


# ------------------------------------------------------------------- model roster


@dataclass
class Model:
    make: str
    model: str
    years: list
    manual: bool

    @property
    def key(self) -> str:
        return image_key(self.make, self.model)


def manual_models() -> set:
    """Folded (make, model) pairs that have a free English owner's manual on file."""
    if not REGISTRY.exists():
        return set()
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {
        (fold(r.get("make")), fold(r.get("model")))
        for r in rows
        if r.get("type") == "owner"
        and r.get("access") == "free"
        and r.get("lang") == "en"
        and r.get("make")
        and r.get("model")
    }


def build_models(limit: int = 0) -> list:
    bikes = json.loads(BIKES.read_text(encoding="utf-8"))
    have_manual = manual_models()
    groups = defaultdict(lambda: {"years": set(), "manual": False, "names": None})
    for b in bikes:
        make, model = (b.get("make") or "").strip(), (b.get("model") or "").strip()
        if not make or not model or len(norm(model).replace(" ", "")) < 2:
            continue
        pair = (fold(make), fold(model))
        g = groups[pair]
        if g["names"] is None:
            g["names"] = (make, model)
        if isinstance(b.get("year"), int):
            g["years"].add(b["year"])
        if b.get("manualId") or b.get("manualUrl") or pair in have_manual:
            g["manual"] = True

    models = [
        Model(g["names"][0], g["names"][1], sorted(g["years"]), g["manual"])
        for g in groups.values()
    ]
    # Manual-bearing models first (those are the ones the app can actually answer
    # from), then everything else newest first.
    models.sort(
        key=lambda m: (
            0 if m.manual else 1,
            -(max(m.years) if m.years else 0),
            -len(m.years),
            m.make.lower(),
            m.model.lower(),
        )
    )
    return models[:limit] if limit else models


# ------------------------------------------------------------------- http plumbing


class Bucket:
    """Global token bucket; every outbound request passes through it."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps
        self.lock = threading.Lock()
        self.next = 0.0

    def take(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait = max(0.0, self.next - now)
            self.next = max(now, self.next) + self.interval
        if wait:
            time.sleep(wait)


def get(client: httpx.Client, url: str, bucket: Bucket, *, params=None, tries=4):
    last = None
    for attempt in range(tries):
        bucket.take()
        try:
            r = client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()
                return r
        except Exception as exc:  # noqa: BLE001 - network is best effort
            last = repr(exc)
        time.sleep(min(30.0, 1.5 * (2**attempt)))
    raise RuntimeError(last or "request failed")


# --------------------------------------------------------------------- candidates


def licence_ok(short: str) -> bool:
    s = strip_html(short).strip()
    if not s or CC_BAD.search(s):
        return False
    low = s.lower()
    if low.startswith("cc0") or "public domain" in low or low in ("pd", "pd-self"):
        return True
    return bool(CC_OK.match(low))


def pick(pages: list, m: Model, used: set):
    best, best_score = None, 0.0
    model_n = norm(m.model)
    for page in pages:
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        title = str(page.get("title", "")).removeprefix("File:")
        # Match on the stem: ".jpg" is not part of the bike's name, and it
        # otherwise reads as a word glued to it ("HondaCB300F" + "jpg").
        stem = EXT.sub("", title)
        if title in used:
            continue
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        width, height = info.get("width") or 0, info.get("height") or 0
        if width < 640 or height < 1:
            continue
        ratio = width / height
        if ratio > 3.0 or ratio < 0.5:
            continue

        title_n = norm(stem)
        if any(w in title_n.split() and w not in model_n.split() for w in REJECT_WORDS):
            continue

        meta = info.get("extmetadata") or {}
        if not licence_ok((meta.get("LicenseShortName") or {}).get("value", "")):
            continue

        desc = " ".join(
            strip_html((meta.get(k) or {}).get("value", ""))
            for k in ("ObjectName", "ImageDescription", "Categories")
        )
        # The model has to be in the FILE NAME. Matching it in the description
        # instead is how a container ship in Portugal became a GasGas EX 250:
        # descriptions and category lists drag in every bike at the same show.
        # The make may come from either, since plenty of good files are titled
        # bare ("SV 650 AL7.jpg").
        haystack = f"{title} {desc}"
        if not (mentions(stem, m.model) and mentions(haystack, m.make)):
            continue

        score = 1.0
        if mentions(stem, m.make):
            score += 3.0
        if re.search(
            r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(re.escape(t) for t in model_n.split()),
            title_n,
        ):
            score += 2.0  # the model spelled out in order beats a jumbled match
        if any(has_token(title_n, str(y)) for y in m.years):
            score += 1.0
        if 1.1 <= ratio <= 2.1:
            score += 2.0
        if info.get("mime") == "image/jpeg":
            score += 0.5
        score += min(width, 4000) / 4000.0
        # "Vulcan 900 & 1500.jpg" is two bikes in one frame: a poor catalogue tile.
        if "&" in stem or has_token(title_n, "and"):
            score -= 1.5
        # "250 SX" must lose to a real 250 SX when the only candidate title says
        # "250 SX-F": a letter glued to either end of the model is a different bike.
        sq_t, sq_m = squash(stem), squash(m.model)
        at = sq_t.find(sq_m)
        if at >= 0:
            after = sq_t[at + len(sq_m) : at + len(sq_m) + 1]
            before = sq_t[at - 1 : at] if at else ""
            if after.isalpha() or before.isalpha():
                score -= 1.5
        if score > best_score:
            best, best_score = (page, info, title, meta), score
    return best


def flatten(im: Image.Image) -> Image.Image:
    """RGB, with any transparency composited onto white rather than discarded."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return im.convert("RGB")


def borders(im: Image.Image, tol: int = 12) -> tuple:
    """(left, top, right, bottom) uniform margin widths, in pixels.

    Press renders arrive as a bike floating in a wide field of flat white; as a
    catalogue tile that reads as a stretched stripe down each edge. The bounding
    box of everything that differs from the corner colour is the real picture.
    """
    w, h = im.size
    corners = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = max(set(corners), key=corners.count)
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
    box = diff.point(lambda v: 255 if v > tol else 0).getbbox()
    if not box:
        return (0, 0, 0, 0)
    return (box[0], box[1], w - box[2], h - box[3])


def debordered(im: Image.Image, min_frac: float = 0.04) -> Image.Image:
    """Crop uniform edge bands wider than `min_frac` of the picture, with a hair of padding."""
    w, h = im.size
    left, top, right, bottom = borders(im)
    if max(left, right) < min_frac * w and max(top, bottom) < min_frac * h:
        return im
    pad = max(2, round(0.015 * max(w, h)))
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(w, w - right + pad),
        min(h, h - bottom + pad),
    )
    if box[2] - box[0] < 0.25 * w or box[3] - box[1] < 0.25 * h:
        return im  # almost everything is background: leave it alone
    return im.crop(box)


def convert(raw: bytes, dest: Path, thumb: Path) -> tuple:
    with Image.open(io.BytesIO(raw)) as src:
        im = debordered(flatten(src))
        full = im.copy()
        full.thumbnail((640, 640), Image.LANCZOS)
        full.save(dest, "WEBP", quality=80, method=6)
        small = im.copy()
        small.thumbnail((160, 160), Image.LANCZOS)
        small.save(thumb, "WEBP", quality=75, method=6)
    return dest.stat().st_size, thumb.stat().st_size


# ------------------------------------------------------------------------- output


def save(path: Path, text: str) -> None:
    """Write `text` to `path`, and never raise: a checkpoint must not kill the run.

    On Windows os.replace() fails with WinError 5 for as long as anything else
    holds the destination open -- an editor, the dev server, a virus scanner --
    so retry a few times, then fall back to writing in place.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(6):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                time.sleep(0.4 * (attempt + 1))
        path.write_text(text, encoding="utf-8")
        tmp.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! checkpoint {path.name}: {exc!r}", flush=True)


def write_outputs(entries: dict) -> None:
    ordered = {k: entries[k] for k in sorted(entries)}
    save(OUT_JSON, json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")

    lines = [
        "# Bike image credits",
        "",
        "One photograph per make+model family, reused across that model's years,",
        "fetched from Wikimedia Commons by `api/tools/images.py`. Every file is CC0,",
        "CC BY, CC BY-SA, or Public Domain. Author and licence as reported by the",
        "Commons API (`extmetadata`); follow the source link for the full terms.",
        "",
        "| file | title | author | source | licence | bikez |",
        "|---|---|---|---|---|---|",
    ]
    for key in sorted(ordered):
        e = ordered[key]
        cell = lambda v: str(v or "").replace("|", "\\|")  # noqa: E731
        for path in (e["image"], e["thumb"]):
            lines.append(
                f"| `{path}` | {cell(e['title'])} | {cell(e['author'])} | "
                f"{e['source']} | {cell(e['license'])} |  |"
            )
    save(OUT_CREDITS, "\n".join(lines) + "\n")


# --------------------------------------------------------------------- band sweep


def banded(path: Path, min_frac: float = 0.04) -> bool:
    """Does this tile carry a uniform stripe down an edge?"""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            left, top, right, bottom = borders(im)
            return max(left, right) >= min_frac * w or max(top, bottom) >= min_frac * h
    except Exception:  # noqa: BLE001
        return False


def source_url(client: httpx.Client, bucket: Bucket, title: str) -> str:
    """The 640-px rendition of one Commons file, by title."""
    r = get(
        client,
        API,
        bucket,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "titles": f"File:{title}",
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            # Wider than the tile: cropping the bands off a 640-px rendition
            # would leave less than 640 px of bike.
            "iiurlwidth": "1000",
        },
    )
    for page in (r.json().get("query") or {}).get("pages") or []:
        info = (page.get("imageinfo") or [None])[0]
        if info:
            return info.get("thumburl") or info.get("url") or ""
    return ""


def fix_bands(rps: float) -> int:
    """Re-render every stored tile whose edges are flat bands. Returns the count."""
    entries = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    hits = [
        (key, e)
        for key, e in entries.items()
        if Path(e["image"]).stem not in PROTECTED and banded(ROOT / "web" / e["image"])
    ]
    print(f"{len(entries)} tiles, {len(hits)} with edge bands", flush=True)
    bucket = Bucket(rps)
    fixed = 0
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
        timeout=httpx.Timeout(30.0, connect=15.0),
        follow_redirects=True,
    ) as client:
        for key, e in hits:
            dest, thumb = ROOT / "web" / e["image"], ROOT / "web" / e["thumb"]
            try:
                url = source_url(client, bucket, e["title"])
                if not url:
                    print(f"  ! {key}: no source", flush=True)
                    continue
                convert(get(client, url, bucket).content, dest, thumb)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {key}: {exc!r}", flush=True)
                continue
            still = " (still banded)" if banded(dest) else ""
            fixed += not still
            print(f"  ~ {key}{still}", flush=True)
    print(f"re-rendered {fixed} of {len(hits)}", flush=True)
    return fixed


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = every model")
    ap.add_argument("--budget-mb", type=float, default=120.0)
    ap.add_argument("--rps", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--minutes", type=float, default=0.0, help="0 = no time limit")
    ap.add_argument("--checkpoint", type=int, default=25)
    ap.add_argument(
        "--fix-bands",
        action="store_true",
        help="re-render stored tiles that have flat stripes down an edge, then exit",
    )
    args = ap.parse_args()

    if args.fix_bands:
        fix_bands(args.rps)
        return 0

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    models = build_models(args.limit)
    manual_total = sum(1 for m in models if m.manual)

    entries = {}
    if OUT_JSON.exists():
        try:
            entries = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            entries = {}
    used = {e.get("title") for e in entries.values()}
    used_slugs = {Path(e["image"]).stem for e in entries.values()}
    bytes_used = sum(
        p.stat().st_size
        for p in IMG_DIR.glob("*.webp")
        if p.stem not in PROTECTED and p.stem.removesuffix("-thumb") not in PROTECTED
    )

    budget = args.budget_mb * 1024 * 1024
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    bucket = Bucket(args.rps)
    lock = threading.Lock()
    stats = {"attempted": 0, "hit": 0, "no_match": 0, "error": 0, "budget": 0, "done": 0}
    manual_seen = {"n": 0, "hit": 0, "announced": False}
    stop = threading.Event()

    def manual_tier_done() -> None:
        """First checkpoint that covers every manual-bearing model."""
        write_outputs(entries)
        by_make = defaultdict(lambda: [0, 0])
        for m in models:
            if not m.manual:
                continue
            by_make[m.make][0] += 1
            if m.key in entries:
                by_make[m.make][1] += 1
        rows = " ".join(
            f"{k}:{v[1]}/{v[0]}" for k, v in sorted(by_make.items(), key=lambda kv: -kv[1][0])
        )
        print(
            f"== MANUAL TIER COMPLETE == {manual_seen['hit']}/{manual_total} models with a "
            f"photo, {bytes_used / 1e6:.1f} MB\n== per make: {rows}",
            flush=True,
        )

    def fetch(m: Model) -> bool:
        """Find, download and store one photo. True when an entry exists after."""
        nonlocal bytes_used
        if stop.is_set() or m.key in entries:
            return m.key in entries
        if deadline and time.monotonic() > deadline:
            stop.set()
            return False
        with lock:
            if bytes_used >= budget:
                stats["budget"] += 1
                stop.set()
                return False
            stats["attempted"] += 1

        plain = f"{m.make} {m.model}"
        nodash = f"{m.make} {m.model.replace('-', ' ')}"
        queries = [f"{plain} filetype:bitmap"]
        if nodash != plain:
            queries.append(f"{nodash} filetype:bitmap")
        queries.append(f"{plain} motorcycle filetype:bitmap")

        chosen = None
        try:
            for q in queries:
                r = get(
                    client,
                    API,
                    bucket,
                    params={
                        "action": "query",
                        "format": "json",
                        "formatversion": "2",
                        "generator": "search",
                        "gsrsearch": q,
                        "gsrnamespace": "6",
                        "gsrlimit": "20",
                        "prop": "imageinfo",
                        "iiprop": "url|extmetadata|size|mime",
                        "iiurlwidth": "640",
                    },
                )
                pages = (r.json().get("query") or {}).get("pages") or []
                with lock:
                    chosen = pick(pages, m, used)
                if chosen:
                    break
        except Exception as exc:  # noqa: BLE001
            with lock:
                stats["error"] += 1
            print(f"  ! {m.make} {m.model}: {exc}", flush=True)
            return False

        if not chosen:
            with lock:
                stats["no_match"] += 1
            return False

        page, info, title, meta = chosen
        with lock:
            if title in used:
                stats["no_match"] += 1
                return False
            used.add(title)
            name = slug(m.key.replace("|", "-")) or slug(f"{m.make}-{m.model}")
            base, n = name, 2
            while name in used_slugs or name in PROTECTED:
                name, n = f"{base}-{n}", n + 1
            used_slugs.add(name)

        dest = IMG_DIR / f"{name}.webp"
        thumb = IMG_DIR / f"{name}-thumb.webp"
        try:
            src = info.get("thumburl") or info.get("url")
            raw = get(client, src, bucket).content
            size_full, size_thumb = convert(raw, dest, thumb)
        except Exception as exc:  # noqa: BLE001
            for p in (dest, thumb):
                p.unlink(missing_ok=True)
            with lock:
                stats["error"] += 1
                used_slugs.discard(name)
            print(f"  ! {m.make} {m.model} download: {exc}", flush=True)
            return False

        entry = {
            "image": f"store/img/bikes/{name}.webp",
            "thumb": f"store/img/bikes/{name}-thumb.webp",
            "title": title,
            "author": strip_html((meta.get("Artist") or {}).get("value", "")) or "Unknown",
            "license": strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            "source": "https://commons.wikimedia.org/wiki/"
            + quote(str(page.get("title", "")).replace(" ", "_"), safe=":/_(),.!'-"),
        }
        with lock:
            entries[m.key] = entry
            stats["hit"] += 1
            bytes_used += size_full + size_thumb
        print(f"  + {m.key} <- {title} [{entry['license']}]", flush=True)
        return True

    def work(m: Model) -> None:
        """fetch() plus the bookkeeping: checkpoints and the manual-tier report.

        Nothing in here may raise: one bad model must not take the pool down.
        """
        try:
            got = fetch(m)
        except Exception as exc:  # noqa: BLE001
            got = False
            with lock:
                stats["error"] += 1
            print(f"  ! {m.key}: {exc!r}", flush=True)
        with lock:
            stats["done"] += 1
            if m.manual:
                manual_seen["n"] += 1
                manual_seen["hit"] += int(got)
            due = stats["done"] % args.checkpoint == 0
            tier = m.manual and not manual_seen["announced"] and manual_seen["n"] >= manual_total
            if tier:
                manual_seen["announced"] = True
            if due or tier:
                write_outputs(entries)
                print(
                    f"  .. {stats['done']}/{len(models)} models, {len(entries)} images, "
                    f"{bytes_used / 1e6:.1f} MB",
                    flush=True,
                )
            if tier:
                manual_tier_done()

    print(
        f"{len(models)} models ({manual_total} with a free English owner's manual), "
        f"{len(entries)} already done, budget {args.budget_mb} MB",
        flush=True,
    )
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
        timeout=httpx.Timeout(30.0, connect=15.0),
        follow_redirects=True,
    ) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(work, models))

    write_outputs(entries)
    print(
        json.dumps(
            {
                "models_considered": len(models),
                "attempted": stats["attempted"],
                "images": len(entries),
                "new_this_run": stats["hit"],
                "no_match": stats["no_match"],
                "errors": stats["error"],
                "bytes": bytes_used,
                "mb": round(bytes_used / 1e6, 2),
                "stopped_for_budget": bool(stats["budget"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

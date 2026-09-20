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
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm  # noqa: E402

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

# A car photo that is really the cabin, the engine bay or the boot.
CAR_REJECT = (
    "interior interieur innenraum cockpit dashboard dash cabin console steering "
    "upholstery trunk boot bay underhood odometer dials dial dashboardview"
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
    kind: str = "bike"

    @property
    def key(self) -> str:
        return image_key(self.make, self.model)

    @property
    def noun(self) -> str:
        return "car" if self.kind == "car" else "motorcycle"


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
    groups = defaultdict(lambda: {"years": set(), "manual": False, "names": None, "kind": "bike"})
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
        if b.get("kind") == "car":
            g["kind"] = "car"
        if b.get("manualId") or b.get("manualUrl") or pair in have_manual:
            g["manual"] = True

    models = [
        Model(g["names"][0], g["names"][1], sorted(g["years"]), g["manual"], g["kind"])
        for g in groups.values()
    ]

    def tier(m: Model) -> int:
        """Motorcycles the app can answer from, then the cars, then the rest."""
        if m.kind == "car":
            return 1
        return 0 if m.manual else 2

    models.sort(
        key=lambda m: (
            tier(m),
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


def rank(pages: list, m: Model, used: set) -> list:
    """Every acceptable candidate, best heuristic score first."""
    out = []
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
        words = set(title_n.split()) - set(model_n.split())
        reject = REJECT_WORDS + CAR_REJECT if m.kind == "car" else REJECT_WORDS
        if words & set(reject):
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
        out.append((score, page, info, title, meta))
    out.sort(key=lambda row: -row[0])
    return out


def pick(pages: list, m: Model, used: set):
    """The single best candidate, or None."""
    top = rank(pages, m, used)
    return top[0][1:] if top else None


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
    pad = max(3, round(0.025 * max(w, h)))  # breathing room; a mirror must not touch the edge
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
        for path in (p for p in (e.get("hero"), e["image"], e["thumb"]) if p):
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


def source_url(client: httpx.Client, bucket: Bucket, title: str, width: int = 1280) -> str:
    """One Commons file's rendition at `width`, by title."""
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
            # Wider than the 640 tile: the hero is 1280, and cropping bands off
            # a 640-px rendition would leave less than 640 px of bike.
            "iiurlwidth": str(width),
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


# --------------------------------------------------------------------- the gate

SCORE_MODEL = "gpt-5.6-luna"
# A motorcycle reads best in profile; a car reads best turned three-quarter front.
VIEWS = {
    "bike": {"side": 2.0, "three_quarter": 1.8, "front": 0.6, "rear": 0.3, "other": 0.0},
    "car": {"three_quarter": 2.0, "side": 1.5, "front": 1.4, "rear": 0.3, "other": 0.0},
}

RUBRIC = (
    "You grade photographs for a vehicle manual catalogue. Each tile is one {noun}, "
    "shown whole, on a clean background, sharp enough to enlarge. Grade strictly; most "
    "snapshots are not good enough.\n"
    "single_bike: exactly one {noun} is the subject. false if a second {noun} is "
    "parked in frame, even partly, even blurred.\n"
    "whole_bike_visible: the entire {noun} is in frame, wheel to wheel, nothing "
    "cropped or hidden behind an object. false for close-ups of any part, and "
    "false for an interior, a dashboard or an engine bay.\n"
    "clean_background: 3 studio white or plain sky/wall; 2 tidy street or paddock; "
    "1 busy street, show stand, garage clutter; 0 crowd, showroom aisle, dense clutter.\n"
    "sharpness: 3 crisp and well lit; 2 acceptable; 1 soft, dim, noisy or small; "
    "0 blurred or heavily compressed.\n"
    "view: side (straight profile), three_quarter, front, rear, other.\n"
    "people_or_other_bikes: any person, or any other {noun}, visible anywhere.\n"
    "is_the_model: could this be the make and model named? false only when it is "
    "plainly a different make, a different model family, or not a {noun}.\n"
    "note: at most eight words on the worst flaw."
)


class Shot(BaseModel):
    single_bike: bool
    whole_bike_visible: bool
    clean_background: int
    sharpness: int
    view: str
    people_or_other_bikes: bool
    is_the_model: bool
    note: str


def shot_score(s: Shot, kind: str = "bike") -> float:
    """0-10 from the rubric: quality first, then how the vehicle is turned."""
    quality = 1.4 * (max(0, min(3, s.clean_background)) + max(0, min(3, s.sharpness)))
    return round(min(10.0, quality + VIEWS[kind].get(s.view, 0.0)), 2)


def passes(s: Shot, threshold: float, kind: str = "bike") -> bool:
    return (
        s.single_bike
        and s.whole_bike_visible
        and not s.people_or_other_bikes
        and s.is_the_model
        and shot_score(s, kind) >= threshold
    )


def as_jpeg(raw: bytes, width: int = 640) -> bytes:
    """A modest JPEG for the vision call: webp on disk, anything from Commons."""
    with Image.open(io.BytesIO(raw)) as src:
        im = flatten(src)
        im.thumbnail((width, width), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue()


def grade(raw: bytes, m: Model) -> Shot:
    years = f" ({m.years[0]}-{m.years[-1]})" if m.years else ""
    return llm.structured(
        "images.score",
        SCORE_MODEL,
        Shot,
        RUBRIC.format(noun=m.noun),
        [
            llm.text_part(f"Catalogue tile for a {m.make} {m.model}{years}. Grade it."),
            llm.image_part(as_jpeg(raw), "image/jpeg", "auto"),
        ],
    )


def spent() -> float:
    """USD logged against this route so far, ours and any earlier run's."""
    path = ROOT / "api" / "data" / "costs.jsonl"
    if not path.exists():
        return 0.0
    total = 0.0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if '"images.score"' in line:
                try:
                    total += float(json.loads(line).get("usd") or 0.0)
                except Exception:  # noqa: BLE001
                    pass
    return total


def renditions(raw: bytes, key_slug: str) -> tuple:
    """hero 1280/q82, tile 640/q80, thumb 160/q75. Returns (paths, bytes)."""
    hero = IMG_DIR / f"{key_slug}-hero.webp"
    dest = IMG_DIR / f"{key_slug}.webp"
    thumb = IMG_DIR / f"{key_slug}-thumb.webp"
    with Image.open(io.BytesIO(raw)) as src:
        im = debordered(flatten(src))
        big = im.copy()
        big.thumbnail((1280, 1280), Image.LANCZOS)
        big.save(hero, "WEBP", quality=82, method=6)
    size = convert(raw, dest, thumb)
    return (hero, dest, thumb), hero.stat().st_size + size[0] + size[1]


def model_for(key: str, roster: dict, entry: dict | None = None) -> Model:
    """The Model behind a bike-images key, even if bikes.json has moved on."""
    got = roster.get(key)
    if got:
        return got
    make, _, name = key.partition("|")
    kind = (entry or {}).get("kind") or "bike"
    return Model(make.replace("-", " ").title(), name.replace("-", " "), [], False, kind)


def best_candidate(client, bucket, m, used, tried, limit, threshold):
    """Search Commons, grade up to `limit` candidates, return the best that passes."""
    plain = f"{m.make} {m.model}"
    nodash = f"{m.make} {m.model.replace('-', ' ')}"
    queries = [f"{plain} filetype:bitmap"]
    if nodash != plain:
        queries.append(f"{nodash} filetype:bitmap")
    queries.append(f"{plain} {m.noun} filetype:bitmap")

    rows, seen = [], set()
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
        for row in rank((r.json().get("query") or {}).get("pages") or [], m, used):
            if row[3] in seen or row[3] in tried:
                continue
            seen.add(row[3])
            rows.append(row)
        if len(rows) >= limit:
            break

    best = None
    for _heuristic, page, info, title, meta in sorted(rows, key=lambda row: -row[0])[:limit]:
        raw = get(client, info.get("thumburl") or info.get("url"), bucket).content
        shot = grade(raw, m)
        sc = shot_score(shot, m.kind)
        if not passes(shot, threshold, m.kind):
            continue
        if best is None or sc > best[0]:
            best = (sc, page, info, title, meta, shot)
        good = ("three_quarter", "front") if m.kind == "car" else ("side", "three_quarter")
        if sc >= 8.0 and shot.view in good:
            break
    return best


def run_gate(args) -> int:
    entries = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    roster = {m.key: m for m in build_models()}
    keys = sorted(entries)
    if args.kind != "all":
        keys = [k for k in keys if (entries[k].get("kind") or "bike") == args.kind]
    if args.ungated_only:
        keys = [k for k in keys if not entries[k].get("hero")]
    used = {e.get("title") for e in entries.values()}
    bucket = Bucket(args.rps)
    lock = threading.Lock()
    stats = {
        "kept": 0,
        "kept_weak": 0,
        "replaced": 0,
        "dropped": 0,
        "graded": 0,
        "errors": 0,
        "done": 0,
    }
    swapped, start = [], spent()
    stop = threading.Event()

    def budget_left() -> bool:
        return (spent() - start) < args.usd

    def one(key: str) -> None:
        entry = entries[key]
        m = model_for(key, roster, entry)
        name = Path(entry["image"]).stem
        if name in PROTECTED or stop.is_set():
            with lock:
                stats["kept"] += 1
                stats["done"] += 1
            return
        old = dict(entry)
        try:
            tile = (ROOT / "web" / entry["image"]).read_bytes()
            shot = grade(tile, m)
            with lock:
                stats["graded"] += 1
            if passes(shot, args.threshold, m.kind):
                raw = get(client, source_url(client, bucket, entry["title"]), bucket).content
                renditions(raw, name)
                entry["hero"] = f"store/img/bikes/{name}-hero.webp"
                with lock:
                    stats["kept"] += 1
                return

            found = None
            if budget_left():
                found = best_candidate(client, bucket, m, used, {entry["title"]},
                                        args.candidates, args.threshold)
            if not found:
                # Nothing better exists. Drop only what is badly wrong -- the wrong
                # bike, a crowd, a second machine in frame. A single harsh call on
                # framing or a background is not worth leaving the model blank, and
                # the grader does make them.
                severe = (
                    not shot.is_the_model
                    or shot.people_or_other_bikes
                    or not shot.single_bike
                    or shot_score(shot, m.kind) < args.threshold - 2.0
                )
                if severe:
                    for rel in (entry.get("hero"), entry["image"], entry["thumb"]):
                        if rel:
                            (ROOT / "web" / rel).unlink(missing_ok=True)
                    with lock:
                        entries.pop(key, None)
                        stats["dropped"] += 1
                        swapped.append((key, old["title"], None, shot.note))
                    print(f"  - {key}: dropped ({shot.note})", flush=True)
                    return
                raw = get(client, source_url(client, bucket, entry["title"]), bucket).content
                renditions(raw, name)
                entry["hero"] = f"store/img/bikes/{name}-hero.webp"
                with lock:
                    stats["kept_weak"] += 1
                return

            _s, page, info, title, meta, _newshot = found
            # Re-fetch wide: the graded preview was only 640 px, the hero is 1280.
            raw = get(client, source_url(client, bucket, title) or info["url"], bucket).content
            renditions(raw, name)
            with lock:
                used.discard(old["title"])
                used.add(title)
            entry.update(
                hero=f"store/img/bikes/{name}-hero.webp",
                **({"kind": "car"} if m.kind == "car" else {}),
                title=title,
                author=strip_html((meta.get("Artist") or {}).get("value", "")) or "Unknown",
                license=strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
                source="https://commons.wikimedia.org/wiki/"
                + quote(str(page.get("title", "")).replace(" ", "_"), safe=":/_(),.!'-"),
            )
            with lock:
                stats["replaced"] += 1
                swapped.append((key, old["title"], title, shot.note))
            print(f"  ~ {key}: {old['title']} -> {title} ({shot.note})", flush=True)
        except Exception as exc:  # noqa: BLE001
            with lock:
                stats["errors"] += 1
            print(f"  ! {key}: {exc!r}", flush=True)
        finally:
            with lock:
                stats["done"] += 1
                if stats["done"] % args.checkpoint == 0:
                    write_outputs(entries)
                    used_usd = spent() - start
                    print(
                        f"  .. {stats['done']}/{len(keys)} graded, kept {stats['kept']}, "
                        f"replaced {stats['replaced']}, dropped {stats['dropped']}, "
                        f"${used_usd:.2f}",
                        flush=True,
                    )
                    if used_usd >= args.usd:
                        stop.set()

    print(f"grading {len(keys)} tiles, threshold {args.threshold}, budget ${args.usd}", flush=True)
    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
        timeout=httpx.Timeout(60.0, connect=15.0),
        follow_redirects=True,
    ) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(one, keys))

    write_outputs(entries)
    cars = sum(1 for e in entries.values() if e.get("kind") == "car")
    print(
        json.dumps(
            {
                **stats,
                "entries_after": len(entries),
                "cars_after": cars,
                "bikes_after": len(entries) - cars,
                "usd": round(spent() - start, 3),
            },
            indent=2,
        )
    )
    for row in swapped[:5]:
        print("sample:", row)
    return 0


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
    ap.add_argument(
        "--gate",
        action="store_true",
        help="grade every stored tile with the vision model, replace what fails, then exit",
    )
    ap.add_argument("--threshold", type=float, default=6.0, help="--gate: lowest score kept, 0-10")
    ap.add_argument("--candidates", type=int, default=8, help="--gate: photos graded per model")
    ap.add_argument("--usd", type=float, default=10.0, help="--gate: spend ceiling for grading")
    ap.add_argument(
        "--kind",
        choices=("all", "bike", "car"),
        default="all",
        help="restrict the queue to motorcycles or to cars",
    )
    ap.add_argument(
        "--ungated-only",
        action="store_true",
        help="--gate: skip entries that already carry a hero, i.e. already graded",
    )
    args = ap.parse_args()

    if args.fix_bands:
        fix_bands(args.rps)
        return 0
    if args.gate:
        return run_gate(args)

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    models = build_models(args.limit)
    if args.kind != "all":
        models = [m for m in models if m.kind == args.kind]
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
        queries.append(f"{plain} {m.noun} filetype:bitmap")

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
            **({"kind": "car"} if m.kind == "car" else {}),
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
                "cars_considered": sum(1 for m in models if m.kind == "car"),
                "car_images": sum(1 for e in entries.values() if e.get("kind") == "car"),
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

"""Second-pass photo hunt for the make|model families `images.py` could not fill.

`api/tools/images.py` searches Commons *filenames*. That ceiling is real: a photo
filed as `DSC_0431.jpg` inside `Category:Suzuki GSX-R 750` is unreachable to it,
and so is every model whose only good picture is the lead image of a German or
French Wikipedia article. This tool works those two seams and writes, and owns,
only these paths:

  web/store/img/bikes2/<make-model>.webp        640 px long side
  web/store/img/bikes2/<make-model>.thumb.webp  160 px long side
  web/store/bike-images-2.json                  {"<make>|<model>": {...}}
  web/store/CREDITS-bikes-2.md                  attribution table

Source waterfall per model, first acceptable candidate wins:

  1. Wikipedia article lead image, over 13 language wikis. The article *title*
     must name the model (search is loose: it.wikipedia answers "Suzuki GSX-R"
     for a GSX-R 750). The file is then resolved on Commons for its licence, so
     a local fair-use upload fails closed.
  2. Commons category. `srnamespace=14` finds the exact category title, then
     `generator=categorymembers` lists its files -- filename irrelevant.
  3. Commons relaxed file search, for models with neither.

Licences accepted: CC0, CC BY, CC BY-SA, Public Domain. Nothing NC or ND.

    api/.venv/Scripts/python api/tools/images2.py --budget-mb 150 --minutes 150

See api/docs/IMAGES-RESEARCH.md for what was tried and rejected (Openverse is
behind a Cloudflare challenge; Wikidata P18 has 394 motorcycles in total).
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
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

import httpx
from PIL import Image, ImageChops

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parents[2]
BIKES = ROOT / "api" / "data" / "bikes.json"
REGISTRY = ROOT / "api" / "data" / "registry.json"
FIRST_JSON = ROOT / "web" / "store" / "bike-images.json"  # read-only, another agent owns it
IMG_DIR = ROOT / "web" / "store" / "img" / "bikes2"
OUT_JSON = ROOT / "web" / "store" / "bike-images-2.json"
OUT_CREDITS = ROOT / "web" / "store" / "CREDITS-bikes-2.md"

COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = (
    "TrustTheManualBikeImages/2.0 "
    "(https://trustthemanual.workers.dev; motorcycle manual search; "
    "one photo per model, free licences only) httpx/0.28"
)

# Ordered by how many motorcycle-model articles each wiki actually carries.
WIKIS = ["en", "de", "fr", "es", "it", "nl", "ja", "pl", "sv", "cs", "pt", "fi", "ru"]

# Words that mean "this is not a photograph of a whole motorcycle".
REJECT_WORDS = (
    "logo emblem engine badge detail tank drawing sketch diagram blueprint "
    "poster brochure advert advertisement sticker decal manual cover chart "
    "graph map speedometer tachometer dashboard cockpit instrument gauge "
    "exhaust muffler silencer carburet carburettor carburetor piston cylinder "
    "crankshaft gearbox sprocket brake caliper headlight headlamp taillight "
    "mirror seat saddle swingarm wheel rim tyre tire spoke chain clutch "
    "radiator fairing screenshot icon signature stamp coin postage grave "
    "memorial interior assembly cutaway render rendering cad wireframe "
    "wreck crash burnt burned rusted scrap junk dismantled disassembled "
    "restoration parts spare toy model kit miniature lego diecast "
    "plate registration licence license number vin sticker key remote "
    "patent trademark scan document leaflet catalogue catalog poster"
).split()

# Category names that are about anything but the bike standing there.
REJECT_CAT_WORDS = (
    "competition racing race motorsport museum crash accident wreck "
    "advertising literature manual documents patents logos engines "
    "interiors details parts taxonomy people riders"
).split()

CC_OK = re.compile(r"^cc[\s_-]*by(?:[\s_-]*sa)?[\s_-]*\d", re.I)
CC_BAD = re.compile(r"\b(nc|nd|noncommercial|non-commercial|noderiv|no-deriv|fair use)\b", re.I)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")
EXT = re.compile(r"\.[a-z0-9]{2,5}$", re.I)
OK_MIME = ("image/jpeg", "image/png", "image/webp")


# --------------------------------------------------------------------------- keys


def fold(value: str) -> str:
    """Mirror of imageKey()'s `part()` in web/counter/js/ttm.js."""
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
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def norm(text: str) -> str:
    s = unicodedata.normalize("NFD", str(text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return WS.sub(" ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def squash(text: str) -> str:
    return norm(text).replace(" ", "")


def has_token(text_n: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text_n) is not None


def glued(haystack: str, needle: str) -> bool:
    """`needle` sits in `haystack` with no letter running out of its tail.

    "sv650" is found in "sv650al7" (digit then letter starts a new word) but
    "r1150r" is not found in "r1150rs" -- an R 1150 RS is a different bike.
    """
    at = haystack.find(needle)
    while at >= 0:
        after = haystack[at + len(needle) : at + len(needle) + 1]
        if not (after.isalpha() and needle[-1:].isalpha()):
            return True
        at = haystack.find(needle, at + 1)
    return False


def mentions(text: str, name: str) -> bool:
    """Does `text` name this bike? Same three-way test as images.py."""
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
    counts: dict = defaultdict(int)
    for t in text_n.split():
        counts[t] += 1
    need: dict = defaultdict(int)
    for t in tokens:
        need[t] += 1
    return all(counts[t] >= n for t, n in need.items())


def tight(text: str, name: str) -> bool:
    """Strict form of mentions(): the model's tokens must run consecutively.

    Used on article and category titles, where a loose match is how
    "Suzuki GSX-R" gets handed back for a GSX-R 750.
    """
    tokens = norm(name).split()
    if not tokens:
        return False
    run = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(re.escape(t) for t in tokens) + r"(?![a-z0-9])"
    if re.search(run, norm(text)):
        return True
    return glued(squash(text), squash(name))


def strip_html(value: str) -> str:
    return WS.sub(" ", html.unescape(TAG.sub(" ", str(value or "")))).strip()


# ------------------------------------------------------------------- model roster


@dataclass
class Model:
    make: str
    model: str
    years: list = field(default_factory=list)
    manual_id: bool = False
    manual_url: bool = False

    @property
    def key(self) -> str:
        return image_key(self.make, self.model)

    @property
    def tier(self) -> int:
        return 0 if self.manual_id else (1 if self.manual_url else 2)


def registry_models() -> set:
    if not REGISTRY.exists():
        return set()
    try:
        rows = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    return {
        (fold(r.get("make")), fold(r.get("model")))
        for r in rows
        if r.get("type") == "owner" and r.get("access") == "free" and r.get("make") and r.get("model")
    }


def build_models() -> list:
    """Every make|model family, ordered manualId -> manualUrl -> year count."""
    bikes = json.loads(BIKES.read_text(encoding="utf-8"))
    registry = registry_models()
    groups: dict = defaultdict(
        lambda: {"years": set(), "manual_id": False, "manual_url": False, "names": None}
    )
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
        if b.get("manualId"):
            g["manual_id"] = True
        if b.get("manualUrl") or pair in registry:
            g["manual_url"] = True

    models = [
        Model(g["names"][0], g["names"][1], sorted(g["years"]), g["manual_id"], g["manual_url"])
        for g in groups.values()
    ]
    models.sort(
        key=lambda m: (
            m.tier,
            -len(m.years),
            -(max(m.years) if m.years else 0),
            m.make.lower(),
            m.model.lower(),
        )
    )
    return models


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


def get(client: httpx.Client, url: str, bucket: Bucket, *, params=None, tries: int = 3):
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
        except Exception as exc:  # noqa: BLE001 - the network is best effort
            last = repr(exc)
        time.sleep(min(20.0, 1.2 * (2**attempt)))
    raise RuntimeError(last or "request failed")


def api_json(client: httpx.Client, url: str, bucket: Bucket, params: dict) -> dict:
    try:
        return get(client, url, bucket, params=params).json()
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------------ licences


def licence_ok(short: str) -> bool:
    s = strip_html(short).strip()
    if not s or CC_BAD.search(s):
        return False
    low = s.lower()
    if low.startswith("cc0") or "public domain" in low or low in ("pd", "pd-self", "pd-old"):
        return True
    return bool(CC_OK.match(low))


def usable(info: dict, meta: dict) -> bool:
    """Shape, size and licence gate, before any name matching."""
    if info.get("mime") not in OK_MIME:
        return False
    width, height = info.get("width") or 0, info.get("height") or 0
    if width < 640 or height < 320:
        return False
    ratio = width / height
    # Landscape or near-square only: a tall frame is a rider, a poster or a
    # detail shot far more often than a bike in profile.
    if not (0.85 <= ratio <= 3.0):
        return False
    return licence_ok((meta.get("LicenseShortName") or {}).get("value", ""))


def bad_title(stem: str, m: Model) -> bool:
    model_words = set(norm(m.model).split())
    words = set(norm(stem).split())
    return any(w in words and w not in model_words for w in REJECT_WORDS)


def score_file(stem: str, info: dict, m: Model, *, base: float) -> float:
    """How much does this file look like the catalogue tile we want?"""
    title_n = norm(stem)
    width, height = info.get("width") or 1, info.get("height") or 1
    ratio = width / height
    score = base
    if tight(stem, m.model):
        score += 2.5
    if mentions(stem, m.make):
        score += 1.5
    if any(has_token(title_n, str(y)) for y in m.years):
        score += 1.0
    if 1.15 <= ratio <= 1.85:
        score += 2.0  # a normal camera frame around a bike in profile
    elif ratio > 2.4:
        score -= 1.0  # panorama: the bike is a speck
    if info.get("mime") == "image/jpeg":
        score += 0.5
    score += min(width, 4000) / 4000.0
    if "&" in stem or has_token(title_n, "and") or has_token(title_n, "group"):
        score -= 1.5
    sq_t, sq_m = squash(stem), squash(m.model)
    at = sq_t.find(sq_m)
    if at >= 0:
        after = sq_t[at + len(sq_m) : at + len(sq_m) + 1]
        before = sq_t[at - 1 : at] if at else ""
        if after.isalpha() or before.isalpha():
            score -= 1.5  # "250 SX-F" is not a "250 SX"
    return score


# ------------------------------------------------------------- Commons file lookup


def commons_files(client: httpx.Client, bucket: Bucket, titles: list) -> list:
    """imageinfo for up to 50 `File:` titles at once."""
    out = []
    for i in range(0, len(titles), 50):
        chunk = titles[i : i + 50]
        data = api_json(
            client,
            COMMONS,
            bucket,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "titles": "|".join(chunk),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": "900",
            },
        )
        for page in (data.get("query") or {}).get("pages") or []:
            if page.get("missing") or not page.get("imageinfo"):
                continue
            out.append(page)
    return out


def candidate(page: dict, m: Model, used: set, *, base: float, need_name: bool):
    """Turn one Commons page into a scored candidate, or None."""
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    title = str(page.get("title", "")).removeprefix("File:")
    if title in used:
        return None
    meta = info.get("extmetadata") or {}
    if not usable(info, meta):
        return None
    stem = EXT.sub("", title)
    if bad_title(stem, m):
        return None
    if need_name:
        desc = " ".join(
            strip_html((meta.get(k) or {}).get("value", ""))
            for k in ("ObjectName", "ImageDescription", "Categories")
        )
        if not (mentions(stem, m.model) and mentions(f"{title} {desc}", m.make)):
            return None
    return score_file(stem, info, m, base=base), page, info, title, meta


# ------------------------------------------------------------------- source: wikis


def wiki_lead(client: httpx.Client, bucket: Bucket, m: Model, used: set, wikis: list):
    """Lead image of the first article on any wiki whose title names the model."""
    query = f"{m.make} {m.model}"
    for lang in wikis:
        data = api_json(
            client,
            f"https://{lang}.wikipedia.org/w/api.php",
            bucket,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": "0",
                "gsrlimit": "3",
                "prop": "pageimages",
                "piprop": "original",
                "pilicense": "any",
            },
        )
        for page in (data.get("query") or {}).get("pages") or []:
            title = str(page.get("title", ""))
            # The article title must name make AND model, tightly: search hands
            # back "Suzuki GSX-R" for a GSX-R 750 otherwise.
            if not (tight(title, m.model) and mentions(title, m.make)):
                continue
            src = (page.get("original") or {}).get("source") or ""
            if "/commons/" not in src:
                continue  # local upload: no Commons licence to read, fail closed
            fname = unquote(src.split("/")[-1].split("?")[0])
            if not fname:
                continue
            got = commons_files(client, bucket, [f"File:{fname}"])
            for cpage in got:
                hit = candidate(cpage, m, used, base=6.0, need_name=False)
                if hit:
                    return hit, f"wikipedia:{lang}"
    return None, None


# -------------------------------------------------------------- source: categories


def commons_category(client: httpx.Client, bucket: Bucket, m: Model, used: set):
    """Best photo inside a Commons category whose title names the model."""
    data = api_json(
        client,
        COMMONS,
        bucket,
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": f"{m.make} {m.model}",
            "srnamespace": "14",
            "srlimit": "6",
        },
    )
    cats = []
    for s in (data.get("query") or {}).get("search") or []:
        name = str(s.get("title", "")).removeprefix("Category:")
        if not (tight(name, m.model) and mentions(name, m.make)):
            continue
        words = set(norm(name).split()) - set(norm(m.model).split())
        if any(w in words for w in REJECT_CAT_WORDS):
            continue
        cats.append(s["title"])
    if not cats:
        return None, None

    best = None
    for cat in cats[:2]:
        members = api_json(
            client,
            COMMONS,
            bucket,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "generator": "categorymembers",
                "gcmtitle": cat,
                "gcmtype": "file",
                "gcmlimit": "40",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": "900",
            },
        )
        for page in (members.get("query") or {}).get("pages") or []:
            # Filename need not name the model: the category already did.
            hit = candidate(page, m, used, base=3.0, need_name=False)
            if hit and (best is None or hit[0] > best[0]):
                best = hit
        if best and best[0] >= 7.0:
            break
    return (best, "commons:category") if best else (None, None)


# ------------------------------------------------------------------ source: search


def commons_search(client: httpx.Client, bucket: Bucket, m: Model, used: set):
    """Relaxed file search, for models with neither an article nor a category."""
    plain = f"{m.make} {m.model}"
    queries = [f'"{m.make}" "{m.model}" motorcycle', f"{plain} motorcycle"]
    nodash = m.model.replace("-", " ")
    if nodash != m.model:
        queries.append(f"{m.make} {nodash} motorcycle")
    best = None
    for q in queries:
        data = api_json(
            client,
            COMMONS,
            bucket,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "generator": "search",
                "gsrsearch": q,
                "gsrnamespace": "6",
                "gsrlimit": "25",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": "900",
            },
        )
        for page in (data.get("query") or {}).get("pages") or []:
            hit = candidate(page, m, used, base=1.0, need_name=True)
            if hit and (best is None or hit[0] > best[0]):
                best = hit
        if best and best[0] >= 7.0:
            break
    return (best, "commons:search") if best else (None, None)


# ------------------------------------------------------------------------- imaging


def flatten(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return im.convert("RGB")


def borders(im: Image.Image, tol: int = 12) -> tuple:
    w, h = im.size
    corners = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = max(set(corners), key=corners.count)
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
    box = diff.point(lambda v: 255 if v > tol else 0).getbbox()
    if not box:
        return (0, 0, 0, 0)
    return (box[0], box[1], w - box[2], h - box[3])


def debordered(im: Image.Image, min_frac: float = 0.04) -> Image.Image:
    """Crop the flat bands a scan or a press render floats the bike inside."""
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
        return im
    return im.crop(box)


def boring(im: Image.Image) -> bool:
    """Near-blank tiles: a scan that came out white, a logo on a flat field."""
    small = im.convert("L").resize((64, 64), Image.BILINEAR)
    hist = small.histogram()
    top = max(hist) / float(sum(hist) or 1)
    return top > 0.82


def convert(raw: bytes, dest: Path, thumb: Path, quality: int) -> tuple:
    with Image.open(io.BytesIO(raw)) as src:
        im = debordered(flatten(src))
        if im.width < 400 or boring(im):
            raise ValueError("blank or tiny after crop")
        full = im.copy()
        full.thumbnail((640, 640), Image.LANCZOS)
        full.save(dest, "WEBP", quality=quality, method=6)
        small = im.copy()
        small.thumbnail((160, 160), Image.LANCZOS)
        small.save(thumb, "WEBP", quality=max(60, quality - 6), method=6)
    return dest.stat().st_size, thumb.stat().st_size


# -------------------------------------------------------------------------- output


def save(path: Path, text: str) -> None:
    """Write, and never raise: a checkpoint must not take the run down."""
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
        "# Bike image credits (second pass)",
        "",
        "Companion to `CREDITS-bikes.md`, for the make+model families the first pass",
        "could not fill. Fetched by `api/tools/images2.py` from Wikipedia article lead",
        "images and Wikimedia Commons categories; every file is hosted on Commons and is",
        "CC0, CC BY, CC BY-SA or Public Domain. Author and licence as reported by the",
        "Commons API (`extmetadata`); follow the source link for the full terms.",
        "",
        "| file | title | author | source | licence | via |",
        "|---|---|---|---|---|---|",
    ]
    cell = lambda v: str(v or "").replace("|", "\\|")  # noqa: E731
    for key in sorted(ordered):
        e = ordered[key]
        for path in (e["image"], e["thumb"]):
            lines.append(
                f"| `{path}` | {cell(e['title'])} | {cell(e['author'])} | "
                f"{e['source']} | {cell(e['license'])} | {cell(e.get('via'))} |"
            )
    save(OUT_CREDITS, "\n".join(lines) + "\n")


def first_pass_keys() -> tuple:
    """(keys, titles) already claimed by images.py. Re-read every checkpoint."""
    try:
        data = json.loads(FIRST_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set(), set()
    return set(data), {e.get("title") for e in data.values() if e.get("title")}


# ----------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = every missing model")
    ap.add_argument("--budget-mb", type=float, default=150.0)
    ap.add_argument("--rps", type=float, default=6.0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--checkpoint", type=int, default=25)
    ap.add_argument("--quality", type=int, default=76)
    ap.add_argument("--tier", type=int, default=2, help="highest tier to attempt (0/1/2)")
    ap.add_argument("--wikis", default=",".join(WIKIS))
    args = ap.parse_args()

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    wikis = [w for w in args.wikis.split(",") if w]

    entries = {}
    if OUT_JSON.exists():
        try:
            entries = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            entries = {}

    done_keys, done_titles = first_pass_keys()
    skip = done_keys | set(entries)
    all_models = build_models()
    models = [m for m in all_models if m.key not in skip and m.tier <= args.tier]
    if args.limit:
        models = models[: args.limit]

    used = set(done_titles) | {e.get("title") for e in entries.values()}
    used_slugs = {Path(e["image"]).stem for e in entries.values()}
    bytes_used = sum(p.stat().st_size for p in IMG_DIR.glob("*.webp"))

    budget = args.budget_mb * 1024 * 1024
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    bucket = Bucket(args.rps)
    lock = threading.Lock()
    stats: dict = defaultdict(int)
    stop = threading.Event()

    def refresh_first_pass() -> None:
        """The first agent is still running: never take a model or file it owns."""
        keys, titles = first_pass_keys()
        with lock:
            used.update(titles)
            stats["first_pass"] = len(keys)
        return keys

    def fetch(client: httpx.Client, m: Model) -> bool:
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

        chosen = via = None
        for source in (wiki_lead, commons_category, commons_search):
            try:
                if source is wiki_lead:
                    hit, tag = source(client, bucket, m, used, wikis)
                else:
                    hit, tag = source(client, bucket, m, used)
            except Exception as exc:  # noqa: BLE001
                stats["error"] += 1
                print(f"  ! {m.key} {source.__name__}: {exc!r}"[:160], flush=True)
                continue
            if hit:
                chosen, via = hit, tag
                break

        if not chosen:
            with lock:
                stats["no_match"] += 1
            return False

        _score, page, info, title, meta = chosen
        with lock:
            if title in used:
                stats["dupe"] += 1
                return False
            used.add(title)
            name = slug(m.key.replace("|", "-")) or slug(f"{m.make}-{m.model}")
            base, n = name, 2
            while name in used_slugs:
                name, n = f"{base}-{n}", n + 1
            used_slugs.add(name)

        dest = IMG_DIR / f"{name}.webp"
        thumb = IMG_DIR / f"{name}.thumb.webp"
        try:
            src = info.get("thumburl") or info.get("url")
            raw = get(client, src, bucket).content
            size_full, size_thumb = convert(raw, dest, thumb, args.quality)
        except Exception as exc:  # noqa: BLE001
            for p in (dest, thumb):
                p.unlink(missing_ok=True)
            with lock:
                stats["error"] += 1
                used_slugs.discard(name)
            print(f"  ! {m.key} download: {exc}"[:160], flush=True)
            return False

        entry = {
            "image": f"store/img/bikes2/{name}.webp",
            "thumb": f"store/img/bikes2/{name}.thumb.webp",
            "title": title,
            "author": strip_html((meta.get("Artist") or {}).get("value", "")) or "Unknown",
            "license": strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            "source": "https://commons.wikimedia.org/wiki/"
            + quote(str(page.get("title", "")).replace(" ", "_"), safe=":/_(),.!'-"),
            "via": via,
        }
        with lock:
            entries[m.key] = entry
            stats["hit"] += 1
            stats[f"src:{via}"] += 1
            stats[f"tier{m.tier}:hit"] += 1
            bytes_used += size_full + size_thumb
        print(f"  + {m.key} <- {title} [{entry['license']}] via {via}", flush=True)
        return True

    def work(client: httpx.Client, m: Model) -> None:
        try:
            got = fetch(client, m)
        except Exception as exc:  # noqa: BLE001
            got = False
            with lock:
                stats["error"] += 1
            print(f"  ! {m.key}: {exc!r}"[:160], flush=True)
        with lock:
            stats["done"] += 1
            stats[f"tier{m.tier}:done"] += 1
            due = stats["done"] % args.checkpoint == 0
        if due:
            write_outputs(entries)
            refresh_first_pass()
            print(
                f"  .. {stats['done']}/{len(models)} tried, {len(entries)} new images, "
                f"{bytes_used / 1e6:.1f} MB, hit rate "
                f"{100 * stats['hit'] / max(1, stats['attempted']):.0f}%",
                flush=True,
            )

    tiers = defaultdict(int)
    for m in models:
        tiers[m.tier] += 1
    print(
        f"{len(all_models)} model families, {len(done_keys)} already done by images.py, "
        f"{len(entries)} done here; {len(models)} to try "
        f"(manualId {tiers[0]}, manualUrl {tiers[1]}, rest {tiers[2]}); "
        f"budget {args.budget_mb} MB"
        + (f", {args.minutes:.0f} min" if args.minutes else ""),
        flush=True,
    )

    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
        timeout=httpx.Timeout(30.0, connect=15.0),
        follow_redirects=True,
    ) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(lambda m: work(client, m), models))

    write_outputs(entries)
    print(
        json.dumps(
            {
                "tried": stats["done"],
                "new_images": stats["hit"],
                "total_entries": len(entries),
                "no_match": stats["no_match"],
                "errors": stats["error"],
                "dupes": stats["dupe"],
                "mb": round(bytes_used / 1e6, 2),
                "by_source": {k[4:]: v for k, v in sorted(stats.items()) if k.startswith("src:")},
                "by_tier": {k: v for k, v in sorted(stats.items()) if k.startswith("tier")},
                "stopped_for_budget": bool(stats["budget"]),
                "stopped_for_time": stop.is_set() and not stats["budget"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

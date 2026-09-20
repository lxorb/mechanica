"""Second-pass photo hunt for the make|model families `images.py` could not fill.

`api/tools/images.py` searches Commons *filenames*. That ceiling is real: a photo
filed as `DSC_0431.jpg` inside `Category:Suzuki GSX-R 750` is invisible to it, and
so is every model whose only good picture is the lead image of a German or French
Wikipedia article. This tool works those two seams, and then makes a vision model
pick the frame, because "a photo exists" and "a photo a rider wants to look at"
are different bars.

Writes, and owns, only these paths:

  web/store/img/bikes2/<make-model>.hero.webp   1280 px long side
  web/store/img/bikes2/<make-model>.webp         640 px long side
  web/store/img/bikes2/<make-model>.thumb.webp   160 px long side
  web/store/bike-images-2.json                   {"<make>|<model>": {...}}
  web/store/CREDITS-bikes-2.md                   attribution table

Per model:

  1. Gather up to --candidates free-licence Commons files from three sources --
     Wikipedia article lead images over several language wikis, Commons model
     categories, then relaxed Commons file search.
  2. Download a 400-px preview of each and score them all in ONE gpt-5.6-luna
     call (route "images.score"): single bike, whole bike in frame, clean
     background, sharpness, camera angle, clutter, right model.
  3. Keep only candidates that pass every hard gate, rank by view (side and
     three-quarter first) plus background and sharpness, and store the winner.

Licences accepted: CC0, CC BY, CC BY-SA, Public Domain. Nothing NC or ND, and a
file that is not hosted on Commons is rejected rather than guessed at.

    api/.venv/Scripts/python api/tools/images2.py --budget-mb 150 --minutes 150

See api/docs/IMAGES-RESEARCH.md for what was tried and rejected (Openverse sits
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
from typing import Literal
from urllib.parse import quote, unquote

import httpx
from PIL import Image, ImageChops, ImageFilter, ImageStat
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from app import llm  # noqa: E402
from app.llm import image_part, structured, text_part  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BIKES = ROOT / "api" / "data" / "bikes.json"
REGISTRY = ROOT / "api" / "data" / "registry.json"
FIRST_JSON = ROOT / "web" / "store" / "bike-images.json"  # read-only; another agent owns it
IMG_DIR = ROOT / "web" / "store" / "img" / "bikes2"
OUT_JSON = ROOT / "web" / "store" / "bike-images-2.json"
OUT_CREDITS = ROOT / "web" / "store" / "CREDITS-bikes-2.md"

COMMONS = "https://commons.wikimedia.org/w/api.php"
FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"
UA = (
    "TrustTheManualBikeImages/2.0 "
    "(https://trustthemanual.workers.dev; motorcycle manual search; "
    "one photo per model, free licences only) httpx/0.28"
)

# Ordered by how many motorcycle-model articles each wiki actually carries.
WIKIS = ["en", "de", "fr", "es", "it", "nl", "ja", "pl", "sv", "cs"]

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
    "restoration parts spare toy miniature lego diecast plate registration "
    "licence license vin key patent trademark scan document leaflet"
).split()

# Categories that are about anything but the bike standing there.
REJECT_CAT_WORDS = (
    "competition racing race motorsport museum crash accident wreck "
    "advertising literature manuals documents patents logos engines "
    "interiors details parts people riders taxonomy"
).split()

CC_OK = re.compile(r"^cc[\s_-]*by(?:[\s_-]*sa)?[\s_-]*\d", re.I)
CC_BAD = re.compile(r"\b(nc|nd|noncommercial|non-commercial|noderiv|no-deriv|fair\s*use)\b", re.I)
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
    return re.sub(r"[\s-]+", "-", s).strip("-")


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

    "sv650" is found in "sv650al7" (a digit then a letter starts a new word) but
    "r1150r" is not found in "r1150rs": an R 1150 RS is a different motorcycle.
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
    """Strict mentions(): the model's tokens must run consecutively.

    For article and category titles, where the loose form is how "Suzuki GSX-R"
    gets handed back as the answer for a GSX-R 750.
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


CODE = re.compile(r"^([a-z]{1,4})[\s-]?(\d{2,4})([a-z]{0,4})$", re.I)


def name_variants(model: str, cap: int = 4) -> list:
    """The model name, then progressively shorter family names.

    What images.py left behind is overwhelmingly *variants*: "RSV4 1100 Factory",
    "VN900 Classic Special Edition", "CB650RAC". Commons photographs families, not
    trim levels, so falling back to "RSV4 1100" and then "RSV4" is the difference
    between a tile and a placeholder -- and it is what lookupImage() in ttm.js
    already does at render time. Longest first: the caller stops at the first one
    that answers.
    """
    out: list = []
    seen: set = set()

    def add(value: str) -> None:
        v = " ".join(str(value or "").split())
        k = squash(v)
        if v and len(k) >= 2 and k not in seen:
            seen.add(k)
            out.append(v)

    add(model)
    tokens = model.split()
    numbered = any(ch.isdigit() for ch in model)
    for n in range(len(tokens) - 1, 0, -1):
        prefix = tokens[:n]
        # A displacement or model number is the bike's identity: never shorten
        # past it, or "VN900 Classic" degrades to a search for "Classic".
        if numbered and not any(any(c.isdigit() for c in t) for t in prefix):
            break
        add(" ".join(prefix))
    # One glued code: peel the trailing trim letters, "CB650RAC" -> "CB650R" -> "CB650".
    tail_variant = out[-1].split()
    if len(tail_variant) == 1 and (mt := CODE.match(tail_variant[0])):
        head, num, tail = mt.groups()
        for i in range(len(tail) - 1, -1, -1):
            add(f"{head}{num}{tail[:i]}")
    return out[:cap]


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

    @property
    def label(self) -> str:
        span = ""
        if self.years:
            span = f" ({min(self.years)}" + (f"-{max(self.years)})" if max(self.years) != min(self.years) else ")")
        return f"{self.make} {self.model}{span}"


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
    """Token bucket. One for the APIs, a looser one for the CDN."""

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

    def penalise(self, seconds: float) -> None:
        """A 429 stalls every worker, not just the one that saw it."""
        with self.lock:
            self.next = max(self.next, time.monotonic()) + seconds


def get(client: httpx.Client, url: str, bucket: Bucket, *, params=None, tries: int = 3):
    last = None
    for attempt in range(tries):
        bucket.take()
        try:
            r = client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                if r.status_code == 429:
                    bucket.penalise(5.0)
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


def filepath_url(title: str, width: int) -> str:
    """Special:FilePath renders any width without spending an API call."""
    return f"{FILEPATH}{quote(title.replace(' ', '_'), safe='')}?width={width}"


# ------------------------------------------------------------------------ licences


def licence_ok(short: str) -> bool:
    s = strip_html(short).strip()
    if not s or CC_BAD.search(s):
        return False
    low = s.lower()
    if low.startswith("cc0") or "public domain" in low or low.startswith("pd"):
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
    # detail shot far more often than it is a bike in profile.
    if not (0.85 <= ratio <= 3.0):
        return False
    return licence_ok((meta.get("LicenseShortName") or {}).get("value", ""))


def bad_title(stem: str, m: Model) -> bool:
    model_words = set(norm(m.model).split())
    words = set(norm(stem).split())
    return any(w in words and w not in model_words for w in REJECT_WORDS)


def prescore(stem: str, info: dict, m: Model, *, base: float) -> float:
    """Cheap ordering, so the vision model sees the most promising frames first."""
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


# ----------------------------------------------------------------------- gathering


@dataclass
class Cand:
    title: str
    page_title: str
    info: dict
    meta: dict
    via: str
    pre: float
    depth: int = 0


def commons_pages(client: httpx.Client, bucket: Bucket, titles: list) -> list:
    """imageinfo for up to 50 `File:` titles at once."""
    out = []
    for i in range(0, len(titles), 50):
        data = api_json(
            client,
            COMMONS,
            bucket,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "titles": "|".join(titles[i : i + 50]),
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
            },
        )
        for page in (data.get("query") or {}).get("pages") or []:
            if not page.get("missing") and page.get("imageinfo"):
                out.append(page)
    return out


def to_cand(page: dict, m: Model, used: set, *, via: str, base: float, need_name: bool):
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    page_title = str(page.get("title", ""))
    title = page_title.removeprefix("File:")
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
    return Cand(title, page_title, info, meta, via, prescore(stem, info, m, base=base))


def from_wikis(client: httpx.Client, bucket: Bucket, m: Model, used: set, wikis: list) -> list:
    """Lead images of articles whose title names the model, across wikis."""
    files, seen = [], set()
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
                "gsrsearch": f"{m.make} {m.model}",
                "gsrnamespace": "0",
                "gsrlimit": "3",
                "prop": "pageimages",
                "piprop": "original",
                "pilicense": "any",
            },
        )
        for page in (data.get("query") or {}).get("pages") or []:
            title = str(page.get("title", ""))
            # The article title must name make AND model, tightly.
            if not (tight(title, m.model) and mentions(title, m.make)):
                continue
            src = (page.get("original") or {}).get("source") or ""
            if "/commons/" not in src:
                continue  # local upload: no Commons licence to read, so fail closed
            fname = unquote(src.split("/")[-1].split("?")[0])
            if fname and fname not in seen:
                seen.add(fname)
                files.append(f"File:{fname}")
        if len(files) >= 3:
            break
    if not files:
        return []
    return [
        c
        for page in commons_pages(client, bucket, files)
        if (c := to_cand(page, m, used, via="wikipedia", base=6.0, need_name=False))
    ]


def from_category(client: httpx.Client, bucket: Bucket, m: Model, used: set, want: int) -> list:
    """Photos inside a Commons category whose title names the model."""
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
        extra = set(norm(name).split()) - set(norm(m.model).split())
        if any(w in extra for w in REJECT_CAT_WORDS):
            continue
        cats.append(s["title"])

    out = []
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
                "gcmlimit": "50",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
            },
        )
        for page in (members.get("query") or {}).get("pages") or []:
            # The filename need not name the model: the category already did.
            c = to_cand(page, m, used, via="category", base=3.0, need_name=False)
            if c:
                out.append(c)
        if len(out) >= want:
            break
    return out


def from_search(client: httpx.Client, bucket: Bucket, m: Model, used: set, want: int) -> list:
    """Relaxed file search, for models with neither an article nor a category."""
    queries = [f'"{m.make}" "{m.model}" motorcycle', f"{m.make} {m.model} motorcycle"]
    nodash = m.model.replace("-", " ")
    if nodash != m.model:
        queries.append(f"{m.make} {nodash} motorcycle")
    out = []
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
            },
        )
        for page in (data.get("query") or {}).get("pages") or []:
            c = to_cand(page, m, used, via="search", base=1.0, need_name=True)
            if c:
                out.append(c)
        if len(out) >= want:
            break
    return out


def gather(client: httpx.Client, bucket: Bucket, m: Model, used: set, wikis: list, want: int) -> list:
    """Up to `want` licence-clean candidates, best-looking first.

    Tries the exact model name, then shorter family names, and stops at the first
    that produces anything: an exact "RSV4 1100 Factory" photo beats an "RSV4" one,
    but an "RSV4" photo beats the placeholder tile.
    """
    found: dict = {}
    for depth, name in enumerate(name_variants(m.model)):
        probe = Model(m.make, name, m.years, m.manual_id, m.manual_url)
        for source in (
            lambda: from_wikis(client, bucket, probe, used, wikis),
            lambda: from_category(client, bucket, probe, used, want),
            lambda: from_search(client, bucket, probe, used, want),
        ):
            try:
                for c in source():
                    c.depth = depth
                    c.pre -= 0.75 * depth  # prefer the most specific name that answered
                    found.setdefault(c.title, c)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {m.key} gather: {exc!r}"[:150], flush=True)
            if len(found) >= want:
                break
        if found:
            break
    return sorted(found.values(), key=lambda c: -c.pre)[:want]


# ------------------------------------------------------------------- vision rating


class Shot(BaseModel):
    index: int = Field(description="the image number given in the prompt")
    is_photo: bool = Field(description="a real photograph, not a drawing, render, poster or scan")
    is_the_model: bool = Field(description="the bike shown is plausibly the named make and model")
    single_bike: bool = Field(description="exactly one motorcycle is the subject")
    whole_bike_visible: bool = Field(description="the entire motorcycle is inside the frame, not cropped")
    people_or_other_bikes: bool = Field(description="people, or other motorcycles, take up a noticeable part of the frame")
    clean_background: Literal[0, 1, 2, 3] = Field(description="0 cluttered showroom or crowd, 3 plain road, wall or studio")
    sharpness: Literal[0, 1, 2, 3] = Field(description="0 blurry or tiny, 3 crisp and well exposed")
    view: Literal["side", "three_quarter", "front", "rear", "top", "other"]


class Shots(BaseModel):
    shots: list[Shot]


RATER_SYSTEM = (
    "You grade candidate photographs for a motorcycle catalogue. Each tile has to show "
    "one whole motorcycle that a rider can recognise at a glance: side or three-quarter "
    "view, the bike filling the frame, nothing cluttering it. Judge only what you can see. "
    "Be strict about people_or_other_bikes: a crowded show stand, a parked row, or a rider "
    "sitting on the bike all count as true. Return exactly one entry per image, in order, "
    "using the index given in the prompt."
)

VIEW_BONUS = {"side": 3.0, "three_quarter": 3.0, "front": 0.5, "rear": 0.5, "top": -2.0, "other": 0.0}


def passes(s: Shot) -> bool:
    return (
        s.is_photo
        and s.is_the_model
        and s.single_bike
        and s.whole_bike_visible
        and not s.people_or_other_bikes
        and s.clean_background >= 1
        and s.sharpness >= 2
    )


def shot_score(s: Shot) -> float:
    return VIEW_BONUS.get(s.view, 0.0) + s.clean_background + 1.5 * s.sharpness


def rate(m: Model, previews: list) -> list:
    """One call, every candidate. `previews` is [(Cand, jpeg_bytes, mime)]."""
    parts = [
        text_part(
            f"Motorcycle: {m.label}.\n"
            f"{len(previews)} candidate photo(s) follow, numbered from 0. "
            "Grade each one."
        )
    ]
    for i, (_c, data, mime) in enumerate(previews):
        parts.append(text_part(f"Image {i}:"))
        parts.append(image_part(data, mime, "low"))
    out = structured("images.score", "gpt-5.6-luna", Shots, RATER_SYSTEM, parts)
    by_index = {s.index: s for s in out.shots}
    return [by_index.get(i) for i in range(len(previews))]


# ------------------------------------------------------------------------- imaging


def outputs(dest: Path) -> tuple:
    """The three renditions written for one model, largest first."""
    return (
        dest.parent / f"{dest.name}.hero.webp",
        dest.parent / f"{dest.name}.webp",
        dest.parent / f"{dest.name}.thumb.webp",
    )


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
    """Crop the flat bands a scan or a catalogue tile floats the bike inside."""
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


def blurry(im: Image.Image) -> bool:
    """Edge energy, as a second opinion on the rater's sharpness score.

    A vision model looking at a 512-px downsample cannot see camera shake; the
    variance of a Laplacian over the real pixels can.
    """
    grey = im.convert("L")
    grey.thumbnail((512, 512), Image.BILINEAR)
    edges = grey.filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges).stddev[0] < 9.0


def boring(im: Image.Image) -> bool:
    """Near-blank tiles: a scan that came out white, a mark on a flat field."""
    small = im.convert("L").resize((64, 64), Image.BILINEAR)
    hist = small.histogram()
    return max(hist) / float(sum(hist) or 1) > 0.82


def render(raw: bytes, dest: Path, q: tuple) -> tuple:
    """Write <name>.hero/.webp/.thumb webps. Returns (bytes written, has_hero)."""
    hero_q, full_q, thumb_q = q
    hero_p, full_p, thumb_p = outputs(dest)
    with Image.open(io.BytesIO(raw)) as src:
        im = debordered(flatten(src))
        if im.width < 500 or boring(im) or blurry(im):
            raise ValueError("blank, blurry or tiny after crop")
        written = 0
        hero = False
        if im.width >= 900:
            big = im.copy()
            big.thumbnail((1280, 1280), Image.LANCZOS)
            big.save(hero_p, "WEBP", quality=hero_q, method=6)
            written += hero_p.stat().st_size
            hero = True
        full = im.copy()
        full.thumbnail((640, 640), Image.LANCZOS)
        full.save(full_p, "WEBP", quality=full_q, method=6)
        written += full_p.stat().st_size
        small = im.copy()
        small.thumbnail((160, 160), Image.LANCZOS)
        small.save(thumb_p, "WEBP", quality=thumb_q, method=6)
        written += thumb_p.stat().st_size
    return written, hero


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
        "Companion to `CREDITS-bikes.md`, for the make+model families the first pass could",
        "not fill. Fetched by `api/tools/images2.py` from Wikipedia article lead images and",
        "Wikimedia Commons categories, then graded by a vision model so every tile shows one",
        "whole bike. Each file is hosted on Commons under CC0, CC BY, CC BY-SA or Public",
        "Domain; author and licence as reported by the Commons API (`extmetadata`). Follow",
        "the source link for the full terms.",
        "",
        "| file | title | author | source | licence | via | view |",
        "|---|---|---|---|---|---|---|",
    ]
    cell = lambda v: str(v or "").replace("|", "\\|")  # noqa: E731
    for key in sorted(ordered):
        e = ordered[key]
        for path in (e.get("hero"), e["image"], e["thumb"]):
            if not path:
                continue
            lines.append(
                f"| `{path}` | {cell(e['title'])} | {cell(e['author'])} | {e['source']} | "
                f"{cell(e['license'])} | {cell(e.get('via'))} | {cell(e.get('view'))} |"
            )
    save(OUT_CREDITS, "\n".join(lines) + "\n")


ALIAS_FIELDS = ("image", "thumb", "hero", "title", "author", "license", "source", "view")


def alias_pass(models: list, entries: dict, filled: dict) -> int:
    """Point variant keys at the family photo that is already on disk.

    "Aprilia RSV4 1100 Factory" has no Commons photo of its own and never will,
    but "Aprilia RSV4 1100" does, and it is the same motorcycle to anyone looking
    at a 160-px tile. Reusing the rendered file costs no bytes, no request and no
    tokens, and the credit is unchanged because it is literally the same
    photograph. Returns how many keys were filled.
    """
    added = 0
    for m in models:
        if m.key in entries or m.key in filled:
            continue
        for name in name_variants(m.model, cap=5)[1:]:
            parent = image_key(m.make, name)
            src = filled.get(parent) or entries.get(parent)
            if not src or not src.get("image"):
                continue
            entry = {k: src[k] for k in ALIAS_FIELDS if src.get(k)}
            entry["via"] = "alias"
            entry["aliasOf"] = parent
            entries[m.key] = entry
            added += 1
            break
    return added


def first_pass() -> tuple:
    """(map, titles) already claimed by images.py. Re-read at every checkpoint."""
    try:
        data = json.loads(FIRST_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}, set()
    return data, {e.get("title") for e in data.values() if e.get("title")}


# ----------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = every missing model")
    ap.add_argument("--budget-mb", type=float, default=150.0)
    ap.add_argument("--llm-budget", type=float, default=8.0, help="USD cap for images.score")
    ap.add_argument("--api-rps", type=float, default=8.0)
    ap.add_argument("--cdn-rps", type=float, default=16.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--checkpoint", type=int, default=25)
    ap.add_argument("--candidates", type=int, default=6)
    ap.add_argument("--min-score", type=float, default=6.0)
    ap.add_argument("--quality", default="70,76,72", help="hero,full,thumb webp quality")
    ap.add_argument("--tier", type=int, default=2, help="highest tier to attempt (0/1/2)")
    ap.add_argument("--wikis", default=",".join(WIKIS))
    ap.add_argument("--no-alias", action="store_true", help="skip the variant-key alias pass")
    args = ap.parse_args()

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    wikis = [w for w in args.wikis.split(",") if w]
    quality = tuple(int(x) for x in args.quality.split(","))

    entries = {}
    if OUT_JSON.exists():
        try:
            entries = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            entries = {}

    filled, done_titles = first_pass()
    all_models = build_models()

    # Free coverage first: every variant key whose family photo is already on disk.
    if not args.no_alias:
        aliased = alias_pass(all_models, entries, filled)
        if aliased:
            write_outputs(entries)
            print(f"alias pass: {aliased} variant keys pointed at an existing photo", flush=True)

    models = [
        m for m in all_models if m.key not in filled and m.key not in entries and m.tier <= args.tier
    ]
    if args.limit:
        models = models[: args.limit]

    used = set(done_titles) | {e.get("title") for e in entries.values()}
    used_slugs = {
        Path(e["image"]).name.split(".")[0]
        for e in entries.values()
        if e.get("image", "").startswith("store/img/bikes2/")
    }
    bytes_used = sum(p.stat().st_size for p in IMG_DIR.glob("*.webp"))

    budget = args.budget_mb * 1024 * 1024
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    api_bucket, cdn_bucket = Bucket(args.api_rps), Bucket(args.cdn_rps)
    lock = threading.Lock()
    stats: dict = defaultdict(int)
    spend = {"usd": 0.0}
    stop = threading.Event()

    # llm.structured() logs through llm.log(); wrap it to keep a running total.
    original_log = llm.log

    def logging_log(route, model, usage, extra_usd: float = 0.0) -> float:
        cost = original_log(route, model, usage, extra_usd)
        with lock:
            spend["usd"] += cost
        return cost

    llm.log = logging_log

    def preview(client: httpx.Client, c: Cand):
        try:
            r = get(client, filepath_url(c.title, 400), cdn_bucket, tries=2)
        except Exception:  # noqa: BLE001
            return None
        mime = r.headers.get("content-type", "").split(";")[0]
        if mime not in OK_MIME or len(r.content) < 2000:
            return None
        return (c, r.content, mime)

    def fetch(client: httpx.Client, m: Model) -> bool:
        nonlocal bytes_used
        if stop.is_set():
            return False
        if deadline and time.monotonic() > deadline:
            stop.set()
            return False
        with lock:
            if bytes_used >= budget:
                stats["budget"] += 1
                stop.set()
                return False
            over_llm = spend["usd"] >= args.llm_budget
            stats["attempted"] += 1

        cands = gather(client, api_bucket, m, used, wikis, args.candidates)
        with lock:
            stats["cands"] += len(cands)
            for c in cands:
                stats[f"cand:{c.via}"] += 1
        if not cands:
            with lock:
                stats["no_candidate"] += 1
            return False

        previews = [p for p in (preview(client, c) for c in cands) if p]
        if not previews:
            with lock:
                stats["no_preview"] += 1
            return False

        if over_llm:
            # Cost cap reached: fall back to the heuristic pick, unrated.
            ranked = [(previews[0][0], None, 0.0)]
            with lock:
                stats["unrated"] += 1
        else:
            try:
                shots = rate(m, previews)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    stats["rate_error"] += 1
                print(f"  ! {m.key} rate: {exc!r}"[:150], flush=True)
                return False
            ranked = []
            with lock:
                stats["rated"] += len(previews)
            for (c, _data, _mime), s in zip(previews, shots):
                if s is None:
                    continue
                with lock:
                    stats[f"scored:{c.via}"] += 1
                if not passes(s):
                    with lock:
                        stats[f"failed:{c.via}"] += 1
                    continue
                score = shot_score(s)
                with lock:
                    stats[f"passed:{c.via}"] += 1
                if score >= args.min_score:
                    ranked.append((c, s, score))
            ranked.sort(key=lambda t: (-t[2], -t[0].pre))

        if not ranked:
            with lock:
                stats["rejected"] += 1
            return False

        for chosen, shot, score in ranked[:3]:
            with lock:
                if chosen.title in used:
                    continue
                used.add(chosen.title)
                name = slug(m.key.replace("|", "-")) or slug(f"{m.make}-{m.model}")
                stem, n = name, 2
                while name in used_slugs:
                    name, n = f"{stem}-{n}", n + 1
                used_slugs.add(name)

            dest = IMG_DIR / name
            try:
                raw = get(client, filepath_url(chosen.title, 1280), cdn_bucket).content
                written, hero = render(raw, dest, quality)
            except Exception as exc:  # noqa: BLE001
                for path in outputs(dest):
                    path.unlink(missing_ok=True)
                with lock:
                    stats["render_error"] += 1
                    used_slugs.discard(name)
                print(f"  ! {m.key} render {chosen.title}: {exc}"[:150], flush=True)
                continue  # try the next-best frame rather than giving up on the model

            entry = {
                "image": f"store/img/bikes2/{name}.webp",
                "thumb": f"store/img/bikes2/{name}.thumb.webp",
                "title": chosen.title,
                "author": strip_html((chosen.meta.get("Artist") or {}).get("value", "")) or "Unknown",
                "license": strip_html((chosen.meta.get("LicenseShortName") or {}).get("value", "")),
                "source": "https://commons.wikimedia.org/wiki/"
                + quote(chosen.page_title.replace(" ", "_"), safe=":/_(),.!'-"),
                "via": chosen.via,
                "view": shot.view if shot else None,
                "score": round(score, 1),
            }
            if hero:
                entry["hero"] = f"store/img/bikes2/{name}.hero.webp"
            with lock:
                entries[m.key] = entry
                stats["hit"] += 1
                stats[f"hit:{chosen.via}"] += 1
                stats[f"tier{m.tier}:hit"] += 1
                bytes_used += written
            print(
                f"  + {m.key} <- {chosen.title} [{entry['license']}] "
                f"{chosen.via}/{entry['view']} {score:.1f}",
                flush=True,
            )
            return True

        with lock:
            stats["render_gave_up"] += 1
        return False

    def work(client: httpx.Client, m: Model) -> None:
        try:
            fetch(client, m)
        except Exception as exc:  # noqa: BLE001
            with lock:
                stats["error"] += 1
            print(f"  ! {m.key}: {exc!r}"[:150], flush=True)
        with lock:
            stats["done"] += 1
            stats[f"tier{m.tier}:done"] += 1
            due = stats["done"] % args.checkpoint == 0
        if due:
            write_outputs(entries)
            _, titles = first_pass()  # the other agent is still claiming files
            with lock:
                used.update(titles)
                snapshot = (stats["done"], stats["hit"], stats["attempted"], spend["usd"])
            print(
                f"  .. {snapshot[0]}/{len(models)} tried, {len(entries)} images, "
                f"{bytes_used / 1e6:.1f} MB, hit {100 * snapshot[1] / max(1, snapshot[2]):.0f}%, "
                f"${snapshot[3]:.2f}",
                flush=True,
            )

    tiers: dict = defaultdict(int)
    for m in models:
        tiers[m.tier] += 1
    print(
        f"{len(all_models)} model families, {len(filled)} filled by images.py, "
        f"{len(entries)} filled here; {len(models)} to try "
        f"(manualId {tiers[0]}, manualUrl {tiers[1]}, rest {tiers[2]}); "
        f"budget {args.budget_mb} MB / ${args.llm_budget} LLM"
        + (f" / {args.minutes:.0f} min" if args.minutes else ""),
        flush=True,
    )

    with httpx.Client(
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
        timeout=httpx.Timeout(40.0, connect=15.0),
        follow_redirects=True,
    ) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(lambda m: work(client, m), models))

    write_outputs(entries)
    by = lambda prefix: {  # noqa: E731
        k.split(":", 1)[1]: v for k, v in sorted(stats.items()) if k.startswith(prefix)
    }
    pass_rate = {}
    for src in ("wikipedia", "category", "search"):
        seen = stats.get(f"scored:{src}", 0)
        if seen:
            pass_rate[src] = f"{stats.get(f'passed:{src}', 0)}/{seen}"
    print(
        json.dumps(
            {
                "tried": stats["done"],
                "new_images": stats["hit"],
                "total_entries": len(entries),
                "alias_entries": sum(1 for e in entries.values() if e.get("via") == "alias"),
                "no_candidate": stats["no_candidate"],
                "rejected_by_rater": stats["rejected"],
                "errors": stats["error"] + stats["rate_error"] + stats["render_error"],
                "mb": round(bytes_used / 1e6, 2),
                "llm_usd": round(spend["usd"], 3),
                "candidates_rated": stats["rated"],
                "pass_rate_by_source": pass_rate,
                "hits_by_source": by("hit:"),
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

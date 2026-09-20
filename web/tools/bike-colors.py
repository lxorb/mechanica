#!/usr/bin/env python3
"""Dominant paint colour per bike photo -> web/store/bike-colors.json. Owner: vehicle-models agent.

    api/.venv/Scripts/python web/tools/bike-colors.py            # every photo present now
    api/.venv/Scripts/python web/tools/bike-colors.py --force    # recompute, ignore the cache
    api/.venv/Scripts/python web/tools/bike-colors.py --report   # what was found, per make

Re-runnable: another agent is still appending to web/store/bike-images.json, so this keeps what it
already measured and only looks at photos whose key is new or whose file changed (size + mtime).

The problem it solves: the 3D viewer shows one generic model per bike TYPE, so a KTM 390 Duke and
a Kawasaki Z900 would be the same grey naked bike. Tinting the paint groups to the colour of the
bike in our own photo of it is what makes the generic read as that bike.

How the colour is found. A photo of a motorcycle is mostly NOT the bike: sky, tarmac, grass, a
showroom wall, and within the bike itself two big achromatic masses (tyres, engine) that would win
any naive "most common colour" vote. So:

  1. crop the outer ring away, downscale to 280px on the long edge, quantise to 28 colours
  2. drop every cluster that is background or hardware:
       - near-white  (V > 0.90, S < 0.20)      sky, showroom wall, number plate
       - near-black  (V < 0.18)                tyres, shadow, engine cases
       - grey        (chroma < 0.14)           tarmac, aluminium, chrome
       - earth band  (hue 8-58, chroma < 0.42) dirt, brick, wood, tarmac, skin
       - sky band    (hue 185-240, V > 0.80, S < 0.75)
  3. score what is left by  share x chroma^1.5 x a mid-value preference
  4. weight the middle of the frame 3x — the bike is what the photographer framed

And then the part that matters more than any of the above: BELIEVE IT ONLY WHEN IT IS OBVIOUS.
Measured over the 1.1k photos we have, this picks the right colour when the bike wears one big
vivid panel (a red Panigale, a blue GSX-R) and picks the tarmac when it does not. A wrong colour
is worse than a generic one — an orange KTM rendered red reads as the wrong bike — so a cluster
only wins if it is genuinely vivid (chroma >= MIN_CHROMA) and genuinely big (share >= MIN_SHARE).
Everything else takes the make's brand colour, which is right far more often than a coin flip:
KTM orange, Kawasaki lime, Yamaha blue, Harley black.

Output: web/store/bike-colors.json
  {"brands": {"ktm": "#ff6600", ...},
   "bikes":  {"ktm|390-duke": {"hex": "#ff6600", "name": "orange", "src": "brand"}}}
Consumed by web/counter/js/vehicle-type.js -> tintFor(bike); the brand map there is the fallback
when this file is missing entirely, and it stays in sync with BRANDS below.
"""

from __future__ import annotations

import argparse
import colorsys
import io
import json
import os
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
IMAGES = WEB / "store" / "bike-images.json"
OUT = WEB / "store" / "bike-colors.json"

# Brand colours: the racing/livery colour a rider would name, not the logo colour. Mirrors
# BRAND_COLORS in web/counter/js/vehicle-type.js — change both together.
BRANDS = {
    "ktm": "#ff6600",
    "kawasaki": "#4caf19",
    "ducati": "#cc1122",
    "yamaha": "#1b4fa8",
    "bmw": "#e8eaec",
    "honda": "#e01020",
    "suzuki": "#1657b8",
    "triumph": "#1c1c20",
    "harley-davidson": "#141416",
    "royal-enfield": "#4d5237",
    "aprilia": "#1a1a1e",
    "husqvarna": "#2b3138",
    "gasgas": "#d81f26",
    "moto-guzzi": "#8a1c22",
    "indian": "#8b1a1a",
    "mv-agusta": "#b81420",
    "vespa": "#c9d4c5",
    "piaggio": "#c9d4c5",
    "benelli": "#1f6f4a",
    "can-am": "#f0c000",
    "zero": "#2b2f33",
    "victory": "#1a1a1c",
    "sherco": "#1d69b4",
    "beta": "#c2172a",
    "hero": "#d3202a",
    "bajaj": "#1a4fa0",
    "tvs": "#1a56a8",
    "kymco": "#0b5ea8",
    "cfmoto": "#2a2e33",
    "kove": "#2f3237",
    "qj-motor": "#25282c",
    "voge": "#2a2d31",
    "niu": "#2b2f33",
    "cake": "#1f2226",
    "vmoto": "#2c3035",
    "chevrolet": "#c8102e",
}

# Colour names, by hue band. Only ever a caption — the hex is what tints the model.
HUES = [
    (12, "red"), (26, "orange"), (45, "gold"), (66, "yellow"), (150, "green"),
    (195, "teal"), (250, "blue"), (285, "purple"), (330, "pink"), (361, "red"),
]

QUANT_COLORS = 28
LONG_EDGE = 280

# The confidence gate. Tuned on the bikes we can check by eye (Panigale red, GSX-R blue, CBR red
# pass; 390 Duke, Z900, MT-09, R 1250 GS, Street Bob fall through to their brand colour, which is
# the right answer for all five). Raise these and more bikes go brand; lower them and tarmac wins.
MIN_CHROMA = 0.55
MIN_SHARE = 0.06


def name_of(r: int, g: int, b: int) -> str:
    """A word for the hex, for captions and for eyeballing the output file."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v < 0.14:
        return "black"
    if s < 0.12:
        return "white" if v > 0.82 else "silver" if v > 0.45 else "grey"
    hue = h * 360
    base = next(word for limit, word in HUES if hue < limit)
    if v < 0.32:
        return f"dark {base}"
    if s < 0.35:
        return f"muted {base}"
    return base


def chroma_of(r: int, g: int, b: int) -> float:
    """0..1. Chroma, not HSV saturation: a dark navy fairing has low V but real chroma."""
    return (max(r, g, b) - min(r, g, b)) / 255


def is_background(r: int, g: int, b: int) -> bool:
    """Sky, wall, tarmac, tyre, shadow — everything that is not paint."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    chroma = chroma_of(r, g, b)
    if v > 0.90 and s < 0.20:
        return True          # blown sky, white wall, number plate
    if v < 0.18:
        return True          # tyre, shadow, engine case
    if chroma < 0.14:
        return True          # tarmac, aluminium, chrome, grey studio sweep
    hue = h * 360
    if 8 <= hue <= 58 and chroma < 0.42:
        return True          # dirt, brick, wood, warm concrete, skin — real paint here is vivid
    if 58 < hue <= 170 and chroma < 0.22:
        return True          # grass and foliage
    if 185 <= hue <= 240 and v > 0.80 and s < 0.75:
        return True          # open sky, which is bright, cyan-blue and never fully saturated
    return False


def score(share: float, r: int, g: int, b: int) -> float:
    """Share of the frame, biased hard towards vivid mid-value paint."""
    _, _, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    mid = 1.0 - abs(v - 0.55) * 0.8
    return share * (chroma_of(r, g, b) ** 1.5) * max(mid, 0.3)


def clusters(image: Image.Image) -> list[tuple[float, tuple[int, int, int]]]:
    """(share, rgb) per quantised cluster, with the middle of the frame counted three times."""
    image = image.convert("RGB")
    image.thumbnail((LONG_EDGE, LONG_EDGE), Image.LANCZOS)
    quant = image.quantize(colors=QUANT_COLORS, method=Image.MEDIANCUT, dither=Image.NONE)
    palette = quant.getpalette()
    w, h = quant.size
    pixels = quant.load()
    # the outer ring is background in nearly every catalogue photo, so it does not vote at all;
    # the middle — where the bike is — votes three times
    x0, x1 = int(w * 0.10), int(w * 0.90)
    y0, y1 = int(h * 0.08), int(h * 0.92)
    cx0, cx1 = int(w * 0.25), int(w * 0.75)
    cy0, cy1 = int(h * 0.20), int(h * 0.85)
    weights: dict[int, float] = {}
    total = 0.0
    for y in range(y0, y1):
        inner_y = cy0 <= y < cy1
        for x in range(x0, x1):
            index = pixels[x, y]
            weight = 3.0 if inner_y and cx0 <= x < cx1 else 1.0
            weights[index] = weights.get(index, 0.0) + weight
            total += weight
    out = []
    for index, weight in weights.items():
        r, g, b = palette[index * 3: index * 3 + 3]
        out.append((weight / max(total, 1.0), (r, g, b)))
    out.sort(key=lambda row: -row[0])
    return out


def paint_of(path: Path) -> tuple[str, str, float] | None:
    """(hex, name, share) of the bike's paint — only when it is unambiguous, else None."""
    try:
        with Image.open(path) as image:
            image.load()
            groups = clusters(image)
    except Exception as error:                       # a truncated download is not a crash
        print(f"  ! {path.name}: {error}", file=sys.stderr)
        return None
    best = None
    best_score = 0.0
    for share, rgb in groups:
        if is_background(*rgb):
            continue
        value = score(share, *rgb)
        if value > best_score:
            best_score = value
            best = (share, rgb)
    if not best:
        return None
    share, (r, g, b) = best
    # the confidence gate — see the module docstring. Not vivid and not big means "I don't know".
    if chroma_of(r, g, b) < MIN_CHROMA or share < MIN_SHARE:
        return None
    return f"#{r:02x}{g:02x}{b:02x}", name_of(r, g, b), round(share, 3)


def make_of(key: str) -> str:
    return key.split("|", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="recompute every photo")
    parser.add_argument("--report", action="store_true", help="print what was found, per make")
    args = parser.parse_args()

    if not IMAGES.exists():
        print(f"{IMAGES} not there yet — writing the brand fallbacks only")
        entries = {}
    else:
        entries = json.loads(IMAGES.read_text(encoding="utf-8"))

    previous = {}
    if OUT.exists() and not args.force:
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8")).get("bikes", {})
        except Exception:
            previous = {}

    bikes: dict[str, dict] = {}
    measured = brand_only = reused = missing = 0
    for key, row in sorted(entries.items()):
        rel = row.get("image") or row.get("thumb")
        if not rel:
            continue
        path = WEB / rel
        if not path.exists():
            missing += 1
            continue
        stamp = f"{path.stat().st_size}:{int(path.stat().st_mtime)}"
        old = previous.get(key)
        if old and old.get("stamp") == stamp:
            bikes[key] = old
            reused += 1
            continue
        found = paint_of(path)
        if found:
            hexcode, name, share = found
            bikes[key] = {"hex": hexcode, "name": name, "share": share, "src": "photo", "stamp": stamp}
            measured += 1
        else:
            brand = BRANDS.get(make_of(key))
            if brand:
                bikes[key] = {"hex": brand, "name": name_of(*bytes.fromhex(brand[1:])), "src": "brand", "stamp": stamp}
                brand_only += 1

    payload = {
        "_": "Generated by web/tools/bike-colors.py — do not hand-edit. Paint colour per bike, "
             "measured from web/store/bike-images.json photos; `brands` is the per-make fallback.",
        "brands": BRANDS,
        "bikes": bikes,
    }
    OUT.write_text(json.dumps(payload, indent=0, sort_keys=False), encoding="utf-8")
    size = OUT.stat().st_size / 1024
    print(
        f"{len(entries)} photo entries · {measured} measured · {reused} unchanged · "
        f"{brand_only} fell back to the brand colour · {missing} file missing"
    )
    print(f"{len(bikes)} colours -> {OUT} ({size:.0f} KB)")

    if args.report:
        by_name: dict[str, int] = {}
        by_make: dict[str, list[str]] = {}
        for key, row in bikes.items():
            by_name[row["name"]] = by_name.get(row["name"], 0) + 1
            by_make.setdefault(make_of(key), []).append(f'{key.split("|")[1]} {row["hex"]} {row["name"]}')
        print("\ncolours found:")
        for name, n in sorted(by_name.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>4} {name}")
        print("\nsample per make:")
        for make in sorted(by_make)[:22]:
            print(f"  {make:<18} {' · '.join(by_make[make][:3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

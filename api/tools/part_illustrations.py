"""One rendered illustration per part type, for the part rows and the part sheet.

Writes, and owns, only these paths:
  web/store/icons-parts-3d/<id>.png    1024 px, RGBA, transparent background
  web/store/icons-parts-3d/<id>.webp   512 px, RGBA, q82 - what the UI actually loads
  web/store/icons-parts-3d/index.json  {id: {webp, png, prompt}}
  web/store/icons-parts-3d/CREDITS.md

The ids are the ones web/counter/js/particons.js already resolves part names to, so a screen swaps
<id>.svg for <id>.webp and nothing else changes, plus the types a scan of every manual's parts turned
up that the SVG set has no icon for (grease, thread lock, chain lube, cleaner spray, fuel additive,
gear oil, button cell).

One style prompt, one camera, one scale for all of them - a set only reads as a set if nothing moves
between frames but the object:

    api/.venv/Scripts/python api/tools/part_illustrations.py --quality medium
    api/.venv/Scripts/python api/tools/part_illustrations.py --only spark-plug,chain --force

Already-rendered ids are skipped unless --force, so a run that dies half way costs nothing to resume.
--budget is a hard stop in USD, checked before every call.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from app import llm  # noqa: E402
from app.config import settings  # noqa: E402

PARTICONS = ROOT / "web" / "counter" / "js" / "particons.js"
OUT_DIR = ROOT / "web" / "store" / "icons-parts-3d"
INDEX = OUT_DIR / "index.json"
CREDITS = OUT_DIR / "CREDITS.md"

WEBP_PX = 512
WEBP_QUALITY = 82
SIZE = "1024x1024"
WORKERS = 4

# gpt-image-1 output tokens per 1024x1024 image, billed at the model's output rate
IMAGE_TOKENS = {"low": 272, "medium": 1056, "high": 4160}
IMAGE_USD_PER_MTOK = {"gpt-image-1": 40.0, "gpt-image-1-mini": 8.0, "gpt-image-2": 30.0}

STYLE = (
    "isometric product render of a single motorcycle {subject}, studio lighting, semi-realistic, "
    "clean, orange #e85d04 accent on ink/steel materials, no text, no background clutter"
)
# Same camera, same framing, same light for every id in the set - this half never changes.
CAMERA = (
    ". Three-quarter isometric view from the front left at a 30 degree elevation, the object centred "
    "and filling about 80 percent of a square frame, consistent scale with other parts of the same "
    "kind, one soft key light from the upper left and a gentle fill, soft contact shadow, fully "
    "transparent background, no ground plane, no props, no packaging, no lettering, no logos, "
    "no watermarks"
)

# What each id actually is. The icon ids come from particons.js; the subject line is what makes the
# render a part a rider recognises rather than a generic blob.
SUBJECTS: dict[str, str] = {
    "engine-oil": "one litre bottle of engine oil, plain unlabelled bottle with an orange cap",
    "oil-filter": "spin-on cartridge oil filter, steel can with a threaded base",
    "air-filter": "pleated panel air filter element with an orange rubber frame",
    "spark-plug": "spark plug, ceramic insulator, steel hex body and threaded tip",
    "brake-pads": "pair of sintered brake pads, friction material on steel backing plates",
    "brake-disc": "front brake disc, drilled floating rotor with an orange carrier, tilted away from "
    "the camera in the same three-quarter view as the rest of the set, never face-on",
    "brake-fluid": "small DOT 4 brake fluid bottle, plain unlabelled with an orange cap",
    "brake-caliper": "radial four-piston brake caliper, machined body with an orange anodised accent",
    "brake-lever": "handlebar brake lever, forged aluminium with an orange adjuster wheel",
    "clutch-lever": "handlebar clutch lever, forged aluminium with an orange adjuster wheel",
    "clutch-cable": "clutch cable, black outer sheath in one loose loop with a steel barrel nipple at "
    "one end and a threaded adjuster at the other",
    "chain": "short section of 520 X-ring drive chain with steel rollers and an orange master link",
    "sprocket": "rear sprocket, toothed aluminium ring with an orange anodised inner carrier",
    "tire": "motorcycle tyre, deep tread block pattern, seen as a single standing tyre",
    "wheel": "cast alloy motorcycle wheel with an orange rim stripe, no tyre fitted",
    "front-fork": "single upside-down telescopic fork leg, gold stanchion and an orange preload adjuster",
    "rear-shock": "rear monoshock absorber, orange coil spring over a steel damper body",
    "swingarm": "aluminium single-sided swingarm casting",
    "battery": "sealed AGM motorcycle battery, black case with an orange positive terminal cover",
    "fuse": "automotive blade fuse, orange translucent body with steel blades",
    "bulb-headlight": "H4 halogen headlight bulb, clear glass envelope on a metal base",
    "taillight": "motorcycle tail light unit, red lens in a black housing",
    "coolant": "one litre bottle of engine coolant, translucent bottle showing bright green coolant "
    "inside, orange cap",
    "radiator": "motorcycle radiator core, aluminium fins and side tanks with an orange cap",
    "fuel-tank": "motorcycle fuel tank, smooth painted shell with a metal filler cap",
    "fuel-filter": "inline fuel filter cartridge, translucent body with two hose spigots",
    "exhaust": "slip-on exhaust silencer, brushed steel canister with a carbon end cap",
    "mirror": "motorcycle rear-view mirror on a threaded stem",
    "handlebar": "tapered aluminium handlebar with an orange anodised centre clamp area",
    "seat": "single motorcycle rider seat, stitched black cover on a moulded base",
    "footpeg": "rider footpeg, a short knurled steel foot platform hinged on a mounting bracket that "
    "bolts to the frame, seen from the side",
    "throttle-cable": "throttle cable, black outer sheath coiled once with a twist-grip end fitting",
    "bearing": "sealed ball bearing, steel races with an orange rubber seal",
    "bolt-torque": "hex flange bolt beside a torque wrench head, steel with an orange handle grip",
    "tool-kit": "compact motorcycle on-board tool kit, a few spanners and a screwdriver laid flat",
    "generic-part": "small machined steel motorcycle spare part on a hex mounting flange",
    # types the manuals name constantly that the SVG set has no icon for
    "grease": "tub of white lithium grease with the lid off and an orange label band",
    "threadlock": "small bottle of thread-locking compound, plain bottle with an orange cap",
    "chain-lube": "aerosol can of chain lube with a thin application straw, orange accent band",
    "cleaner-spray": "aerosol cleaning spray can with a trigger nozzle, orange accent band",
    "fuel-additive": "small bottle of fuel additive with a long pouring neck and an orange cap",
    "gear-oil": "squat silver bottle of final drive gear oil with a long narrow pouring spout folded "
    "over the shoulder and an orange cap",
    "button-cell": "CR2032 button cell battery, polished steel coin cell",
}


def icon_ids() -> list[str]:
    """The PART_ICONS array in particons.js, in its own order, then the new types."""
    source = PARTICONS.read_text(encoding="utf-8")
    block = re.search(r"export const PART_ICONS = \[(.*?)\]", source, re.S)
    known = re.findall(r'"([a-z0-9-]+)"', block.group(1)) if block else []
    extra = [i for i in SUBJECTS if i not in known]
    missing = [i for i in known if i not in SUBJECTS]
    if missing:
        raise SystemExit(f"particons.js has ids with no subject line: {missing}")
    return known + extra


def prompt_for(icon_id: str) -> str:
    return STYLE.format(subject=SUBJECTS[icon_id]) + CAMERA


def cost_of(model: str, quality: str, usage) -> float:
    tokens = int(getattr(usage, "output_tokens", 0) or 0) or IMAGE_TOKENS.get(quality, 1056)
    return tokens * IMAGE_USD_PER_MTOK.get(model, 40.0) / 1_000_000


def render(icon_id: str, model: str, quality: str) -> tuple[bytes, float]:
    response = llm.client().images.generate(
        model=model,
        prompt=prompt_for(icon_id),
        size=SIZE,
        quality=quality,
        background="transparent",
        output_format="png",
        n=1,
    )
    usd = cost_of(model, quality, getattr(response, "usage", None))
    llm.log("illustrations", model, getattr(response, "usage", None), extra_usd=usd)
    return base64.b64decode(response.data[0].b64_json), usd


def write(icon_id: str, png: bytes) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{icon_id}.png").write_bytes(png)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    image.resize((WEBP_PX, WEBP_PX), Image.LANCZOS).save(
        OUT_DIR / f"{icon_id}.webp", "WEBP", quality=WEBP_QUALITY, method=6
    )


def manifest(ids: list[str], model: str, quality: str) -> None:
    index = {}
    for icon_id in ids:
        if (OUT_DIR / f"{icon_id}.webp").exists():
            index[icon_id] = {
                "webp": f"{icon_id}.webp",
                "png": f"{icon_id}.png",
                "prompt": prompt_for(icon_id),
            }
    INDEX.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    CREDITS.write_text(
        "# Part illustration credits\n\n"
        f"Every file in `store/icons-parts-3d/` was generated with OpenAI {model} "
        f"({SIZE}, quality {quality}, transparent background) by `api/tools/part_illustrations.py` "
        f"on {time.strftime('%Y-%m-%d')}. One style prompt and one camera for the whole set; the exact "
        "prompt per file is in `index.json`. Images generated with the OpenAI API belong to the "
        "customer who generated them, so these are ours to ship - no third-party attribution is owed. "
        "No trademark, logo or lettering was requested in any prompt.\n",
        encoding="utf-8",
    )


def sheet(ids: list[str], columns: int = 7, cell: int = 192) -> Path:
    """One contact sheet of the whole set on paper white - the only way to see whether the camera,
    the scale and the orange actually hold still from frame to frame."""
    have = [i for i in ids if (OUT_DIR / f"{i}.webp").exists()]
    rows = (len(have) + columns - 1) // columns
    pad, label = 10, 16
    canvas = Image.new("RGB", (columns * (cell + pad) + pad, rows * (cell + pad + label) + pad), "#faf8f5")
    for n, icon_id in enumerate(have):
        tile = Image.open(OUT_DIR / f"{icon_id}.webp").convert("RGBA").resize((cell, cell), Image.LANCZOS)
        white = Image.new("RGBA", tile.size, (250, 248, 245, 255))
        white.alpha_composite(tile)
        x = pad + (n % columns) * (cell + pad)
        y = pad + (n // columns) * (cell + pad + label)
        canvas.paste(white.convert("RGB"), (x, y))
    path = OUT_DIR / "sheet.png"
    canvas.save(path)
    print(f"sheet: {path} ({len(have)} tiles)")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=settings.model_image)
    parser.add_argument("--quality", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--only", default="", help="comma separated ids")
    parser.add_argument("--force", action="store_true", help="re-render ids that already exist")
    parser.add_argument("--budget", type=float, default=8.0, help="hard stop, USD")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--sheet", action="store_true", help="only rebuild sheet.png and index.json")
    args = parser.parse_args()

    ids = icon_ids()
    if args.sheet:
        manifest(ids, args.model, args.quality)
        sheet(ids)
        return 0
    if args.only:
        wanted = [i.strip() for i in args.only.split(",") if i.strip()]
        unknown = [i for i in wanted if i not in SUBJECTS]
        if unknown:
            raise SystemExit(f"unknown ids: {unknown}")
        ids = wanted
    todo = [i for i in ids if args.force or not (OUT_DIR / f"{i}.webp").exists()]
    per_image = IMAGE_TOKENS[args.quality] * IMAGE_USD_PER_MTOK.get(args.model, 40.0) / 1_000_000
    print(f"{len(todo)} to render, {len(ids) - len(todo)} already there, "
          f"~${per_image:.3f} each, ~${per_image * len(todo):.2f} total, budget ${args.budget:.2f}")
    if per_image * len(todo) > args.budget:
        raise SystemExit("over budget: raise --budget or drop --quality")

    spent = 0.0
    failed: list[str] = []

    def one(icon_id: str) -> tuple[str, float, str]:
        try:
            png, usd = render(icon_id, args.model, args.quality)
            write(icon_id, png)
            return icon_id, usd, ""
        except Exception as exc:  # one bad id must not cost the other forty
            return icon_id, 0.0, repr(exc)[:160]

    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for icon_id, usd, error in pool.map(one, todo):
            spent += usd
            if error:
                failed.append(icon_id)
            print(f"  {'FAIL' if error else 'ok  '} {icon_id:<16} ${spent:.2f} {error}")
            if spent > args.budget:
                print("budget reached, stopping")
                break

    every = icon_ids()
    manifest(every, args.model, args.quality)
    sheet(every)
    print(f"{len(todo) - len(failed)} rendered in {time.time() - started:.0f}s, ${spent:.2f} spent")
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

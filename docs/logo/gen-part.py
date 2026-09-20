"""Generate single-part icon candidates (gpt-image-1, transparent, 1024) into docs/logo/part-*.png.

    api/.venv/Scripts/python docs/logo/gen-part.py            # all
    api/.venv/Scripts/python docs/logo/gen-part.py piston     # one
"""
import base64
import concurrent.futures as cf
import pathlib
import sys

from openai import OpenAI

HERE = pathlib.Path(__file__).resolve().parent
KEY = pathlib.Path(r"C:\Users\me\agent-secrets\openai-mechanica.txt").read_text().strip()

STYLE = (
    "Flat geometric vector app icon, minimal and bold, designed to stay legible at 16 pixels. "
    "Only three colours: a single warm orange accent (#e85d04), near-black ink (#141414) and white. "
    "No gradients, no shading, no bevel, no glow, no photorealism, no 3D, no text, no letters, no numbers, "
    "no words anywhere in the image. Thick even strokes, large simple shapes, at most four distinct shapes, "
    "every stroke at least one tenth of the icon width, generous negative space, perfectly centred, small margin, "
    "transparent background. Crisp hard edges like an SVG. Automotive service-manual feel. "
    "The whole image is exactly one motorcycle part and nothing else: "
)
PARTS = {
    "piston": "a piston with its connecting rod seen straight from the side: a solid ink piston crown with two thick "
              "orange piston-ring bars across it, the ink rod tapering down to a round big end with a white hole.",
    "sparkplug": "a spark plug standing upright: a solid ink hexagon body, a white ceramic insulator above it wearing "
                 "one thick orange band, a small ink terminal nut on top and a short ink ground-electrode hook below.",
    "sprocket": "a rear drive sprocket seen straight on: a bold ink toothed ring with eight blunt square teeth, "
                "a solid orange hub in the middle with four round white lightening holes.",
    "brakedisc": "a brake disc seen straight on: a bold ink outer ring with eight round white holes, a solid orange hub, "
                 "and one thick ink brake pad clamping the top of the ring.",
}


def gen(name: str) -> str:
    client = OpenAI(api_key=KEY)
    res = client.images.generate(model="gpt-image-1", prompt=STYLE + PARTS[name], size="1024x1024",
                                 quality="high", background="transparent", n=1)
    out = HERE / f"part-{name}.png"
    out.write_bytes(base64.b64decode(res.data[0].b64_json))
    return f"{out.name} {out.stat().st_size} B"


names = sys.argv[1:] or list(PARTS)
with cf.ThreadPoolExecutor(4) as ex:
    for line in ex.map(gen, names):
        print(line)
with (HERE / "PROMPTS.md").open("a", encoding="utf-8") as f:
    for n in names:
        f.write(f"\n## part-{n}.png\n\n{STYLE}{PARTS[n]}\n")

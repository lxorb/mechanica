"""Generate Mechanica logo candidates with the OpenAI Images API."""
import base64
import json
import os
import pathlib
import sys

from openai import OpenAI

HERE = pathlib.Path(__file__).resolve().parent
MODEL = os.environ.get("IMG_MODEL", "gpt-image-1")

BASE = (
    "Flat geometric vector logo mark, app icon, minimal and bold, designed to stay legible "
    "at 16 pixels. Only three colours: a single warm orange accent (#e85d04), near-black ink "
    "(#141414) and white. No gradients, no shading, no bevel, no glow, no photorealism, no 3D, "
    "no text, no letters, no numbers, no words anywhere in the image. Thick even strokes, large "
    "simple shapes, generous negative space, perfectly centred, small margin, transparent "
    "background. Crisp hard edges like an SVG. Automotive service-manual feel."
)

IDEAS = {
    1: (
        "A single mark: the corner of a manual page (a square sheet with one corner folded over) "
        "with two short horizontal ink rules of body text on it, one of which is covered by a thick "
        "flat orange highlighter bar; below the page sits a simple geometric motorcycle wheel, a bold "
        "ink ring with five straight spokes, overlapping the bottom of the page."
    ),
    2: (
        "A single mark: a torque wrench bent into an arc that forms the letter M shape purely from "
        "tool geometry - two symmetric angled wrench arms meeting at a centre peak, the open jaw ends "
        "as flat hexagon sockets in ink, and the sweeping torque arc above drawn as a thick orange "
        "curved band with a small orange arrowhead."
    ),
    3: (
        "A single mark: a rounded square sheet of paper in ink outline with two short orange rules at "
        "the top like highlighted text, and inside it the silhouette of a motorcycle reduced to pure "
        "geometry - two bold ink circles for wheels joined by a straight angled frame bar and a short "
        "handlebar stub."
    ),
    4: (
        "A single mark: a hexagonal bolt head seen straight on, thick ink hexagon ring with a smaller "
        "hexagon socket inside; the top-right sixth of the hexagon peels away as a folded page corner "
        "in orange, revealing a flat orange triangle, and one short orange rule sits inside the socket."
    ),
    5: (
        "A single mark: the letter shape of an M constructed entirely from interlocking drive-chain "
        "links - four thick ink chain link plates with round pin holes, arranged as two rising strokes "
        "and two falling strokes forming an M silhouette, with the single centre link filled solid orange."
    ),
    6: (
        "A single mark: a spark plug drawn as a flat geometric object - a bold ink hexagon nut body, a "
        "straight ceramic insulator column above it, a small ink electrode hook below - where the "
        "insulator column doubles as a chisel-tip highlighter, its angled tip solid orange, laying down "
        "a short thick orange highlight bar across the bottom."
    ),
}


def gen(client, key, prompt, out):
    kwargs = dict(model=MODEL, prompt=prompt, size="1024x1024", n=1)
    if MODEL.startswith("gpt-image"):
        kwargs.update(quality="high", background="transparent", output_format="png")
    r = client.images.generate(**kwargs)
    data = r.data[0]
    raw = base64.b64decode(data.b64_json) if data.b64_json else None
    if raw is None:
        import urllib.request
        raw = urllib.request.urlopen(data.url).read()
    out.write_bytes(raw)
    usage = getattr(r, "usage", None)
    print(f"{key} -> {out.name} {len(raw)} bytes usage={usage}")
    return usage


def main():
    key_file = pathlib.Path(r"C:\Users\me\agent-secrets\openai-mechanica.txt")
    os.environ["OPENAI_API_KEY"] = key_file.read_text(encoding="utf-8").strip()
    client = OpenAI()

    which = sys.argv[1:] or [str(i) for i in IDEAS]
    specs = json.loads(pathlib.Path(HERE / "extra.json").read_text()) if (HERE / "extra.json").exists() else {}

    log = []
    for w in which:
        if w in specs:
            prompt = BASE + " " + specs[w]
            name = f"candidate-{w}.png"
        else:
            prompt = BASE + " " + IDEAS[int(w)]
            name = f"candidate-{w}.png"
        u = gen(client, w, prompt, HERE / name)
        log.append({"key": w, "file": name, "prompt": prompt,
                    "usage": u.model_dump() if u else None})
    (HERE / f"log-{'-'.join(which)}.json").write_text(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()

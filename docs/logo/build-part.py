"""Build the Mechanica icon set from the generated piston (docs/logo/part-piston.png).

The render is kept as the design reference; the shipped icons come from it after cleaning:
alpha is hard-thresholded (the generator leaves a soft halo), every opaque pixel snaps to the
exact brand colours (--ink / --orange / white), then the mark is cropped, centred and scaled.
    api/.venv/Scripts/python docs/logo/build-part.py
"""
import pathlib

import numpy as np
from PIL import Image, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
ICONS = HERE.parent.parent / "web" / "counter" / "icons"
SRC = HERE / "part-piston.png"

INK = (20, 20, 20)
ORANGE = (232, 93, 4)
WHITE = (255, 255, 255)
PAPER = (236, 231, 220)


def clean(src: Image.Image) -> Image.Image:
    im = np.asarray(src.convert("RGBA")).astype(np.int32)
    rgb, a = im[..., :3], im[..., 3]
    solid = a >= 140
    out = np.zeros_like(im)
    pal = np.array([INK, ORANGE, WHITE], dtype=np.int32)
    d = ((rgb[..., None, :] - pal[None, None, :, :]) ** 2).sum(-1)      # h, w, 3
    idx = d.argmin(-1)
    out[..., :3] = pal[idx]
    out[..., 3] = np.where(solid, 255, 0)
    img = Image.fromarray(out.astype(np.uint8), "RGBA")
    # one pass of a tiny blur on the alpha only, so the hard threshold does not alias at 1024
    alpha = img.getchannel("A").filter(ImageFilter.GaussianBlur(0.8))
    img.putalpha(alpha)
    return img


def crop_square(img: Image.Image, margin: float = 0.06) -> Image.Image:
    box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    part = img.crop(box)
    w, h = part.size
    side = int(max(w, h) * (1 + 2 * margin))
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(part, ((side - w) // 2, (side - h) // 2), part)
    return sq


def tile(mark: Image.Image, px: int, scale: float, bg) -> Image.Image:
    """Opaque square with the mark at `scale` of its side."""
    im = Image.new("RGBA", (px, px), bg + (255,))
    size = int(px * scale)
    m = mark.resize((size, size), Image.LANCZOS)
    im.paste(m, ((px - size) // 2, (px - size) // 2), m)
    return im


def transparent(mark: Image.Image, px: int, scale: float = 0.96) -> Image.Image:
    im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    size = int(px * scale)
    m = mark.resize((size, size), Image.LANCZOS)
    im.paste(m, ((px - size) // 2, (px - size) // 2), m)
    return im


mark = crop_square(clean(Image.open(SRC)))
mark.save(HERE / "part-piston-clean.png")
ICONS.mkdir(exist_ok=True)
tile(mark, 512, 0.78, PAPER).save(ICONS / "icon-512.png")
tile(mark, 512, 0.56, PAPER).save(ICONS / "icon-512-maskable.png")   # safe zone: central 80 %
tile(mark, 192, 0.78, PAPER).save(ICONS / "icon-192.png")
tile(mark, 180, 0.78, PAPER).save(ICONS / "apple-touch-icon-180.png")
transparent(mark, 32).save(ICONS / "favicon-32.png")
sizes = [16, 24, 32, 48, 64, 128, 256]
frames = [transparent(mark, s) for s in sizes]
# Pillow drops every size larger than the base frame, so the 256 px frame is the base
frames[-1].save(ICONS / "favicon.ico", format="ICO", sizes=[(s, s) for s in sizes],
                append_images=frames[:-1])
# previews for a human check: the 16 and 32 px favicons blown up next to the 192 tile
sheet = Image.new("RGBA", (192 + 16 + 128 + 16 + 128, 192), PAPER + (255,))
sheet.paste(tile(mark, 192, 0.78, PAPER), (0, 0))
sheet.paste(transparent(mark, 32).resize((128, 128), Image.NEAREST), (208, 32))
sheet.paste(transparent(mark, 16).resize((128, 128), Image.NEAREST), (352, 32))
sheet.save(HERE / "part-piston-sheet.png")
print("built", sorted(p.name for p in ICONS.glob("*") if not p.name.startswith(("corvette-", "mark-"))))

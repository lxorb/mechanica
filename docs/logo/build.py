"""Build the Mechanica icon set from the winning mark (candidate-1a) as clean geometry.

The generated PNG is the design reference; the shipped icons are redrawn here at exact
brand colours so they stay crisp and on-palette down to 16 px.
"""
import pathlib

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
ICONS = HERE.parent.parent / "web" / "counter" / "icons"

INK = (20, 20, 20, 255)          # --ink  #141414
PAPER = (236, 231, 220, 255)     # --paper #ece7dc
ORANGE = (232, 93, 4, 255)       # --orange #e85d04
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)

# --- geometry, in a 0..100 art space -------------------------------------
PX0, PY0, PX1, PY1 = 14.0, 12.0, 66.0, 78.0   # page
RAD = 5.0                                      # page corner radius
FOLD = 14.0                                    # dog-ear size
RX0 = 21.0                                     # rules left
RULES = [(52.0, 29.5, 35.0), (52.0, 40.0, 47.0), (44.0, 51.5, 57.0)]  # x1, y0, y1
CX, CY = 70.0, 66.0                            # wheel
R_OUT, R_GAP, R_HI, R_OR, R_HUB = 22.0, 25.4, 15.0, 10.8, 4.3

# sub-32 px cut: two fat rules instead of three, one size up on the wheel
RULES_S = [(51.0, 29.0, 37.0), (51.0, 43.0, 52.0)]
WHEEL_S = (70.0, 66.0, 23.0, 26.6, 15.8, 11.2, 4.7)


def _o(d, cx, cy, r, fill, s):
    d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], fill=fill)


def draw_mark(px, dark=False, simple=False):
    """Render the mark on a transparent square of px pixels, cropped and centred."""
    s = px / 100.0
    body = PAPER if dark else INK      # page + wheel tyre
    hi = INK if dark else WHITE        # rules + wheel ring + hub
    rules = RULES_S if simple else RULES
    cx, cy, r_out, r_gap, r_hi, r_or, r_hub = WHEEL_S if simple else (
        CX, CY, R_OUT, R_GAP, R_HI, R_OR, R_HUB)
    im = Image.new("RGBA", (px, px), CLEAR)
    d = ImageDraw.Draw(im)

    d.rounded_rectangle([PX0 * s, PY0 * s, PX1 * s, PY1 * s], radius=RAD * s, fill=body)
    # dog-ear: cut the corner away, then lay the folded flap in the contrast colour
    d.polygon([((PX1 - FOLD) * s, (PY0 - 1) * s), ((PX1 + 1) * s, (PY0 - 1) * s),
               ((PX1 + 1) * s, (PY0 + FOLD) * s)], fill=CLEAR)
    d.polygon([((PX1 - FOLD) * s, PY0 * s), ((PX1 - 0.6) * s, (PY0 + FOLD - 0.6) * s),
               ((PX1 - FOLD) * s, (PY0 + FOLD - 0.6) * s)], fill=hi)
    # the marked lines
    for i, (x1, y0, y1) in enumerate(rules):
        d.rounded_rectangle([RX0 * s, y0 * s, x1 * s, y1 * s],
                            radius=(y1 - y0) * s / 2.4,
                            fill=ORANGE if i == 1 else hi)
    # wheel, knocked out of the page so it keeps its own silhouette
    _o(d, cx, cy, r_gap, CLEAR, s)
    _o(d, cx, cy, r_out, body, s)
    _o(d, cx, cy, r_hi, hi, s)
    _o(d, cx, cy, r_or, ORANGE, s)
    _o(d, cx, cy, r_hub, hi, s)
    return im


def mark(px, dark=False, ss=8, simple=None):
    if simple is None:
        simple = px <= 34
    w = min(px * ss, 3200)
    im = draw_mark(w, dark, simple)
    im = im.crop(im.getbbox())
    side = max(im.size)
    sq = Image.new("RGBA", (side, side), CLEAR)
    sq.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return sq.resize((px, px), Image.LANCZOS)


def tile(px, cover=0.78, bg=PAPER, dark=False, radius=0.0, simple=None):
    """Mark centred on a solid tile."""
    im = Image.new("RGBA", (px, px), CLEAR)
    if radius:
        ImageDraw.Draw(im).rounded_rectangle([0, 0, px - 1, px - 1],
                                             radius=px * radius, fill=bg)
    else:
        im.paste(bg, (0, 0, px, px))
    m = max(8, int(px * cover))
    im.alpha_composite(mark(m, dark, simple=simple), ((px - m) // 2, (px - m) // 2))
    return im


def write_ico(path, sizes):
    """ICO with a purpose-drawn PNG per size (Pillow only rescales one source)."""
    import io
    import struct
    blobs = []
    for px in sizes:
        b = io.BytesIO()
        tile(px, 0.88 if px <= 34 else 0.82).convert("RGBA").save(b, format="PNG")
        blobs.append(b.getvalue())
    off = 6 + 16 * len(sizes)
    out = struct.pack("<HHH", 0, 1, len(sizes))
    for px, blob in zip(sizes, blobs):
        out += struct.pack("<BBBBHHII", px if px < 256 else 0, px if px < 256 else 0,
                           0, 0, 1, 32, len(blob), off)
        off += len(blob)
    path.write_bytes(out + b"".join(blobs))


def main():
    ICONS.mkdir(parents=True, exist_ok=True)

    mark(1024).save(HERE / "mechanica-mark.png")
    mark(1024, dark=True).save(HERE / "mechanica-mark-dark.png")

    out = {
        "favicon-32.png": tile(32, 0.88),
        "icon-192.png": tile(192, 0.80),
        "icon-512.png": tile(512, 0.80),
        "apple-touch-icon-180.png": tile(180, 0.76),
        "icon-512-maskable.png": tile(512, 0.58, bg=INK, dark=True),
    }
    for name, im in out.items():
        im.convert("RGB").save(ICONS / name)
        print(name, im.size)

    write_ico(ICONS / "favicon.ico", [16, 24, 32, 48, 64, 128, 256])
    print("favicon.ico")


if __name__ == "__main__":
    main()

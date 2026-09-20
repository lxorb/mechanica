"""Composite candidates onto paper + ink with 32/16 px previews for judging."""
import pathlib
import sys

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
PAPER = (236, 231, 220, 255)
INK = (20, 20, 20, 255)


def flat(p, bg):
    im = Image.open(p).convert("RGBA")
    c = Image.new("RGBA", im.size, bg)
    c.alpha_composite(im)
    return c.convert("RGB")


def zoom(p, bg, s, z=128):
    return flat(p, bg).resize((s, s), Image.LANCZOS).resize((z, z), Image.NEAREST)


def main():
    out, names = sys.argv[1], sys.argv[2:]
    cw, ch = 288, 570
    sheet = Image.new("RGB", (cw * len(names), ch), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, n in enumerate(names):
        p = HERE / n
        x = i * cw + 12
        sheet.paste(flat(p, PAPER).resize((256, 256), Image.LANCZOS), (x, 30))
        d.text((x, 10), n, fill=(0, 0, 0))
        sheet.paste(flat(p, INK).resize((128, 128), Image.LANCZOS), (x, 300))
        sheet.paste(zoom(p, PAPER, 32), (x + 136, 300))
        sheet.paste(zoom(p, PAPER, 16), (x, 436))
        sheet.paste(zoom(p, INK, 16), (x + 136, 436))
    sheet.save(HERE / out)
    print(HERE / out, sheet.size)


if __name__ == "__main__":
    main()

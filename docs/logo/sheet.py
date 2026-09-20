"""Contact sheet: every candidate, plus the shipped icons at 16/32/192 on ink and paper."""
import pathlib

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
ICONS = HERE.parent.parent / "web" / "counter" / "icons"
INK = (20, 20, 20)
PAPER = (236, 231, 220)
ORANGE = (232, 93, 4)
W = 1440

CANDS = ["candidate-1.png", "candidate-2.png", "candidate-3.png", "candidate-4.png",
         "candidate-5.png", "candidate-6.png", "candidate-1a.png", "candidate-1b.png",
         "candidate-4a.png", "candidate-4b.png"]
DROPPED = {"candidate-3.png", "candidate-5.png", "candidate-6.png", "candidate-1b.png",
           "candidate-2.png", "candidate-4a.png"}
WINNER = "candidate-1a.png"


def font(px, bold=False):
    for n in ("bahnschrift.ttf", "segoeuib.ttf" if bold else "segoeui.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(n, px)
        except OSError:
            continue
    return ImageFont.load_default()


F = font(17)
FB = font(21, True)
FS = font(14)


def flat(p, bg):
    im = Image.open(p).convert("RGBA")
    c = Image.new("RGBA", im.size, bg + (255,))
    c.alpha_composite(im)
    return c.convert("RGB")


def main():
    H = 1440
    s = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(s)

    d.rectangle([0, 0, W, 64], fill=INK)
    d.text((28, 18), "MECHANICA  ·  logo candidates and shipped icons", font=FB, fill=PAPER)
    d.text((W - 300, 22), "2026-09-20  ·  gpt-image-1", font=FS, fill=(150, 150, 150))

    # --- candidates, 5 per row
    y = 92
    d.text((28, y), "10 candidates  (6 ideas + 2 variants each of the best two)", font=FB, fill=INK)
    y += 34
    cw, cell = 276, 200
    for i, n in enumerate(CANDS):
        cx = 28 + (i % 5) * cw
        cy = y + (i // 5) * (cell + 78)
        s.paste(flat(HERE / n, PAPER).resize((cell, cell), Image.LANCZOS), (cx, cy))
        if n == WINNER:
            d.rectangle([cx - 5, cy - 5, cx + cell + 4, cy + cell + 4], outline=ORANGE, width=5)
        lab = n.replace("candidate-", "").replace(".png", "")
        note = "WINNER" if n == WINNER else ("dropped" if n in DROPPED else "shortlist")
        col = ORANGE if n == WINNER else ((150, 150, 150) if note == "dropped" else INK)
        d.text((cx, cy + cell + 8), lab, font=FB, fill=INK)
        d.text((cx + 34, cy + cell + 12), note, font=FS, fill=col)
        # 16 px check strip
        z = flat(HERE / n, PAPER).resize((16, 16), Image.LANCZOS).resize((34, 34), Image.NEAREST)
        s.paste(z, (cx + cell - 34, cy + cell + 8))

    # --- shipped icons
    y = 92 + 34 + 2 * (cell + 78) + 22
    d.line([28, y - 14, W - 28, y - 14], fill=(220, 216, 208), width=2)
    d.text((28, y), "Shipped icons  ·  web/counter/icons/", font=FB, fill=INK)
    y += 38

    rows = [("on paper #ece7dc", PAPER), ("on ink #141414", INK)]
    rh, mid = 250, 112
    for ri, (label, bg) in enumerate(rows):
        ry = y + ri * rh
        d.text((28, ry + mid - 10), label, font=F, fill=INK)
        bx = 200

        def put(im, px, pad, cap):
            nonlocal bx
            box = Image.new("RGB", (px + pad * 2, px + pad * 2), bg)
            box.paste(im, (pad, pad))
            s.paste(box, (bx, ry + mid - (px + pad * 2) // 2))
            d.text((bx, ry + mid + 120), cap, font=FS, fill=(110, 110, 110))
            bx += px + pad * 2 + 28

        for px in (16, 32):
            im = Image.open(ICONS / "favicon-32.png").convert("RGB").resize((px, px), Image.LANCZOS)
            put(im, px, 16, f"{px} px")
            put(im.resize((px * 4, px * 4), Image.NEAREST), px * 4, 6, f"{px} px @4x")
        put(Image.open(ICONS / "icon-192.png").convert("RGB"), 192, 14, "192 px")

        if ri == 1:
            bx += 10
            for name, lab2 in (("icon-512-maskable.png", "512 maskable"),
                               ("apple-touch-icon-180.png", "apple 180")):
                im = Image.open(ICONS / name).convert("RGB").resize((150, 150), Image.LANCZOS)
                s.paste(im, (bx, ry + mid - 75))
                d.text((bx, ry + mid + 120), lab2, font=FS, fill=(110, 110, 110))
                bx += 176

    wy = y + 2 * rh + 16
    d.line([28, wy - 12, W - 28, wy - 12], fill=(220, 216, 208), width=2)
    wm = Image.open(HERE / "mechanica-wordmark.png").convert("RGB")
    ww = 620
    wm = wm.resize((ww, int(wm.height * ww / wm.width)), Image.LANCZOS)
    s.paste(wm, (28, wy + 10))
    d.text((28 + ww + 34, wy + 40), "mechanica-wordmark.svg", font=FB, fill=INK)
    d.text((28 + ww + 34, wy + 70), "mark + Big Shoulders Display 800, inline it so the font applies",
           font=FS, fill=(110, 110, 110))

    s.save(HERE / "sheet.png")
    print(HERE / "sheet.png", s.size)


if __name__ == "__main__":
    main()

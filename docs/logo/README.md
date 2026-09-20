# Mechanica logo

**Winner: `candidate-1a` — a manual page with one line marked, and a wheel.**

- It is the product in one mark: the page, the orange marked line, the bike. Nothing to explain.
- Only survivor that still reads at 16 px: solid page silhouette, orange bar, orange hub — no hairlines.
- The wheel breaks the square, so it is not another rounded-square document icon in a tab strip.
- Dropped: 3, 5, 6, 1b (detail collapses at 16 px), 2 (a torque arc is not the product), 4/4a/4b (a bolt head is any tool app).
- Shipped icons are **redrawn in `build.py`** from this mark, not cropped from the render (murky alpha, off-brand greys): a 0–100 art space at exact `--ink` / `--paper` / `--orange`, simplified below 34 px (two fat rules, bigger wheel).
- `favicon.ico` is hand-written with a purpose-drawn PNG per size (16/24/32/48/64/128/256); Pillow would only rescale one source.
- Icon URLs carry `?v=2` to get past the service-worker precache of the old Corvette photo, which is kept as `icons/corvette-*`.
- Rebuild: `api/.venv/Scripts/python docs/logo/build.py`, then `sheet.py`. `gen.py` re-runs the candidates; prompts in `PROMPTS.md`.

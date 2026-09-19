"""Optional PART_MODEL=yolo path: AswinG5/moto-parts-30cls motopartscls.pt via ultralytics.

Not imported unless PART_MODEL=yolo. torch/ultralytics stay out of requirements.txt;
install them yourself (`pip install ultralytics`) if you want this path.
"""

import io
import os
from pathlib import Path

from ..config import settings
from ..models import PartClass
from .labels import LABELS

REPO = "AswinG5/moto-parts-30cls"
FILE = "motopartscls.pt"
URL = f"https://huggingface.co/{REPO}/resolve/main/{FILE}?download=true"

_model = None


def weights() -> Path:
    path = Path(os.getenv("PART_WEIGHTS") or settings.data_dir / "models" / FILE)
    if path.exists():
        return path
    import httpx

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with httpx.stream("GET", URL, follow_redirects=True, timeout=120.0) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(path)
    return path


def model():
    global _model
    if _model is None:
        from ultralytics import YOLO

        _model = YOLO(str(weights()))
    return _model


def _label(name: str) -> str:
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in LABELS else str(name)


def classify(image: bytes) -> list[PartClass]:
    from PIL import Image

    img = Image.open(io.BytesIO(image)).convert("RGB")
    m = model()
    result = m.predict(img, verbose=False)[0]
    probs = getattr(result, "probs", None)
    if probs is None:
        return []
    names = result.names
    top = list(zip(probs.top5, probs.top5conf.tolist()))[:3]
    return [PartClass(label=_label(names[int(i)]), confidence=round(float(c), 3)) for i, c in top]

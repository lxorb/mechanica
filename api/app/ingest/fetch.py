"""Get the official PDF onto disk."""

import shutil
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "application/pdf,application/octet-stream,*/*", "Accept-Language": "en-US,en;q=0.9"}


def fetch(source: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.lower().startswith(("http://", "https://")):
        tmp = dest.with_suffix(".part")
        with httpx.stream("GET", source, follow_redirects=True, timeout=180.0, headers=HEADERS) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        tmp.replace(dest)
    else:
        src = Path(source).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"no such file: {source}")
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
    with dest.open("rb") as f:
        if f.read(5)[:4] != b"%PDF":
            raise ValueError(f"not a PDF: {source}")
    return dest

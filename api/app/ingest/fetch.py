"""Get the official PDF onto disk. Nothing downstream ever sees a file that is not a PDF."""

import shutil
from pathlib import Path

import httpx

BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
UA = BROWSER
AGENTS = {"browser": BROWSER, "googlebot": GOOGLEBOT}
HEADERS = {"User-Agent": UA, "Accept": "application/pdf,application/octet-stream,*/*", "Accept-Language": "en-US,en;q=0.9"}
MAGIC = b"%PDF"


def agents_for(needs_ua: str | None) -> tuple[str, ...]:
    """RegistryEntry.needsUa names the agent a host insists on; the other one stays as the fallback."""
    first = AGENTS.get((needs_ua or "").strip().lower())
    return (first, BROWSER if first is GOOGLEBOT else GOOGLEBOT) if first else (BROWSER, GOOGLEBOT)


def fetch(source: str, dest: Path, needs_ua: str | None = None, on_bytes=None) -> Path:
    """on_bytes(received, expected) is called while the body streams so a waiting UI can show the download."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.lower().startswith(("http://", "https://")):
        last: Exception | None = None
        for agent in agents_for(needs_ua):
            tmp = dest.with_suffix(".part")
            try:
                with httpx.stream("GET", source, follow_redirects=True, timeout=180.0, headers={**HEADERS, "User-Agent": agent}) as r:
                    r.raise_for_status()
                    expected = int(r.headers.get("content-length") or 0)
                    got = 0
                    with tmp.open("wb") as f:
                        for chunk in r.iter_bytes(1 << 16):
                            f.write(chunk)
                            got += len(chunk)
                            if on_bytes:
                                on_bytes(got, expected)
                if tmp.open("rb").read(5)[:4] != MAGIC:
                    raise ValueError(f"not a PDF: {source}")
                tmp.replace(dest)
                last = None
                break
            except Exception as exc:
                last = exc
                tmp.unlink(missing_ok=True)
        if last is not None:
            raise last
    else:
        src = Path(source).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"no such file: {source}")
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
    with dest.open("rb") as f:
        if f.read(5)[:4] != MAGIC:
            raise ValueError(f"not a PDF: {source}")
    return dest

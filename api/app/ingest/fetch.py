"""Get the official PDF onto disk. Nothing downstream ever sees a file that is not a PDF."""

import ipaddress
import os
import shutil
import socket
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


class BlockedTarget(ValueError):
    """The URL resolves somewhere this process must never be talked into reaching."""


def _public(host: str) -> bool:
    """Every address `host` resolves to is a routable public one.

    The manual registry only ever names public web hosts, so anything else - 127.0.0.1, 10/8,
    169.254.169.254 (the cloud metadata service), a hostname that resolves into the container's own
    network - is somebody redirecting the fetcher at the inside of the deployment. DNS can of course
    answer differently on the connect that follows; this closes the easy door, not every door.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            return False
        if not ip.is_global or ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
            return False
    return True


def _guard(request: httpx.Request) -> None:
    """Runs on the first request AND on every redirect hop, which is where the interesting ones hide."""
    if os.getenv("TTM_ALLOW_PRIVATE_FETCH") == "1":
        return
    host = request.url.host
    if not host or not _public(host):
        raise BlockedTarget(f"refusing a non-public target: {host or request.url}")


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
                # A Client, not httpx.stream(), so the event hook sees every redirect hop too.
                client = httpx.Client(
                    follow_redirects=True,
                    timeout=180.0,
                    headers={**HEADERS, "User-Agent": agent},
                    event_hooks={"request": [_guard]},
                )
                with client, client.stream("GET", source) as r:
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
                if isinstance(exc, BlockedTarget):
                    break  # a second user agent reaches the same address; do not ask twice
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

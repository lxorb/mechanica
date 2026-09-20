"""Incremental DATA_DIR -> Azure Blob sync. Ingest workers write locally at full speed; this runs
every few minutes and pushes what changed.

A blob is skipped when its size matches the local file and its recorded mtime is not older than the
local one (both are kept in blob metadata, so the check costs one listing per prefix, not one HEAD
per file).

  api/.venv/Scripts/python -m tools.sync_blob                    # everything
  api/.venv/Scripts/python -m tools.sync_blob --pdf-only
  api/.venv/Scripts/python -m tools.sync_blob --json-only
  api/.venv/Scripts/python -m tools.sync_blob --delete-local-pdf-after-upload
  api/.venv/Scripts/python -m tools.sync_blob --compact          # fold links/* into bikes.json
  api/.venv/Scripts/python -m tools.sync_blob --loop 300         # keep syncing every 5 minutes

Credentials: AZURE_STORAGE_CONNECTION_STRING, or AZURE_STORAGE_ACCOUNT with DefaultAzureCredential,
or C:\\Users\\me\\agent-secrets\\azure-storage.txt.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure.core.exceptions import ResourceNotFoundError  # noqa: E402
from azure.storage.blob import ContentSettings  # noqa: E402

from app.config import SECRETS_DIR, settings  # noqa: E402
from app.store_blob import BlobStore  # noqa: E402

# local relative path -> blob name in the data container. Directories map one to one.
JSON_DIRS = {"manuals": "manuals", "pages": "pages", "specs": "specs"}
JSON_FILES = ("bikes.json", "registry.json")
SKIP_FILES = {"jobs.json", "costs.jsonl", "bulk_report.json"}

CT_JSON = ContentSettings(content_type="application/json")
CT_PDF = ContentSettings(content_type="application/pdf")


def connection() -> str | None:
    value = settings.azure_storage_connection_string
    if value:
        return value
    path = SECRETS_DIR / "azure-storage.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def store() -> BlobStore:
    conn = connection()
    if conn:
        return BlobStore(conn, settings.azure_data_container, settings.azure_pdf_container, pdf_base=settings.azure_pdf_base)
    if settings.azure_storage_account:
        return BlobStore(
            f"https://{settings.azure_storage_account}.blob.core.windows.net",
            settings.azure_data_container,
            settings.azure_pdf_container,
            pdf_base=settings.azure_pdf_base,
        )
    raise SystemExit("no credentials: set AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT")


def remote_index(bs: BlobStore, container: str, prefix: str) -> dict[str, tuple[int, float]]:
    client = bs.service.get_container_client(container)
    out: dict[str, tuple[int, float]] = {}
    for blob in client.list_blobs(name_starts_with=prefix, include=["metadata"]):
        meta = blob.metadata or {}
        try:
            mtime = float(meta.get("mtime", 0))
        except ValueError:
            mtime = 0.0
        out[blob.name] = (blob.size or 0, mtime)
    return out


def plan(local: list[tuple[Path, str]], index: dict[str, tuple[int, float]]) -> list[tuple[Path, str]]:
    todo = []
    for path, name in local:
        stat = path.stat()
        known = index.get(name)
        if known and known[0] == stat.st_size and known[1] >= int(stat.st_mtime):
            continue
        todo.append((path, name))
    return todo


def summary_metadata(path: Path) -> dict[str, str]:
    """Manuals carry their /manuals listing fields in blob metadata, exactly as put_manual writes them,
    so BlobStore.manual_summaries() never has to download the documents."""
    import json

    from app.models import Manual

    try:
        return BlobStore._meta(Manual.model_validate(json.loads(path.read_text(encoding="utf-8"))))
    except Exception as exc:
        print(f"metadata: {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {}


def upload(bs: BlobStore, container: str, path: Path, name: str, content_settings: ContentSettings) -> int:
    stat = path.stat()
    metadata = {"mtime": str(int(stat.st_mtime)), "src": path.name}
    if name.startswith("manuals/"):
        metadata.update(summary_metadata(path))
    with path.open("rb") as fh:
        bs.service.get_blob_client(container, name).upload_blob(
            fh,
            overwrite=True,
            content_settings=content_settings,
            metadata=metadata,
            max_concurrency=4,
        )
    return stat.st_size


def run_batch(bs: BlobStore, container: str, items: list[tuple[Path, str]], ct: ContentSettings, workers: int, label: str) -> tuple[int, int]:
    if not items:
        print(f"{label}: up to date")
        return 0, 0
    done = 0
    total = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(upload, bs, container, p, n, ct): (p, n) for p, n in items}
        for fut in as_completed(futures):
            path, name = futures[fut]
            try:
                total += fut.result()
                done += 1
                if done % 25 == 0 or done == len(items):
                    print(f"{label}: {done}/{len(items)} ({total / 1e6:.1f} MB)")
            except Exception as exc:
                print(f"{label}: FAILED {path.name} -> {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return done, total


def collect_json(root: Path) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for local_dir, prefix in JSON_DIRS.items():
        folder = root / local_dir
        if folder.exists():
            out += [(p, f"{prefix}/{p.name}") for p in sorted(folder.glob("*.json"))]
    for name in JSON_FILES:
        path = root / name
        if path.exists() and name not in SKIP_FILES:
            out.append((path, name))
    return out


def collect_pdf(root: Path) -> list[tuple[Path, str]]:
    folder = root / "pdf"
    return [(p, p.name) for p in sorted(folder.glob("*.pdf"))] if folder.exists() else []


def sync(bs: BlobStore, root: Path, args) -> None:
    started = time.time()
    if not args.pdf_only:
        items = collect_json(root)
        index = remote_index(bs, bs.data, "")
        todo = plan(items, index)
        print(f"json: {len(items)} local, {len(todo)} to upload")
        run_batch(bs, bs.data, todo, CT_JSON, args.workers, "json")

    if not args.json_only:
        items = collect_pdf(root)
        index = remote_index(bs, bs.pdf, "")
        todo = plan(items, index)
        print(f"pdf: {len(items)} local, {len(todo)} to upload")
        run_batch(bs, bs.pdf, todo, CT_PDF, args.workers, "pdf")
        if args.delete_local_pdf_after_upload:
            fresh = remote_index(bs, bs.pdf, "")
            removed = 0
            for path, name in items:
                known = fresh.get(name)
                if known and known[0] == path.stat().st_size:
                    path.unlink()
                    removed += 1
            print(f"pdf: removed {removed} local files now safely in blob")

    if args.compact:
        print(f"bikes: compacted {bs.compact_bikes()} link blobs into bikes.json")

    print(f"done in {time.time() - started:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(settings.data_dir))
    ap.add_argument("--pdf-only", action="store_true")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--delete-local-pdf-after-upload", action="store_true")
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--loop", type=int, default=0, metavar="SECONDS")
    args = ap.parse_args()

    root = Path(args.data_dir)
    if not root.exists():
        raise SystemExit(f"no such data dir: {root}")
    bs = store()
    account = os.environ.get("AZURE_STORAGE_ACCOUNT") or bs.service.account_name
    print(f"{root} -> {account} ({bs.data}, {bs.pdf})")

    sync(bs, root, args)
    while args.loop:
        time.sleep(args.loop)
        sync(bs, root, args)


if __name__ == "__main__":
    main()

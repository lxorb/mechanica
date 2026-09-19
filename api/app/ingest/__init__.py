"""STUB. Owner: ingest agent.

run() turns a PDF into a Manual (sections with keywords + grounded highlights, parts with shop links),
its Pages and Specs, stores them via get_store(), indexes via get_index(), and updates the IngestJob.
"""

from pathlib import Path

from ..config import settings
from ..models import Manual


def pdf_path(manual_id: str) -> Path:
    return settings.data_dir / "pdf" / f"{manual_id}.pdf"


def run(job_id: str, source: str, manual_id: str, bike_ids: list[str], make: str, model: str, year: int) -> Manual:
    """source = local path or http(s) URL of the official PDF."""
    raise NotImplementedError

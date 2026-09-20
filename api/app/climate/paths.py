"""Where the reduced artefacts live.

The image ships no data/ (api/.dockerignore), so the runtime looks in three places in order:
CLIMATE_DIR, then DATA_DIR/climate (where a deployed replica would sync them), then the repo's own
api/data/climate, which is what a checkout and the test suite see. First one that exists wins.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2] / "data" / "climate"


def climate_dir() -> Path:
    override = os.environ.get("CLIMATE_DIR")
    if override:
        return Path(override)
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        candidate = Path(data_dir) / "climate"
        if candidate.exists():
            return candidate
    return REPO_DIR


def rules_dir() -> Path:
    return climate_dir() / "rules"

"""Load the JSON fixtures from spec/fixtures/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Resolve repo root: this file is at langs/python/tests/conformance/fixtures/loader.py
# parents[0] = fixtures/
# parents[1] = conformance/
# parents[2] = tests/
# parents[3] = python/
# parents[4] = langs/
# parents[5] = repo root (VMx)
REPO_ROOT = Path(__file__).resolve().parents[5]
FIXTURES_DIR = REPO_ROOT / "spec" / "fixtures"


def load(filename: str) -> Any:
    """Load and return the parsed JSON for ``filename`` in spec/fixtures/."""
    path = FIXTURES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)

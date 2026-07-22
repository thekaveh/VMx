"""Load the spec-synchronized JSON fixtures shipped with the test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "data"


def load(filename: str) -> Any:
    """Load and return the parsed JSON fixture named ``filename``."""
    path = FIXTURES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)

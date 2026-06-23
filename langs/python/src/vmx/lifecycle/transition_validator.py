"""Lifecycle transition validator.

Loads spec/fixtures/lifecycle-transitions.json once (lazy) and exposes three
module-level helpers:

- ``is_legal(current, operation)`` — returns bool
- ``require(current, operation)`` — raises StatusTransitionError if illegal
- ``final_state(current, operation)`` — returns the final ConstructionStatus
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus

# ---------------------------------------------------------------------------
# JSON loading — two-pronged strategy
# ---------------------------------------------------------------------------
# 1. importlib.resources (works in installed wheels where the JSON is bundled
#    into vmx/lifecycle/_data/ via pyproject.toml force-include).
# 2. Repo-relative fallback (works in editable / source installs where the
#    bundle hasn't been copied yet, so we find the file by walking up from
#    this module's __file__ to the repo root).
# ---------------------------------------------------------------------------

_FIXTURE_NAME = "lifecycle-transitions.json"


def _load_from_importlib() -> str:
    """Try to read via importlib.resources (installed / editable with data)."""
    from importlib.resources import files  # Python 3.9+

    data_pkg = files("vmx.lifecycle").joinpath(f"_data/{_FIXTURE_NAME}")
    return data_pkg.read_text(encoding="utf-8")


def _load_from_repo() -> str:
    """Fallback: walk up from this file to find spec/fixtures/ in the repo."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "spec" / "fixtures" / _FIXTURE_NAME
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"Cannot locate {_FIXTURE_NAME} via importlib.resources or repo walk. "
        "Ensure the package is installed with 'uv sync --all-extras' or that "
        "you are running from within the VMx repository."
    )


def _load_table() -> list[dict[str, Any]]:
    try:
        raw = _load_from_importlib()
    except (FileNotFoundError, ModuleNotFoundError, TypeError):
        raw = _load_from_repo()
    data: dict[str, Any] = json.loads(raw)
    transitions: list[dict[str, Any]] = data["transitions"]
    return transitions


# Lazy cache — loaded once on first use. The lock makes first-touch
# initialization thread-safe (double-checked locking); reads after init stay
# lock-free since the reference assignment is atomic.
_table: list[dict[str, Any]] | None = None
_table_lock = threading.Lock()


def _get_table() -> list[dict[str, Any]]:
    global _table
    if _table is None:
        with _table_lock:
            if _table is None:
                _table = _load_table()
    return _table


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _find_row(current: ConstructionStatus, operation: str) -> dict[str, Any] | None:
    """Return the matching transition row, or None if not found."""
    from_name = current.name.capitalize()
    for row in _get_table():
        if row["from"] == from_name and row["via"] == operation:
            return row
    return None


def is_legal(current: ConstructionStatus, operation: str) -> bool:
    """Return ``True`` iff *operation* is allowed from *current* state."""
    row = _find_row(current, operation)
    if row is None:
        return False
    return bool(row["legal"])


def require(current: ConstructionStatus, operation: str) -> None:
    """Raise :exc:`StatusTransitionError` if *operation* is illegal from *current*."""
    if not is_legal(current, operation):
        raise StatusTransitionError(current, operation)


def final_state(current: ConstructionStatus, operation: str) -> ConstructionStatus:
    """Return the final :class:`ConstructionStatus` after *operation* completes.

    Raises
    ------
    StatusTransitionError
        If the operation is illegal from *current* or has no defined final state.
    """
    row = _find_row(current, operation)
    if row is None or not row["legal"] or row.get("to_final") is None:
        raise StatusTransitionError(current, operation)
    to_final: str = row["to_final"]
    return ConstructionStatus[to_final.upper()]

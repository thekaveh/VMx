"""Shared terminal-step helper for disposal paths across VMx packages."""

from __future__ import annotations

from collections.abc import Callable


def _run_disposal_steps(*steps: Callable[[], None]) -> None:
    """Attempt every terminal step and re-raise the first failure."""
    first_error: BaseException | None = None
    for step in steps:
        try:
            step()
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error

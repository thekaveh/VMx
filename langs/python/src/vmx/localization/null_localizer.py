"""NullLocalizer — null-object variant per ADR-0017."""

from __future__ import annotations

from collections.abc import Iterable


class NullLocalizer:
    """Returns the input key unchanged (no localization, no formatting)."""

    def localize(self, key: str, args: Iterable[object] | None = None) -> str:
        return key


NULL_LOCALIZER: NullLocalizer = NullLocalizer()
"""Shared singleton."""

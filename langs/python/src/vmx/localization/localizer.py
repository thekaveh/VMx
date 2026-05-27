"""ILocalizer Protocol. See spec/17-localization.md."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class ILocalizer(Protocol):
    """Localization hook contract."""

    def localize(self, key: str, args: Iterable[object] | None = None) -> str:
        """Return the localized string for ``key``, optionally formatted with ``args``."""
        ...

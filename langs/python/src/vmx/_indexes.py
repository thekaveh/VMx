"""Shared index-argument guard for VMx sequence containers."""

from __future__ import annotations


def _reject_bool_index(*indexes: object) -> None:
    """Raise ``TypeError`` if any index is a ``bool``.

    ``bool`` is an ``int`` subclass, so ``True`` and ``False`` would otherwise
    be accepted as positions and leak into collection-changed payloads.
    """
    if any(isinstance(index, bool) for index in indexes):
        raise TypeError("index must be an int, not bool")

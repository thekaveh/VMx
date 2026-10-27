"""ChildOrder — the order in which a container destructs and disposes its children.

``GroupVM``, ``CompositeVM`` and ``CompositeVMOf`` take a ``destruct_order``
builder option (spec/07 §2 and §3, spec/06 §5, ADR-0161). Construct order is
not affected: a container always constructs its children in child order.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class ChildOrder(Enum):
    """The order of a container's destruct walk and dispose cascade."""

    INSERTION = "insertion"
    """Visit children in child order, index 0 first (the default)."""

    REVERSE = "reverse"
    """Visit children in reverse child order, the last index first."""


def _in_destruct_order(children: Sequence[T], order: ChildOrder) -> list[T]:
    """Return a snapshot of ``children`` in the destruct and dispose order."""
    if order is ChildOrder.REVERSE:
        return list(reversed(children))
    return list(children)


__all__ = ["ChildOrder"]

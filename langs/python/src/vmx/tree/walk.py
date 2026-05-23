"""Depth-first walk / find over a VMx hierarchy.

See spec/13-tree-utilities.md (UTIL-001..003).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from vmx.components.base import _ComponentVMBase


def walk(root: _ComponentVMBase) -> Iterator[_ComponentVMBase]:
    """Yield ``root`` then every descendant in depth-first pre-order.

    A descendant of a ``CompositeVM`` or ``GroupVM`` is each item in its
    ``__iter__``. A descendant of an ``AggregateVMN`` is each non-``None``
    ``Component<i>`` slot, in slot index order.
    """
    yield root
    for child in _children(root):
        yield from walk(child)


def find(
    root: _ComponentVMBase,
    predicate: Callable[[_ComponentVMBase], bool],
) -> _ComponentVMBase | None:
    """Return the first node in ``walk(root)`` for which ``predicate`` is truthy."""
    for node in walk(root):
        if predicate(node):
            return node
    return None


def _children(node: _ComponentVMBase) -> Iterator[_ComponentVMBase]:
    if hasattr(node, "__iter__"):
        try:
            for child in iter(node):
                if isinstance(child, _ComponentVMBase):
                    yield child
            return
        except TypeError:
            pass

    for i in range(1, 6):
        slot = getattr(node, f"component_{i}", None)
        if isinstance(slot, _ComponentVMBase):
            yield slot

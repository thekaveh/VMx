"""Depth-first walk / find over a VMx hierarchy.

See spec/13-tree-utilities.md (UTIL-001..003).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from vmx.capabilities.expansion import IExpandable
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


def walk_expanded(root: _ComponentVMBase) -> Iterator[_ComponentVMBase]:
    """Yield ``root`` then descend only into children whose parent reports as
    expanded. A node that does NOT implement IExpandable is treated as
    always-expanded. See spec/13-tree-utilities.md §Expand-aware traversal.
    """
    yield root
    if isinstance(root, IExpandable) and not root.is_expanded:
        return
    for child in _children(root):
        yield from walk_expanded(child)


def _children(node: _ComponentVMBase) -> Iterator[_ComponentVMBase]:
    if hasattr(node, "__iter__"):
        try:
            for child in iter(node):
                if isinstance(child, _ComponentVMBase):
                    yield child
            return
        except TypeError:
            # Swallow — a node may advertise __iter__ but raise on iter()
            # (e.g. a guarded proxy); fall through to aggregate slot probing
            # below, same as nodes with no iterator at all.
            pass

    for i in range(1, 7):
        slot = getattr(node, f"component_{i}", None)
        if isinstance(slot, _ComponentVMBase):
            yield slot

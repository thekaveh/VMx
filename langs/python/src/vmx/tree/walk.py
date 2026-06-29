"""Depth-first walk / find over a VMx hierarchy.

See spec/13-tree-utilities.md (UTIL-001..003).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Protocol, runtime_checkable

from vmx.capabilities.expansion import IExpandable
from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ComponentVMProto


@runtime_checkable
class _AggregateComponents(Protocol):
    """The typed accessor an aggregate VM exposes for tree traversal — its
    component slots in declaration order.

    VMX-137: walking via this method (instead of probing ``component_{i}`` name
    strings bounded at ``range(1, 7)``) keeps ``walk``/``walk_expanded``/``find``
    correct for any arity, including a future AggregateVM7+.
    """

    def components(self) -> Sequence[ComponentVMProto]: ...


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

    # Aggregates expose a typed ``components()`` accessor (VMX-137) — no
    # per-arity ``component_{i}`` slot-name reflection, so AggregateVM7+ would be
    # traversed automatically.
    if isinstance(node, _AggregateComponents):
        for slot in node.components():
            if isinstance(slot, _ComponentVMBase):
                yield slot

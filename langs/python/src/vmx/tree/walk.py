"""Depth-first walk / find over a VMx hierarchy.

See spec/13-tree-utilities.md (UTIL-001..004).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Protocol, cast, runtime_checkable

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


def walk(root: ComponentVMProto) -> Iterator[ComponentVMProto]:
    """Yield ``root`` then every descendant in depth-first pre-order.

    A descendant of a ``CompositeVM`` or ``GroupVM`` is each item in its
    ``__iter__``. A descendant of an ``AggregateVMN`` is each non-``None``
    ``Component<i>`` slot, in slot index order.
    """
    return _pre_order(root, lambda _node: True)


def find(
    root: ComponentVMProto,
    predicate: Callable[[ComponentVMProto], bool],
) -> ComponentVMProto | None:
    """Return the first node in ``walk(root)`` for which ``predicate`` is truthy."""
    for node in walk(root):
        if predicate(node):
            return node
    return None


def walk_expanded(root: ComponentVMProto) -> Iterator[ComponentVMProto]:
    """Yield ``root`` then descend only into children whose parent reports as
    expanded. A node that does NOT implement IExpandable is treated as
    always-expanded. See spec/13-tree-utilities.md §Expand-aware traversal.
    """
    return _pre_order(root, _is_expanded_or_not_expandable)


def _is_expanded_or_not_expandable(node: ComponentVMProto) -> bool:
    return not (isinstance(node, IExpandable) and not node.is_expanded)


def _pre_order(
    root: ComponentVMProto,
    should_descend: Callable[[ComponentVMProto], bool],
) -> Iterator[ComponentVMProto]:
    """Pre-order walk with an explicit stack of child iterators.

    Each node is yielded before its children are read, and a node's children
    are read only when the walk descends into it, so the factory and error
    timing matches a recursive walk (spec/13 §6.1, ADR-0170). The stack keeps
    the walk iterative, so tree depth is not limited by the recursion limit.
    """
    yield root
    if not should_descend(root):
        return
    stack: list[Iterator[ComponentVMProto]] = [_children(root)]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            continue
        yield child
        if should_descend(child):
            stack.append(_children(child))


def _children(node: ComponentVMProto) -> Iterator[ComponentVMProto]:
    if hasattr(node, "__iter__"):
        # Any error from iter(node), including a TypeError, propagates. For a
        # HierarchicalVM, iter() reads ``children`` and runs the factory, so a
        # caught error would turn invalid factory output into a leaf
        # (spec/13 §6.1, ADR-0170, ADR-0212).
        for child in cast(Iterable[object], node):
            if isinstance(child, _ComponentVMBase):
                yield child
        return

    # Aggregates expose a typed ``components()`` accessor (VMX-137) — no
    # per-arity ``component_{i}`` slot-name reflection, so AggregateVM7+ would be
    # traversed automatically.
    if isinstance(node, _AggregateComponents):
        for slot in node.components():
            if isinstance(slot, _ComponentVMBase):
                yield slot

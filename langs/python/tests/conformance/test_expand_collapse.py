"""Conformance tests: EXP-001..005 — expand / collapse.

Per spec/05-component-vm.md, spec/13-tree-utilities.md, ADR-0015.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx import ComponentVMBuilder, MessageHub, RxDispatcher, ViewModelType
from vmx.capabilities import ExpandableState, IExpandable
from vmx.components.base import _ComponentVMBase
from vmx.tree import walk_expanded


def _vm(name: str) -> Any:
    return ComponentVMBuilder().name(name).services(MessageHub(), RxDispatcher.immediate()).build()


# ---------------------------------------------------------------------------
# EXP-001
# ---------------------------------------------------------------------------


@pytest.mark.conformance("EXP-001")
def test_EXP_001_defaults_to_collapsed() -> None:
    e = ExpandableState()
    assert e.is_expanded is False
    assert e.can_expand() is True
    assert e.can_collapse() is False


# ---------------------------------------------------------------------------
# EXP-002
# ---------------------------------------------------------------------------


@pytest.mark.conformance("EXP-002")
def test_EXP_002_expand_flips_and_emits() -> None:
    e = ExpandableState()
    observed: list[bool] = []
    e.is_expanded_changed.subscribe(on_next=observed.append)
    e.expand()
    assert e.is_expanded is True
    assert observed == [True]
    e.expand()  # no-op
    assert observed == [True]


# ---------------------------------------------------------------------------
# EXP-003
# ---------------------------------------------------------------------------


@pytest.mark.conformance("EXP-003")
def test_EXP_003_collapse_flips_back() -> None:
    e = ExpandableState(initially_expanded=True)
    observed: list[bool] = []
    e.is_expanded_changed.subscribe(on_next=observed.append)
    e.collapse()
    assert e.is_expanded is False
    assert observed == [False]


# ---------------------------------------------------------------------------
# EXP-004
# ---------------------------------------------------------------------------


@pytest.mark.conformance("EXP-004")
def test_EXP_004_toggle_alternates() -> None:
    e = ExpandableState()
    e.toggle_expansion()
    e.toggle_expansion()
    assert e.is_expanded is False
    e.toggle_expansion()
    assert e.is_expanded is True


# ---------------------------------------------------------------------------
# EXP-005 — walk_expanded skips descendants of collapsed nodes
# ---------------------------------------------------------------------------


class _ExpandableLeaf(_ComponentVMBase, IExpandable):
    """A minimal VM-like node that also implements IExpandable."""

    def __init__(self, name: str, children: list[Any], expanded: bool) -> None:
        # We don't call _ComponentVMBase.__init__ to avoid the full setup;
        # walk_expanded only needs _ComponentVMBase identity + iteration.
        self._name = name
        self._children = children
        self._expanded = expanded

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    def __iter__(self) -> Any:
        return iter(self._children)

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def can_expand(self) -> bool:
        return not self._expanded

    def expand(self) -> None:
        self._expanded = True


@pytest.mark.conformance("EXP-005")
def test_EXP_005_walk_expanded_skips_collapsed() -> None:
    a = _vm("a")
    b1 = _vm("b1")
    b2 = _vm("b2")
    b_collapsed = _ExpandableLeaf("b", [b1, b2], expanded=False)
    root = _ExpandableLeaf("root", [a, b_collapsed], expanded=True)

    visited = list(walk_expanded(root))
    assert root in visited
    assert a in visited
    assert b_collapsed in visited
    assert b1 not in visited
    assert b2 not in visited

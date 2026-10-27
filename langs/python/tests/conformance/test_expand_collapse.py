"""Conformance tests: EXP-001..008 — expand / collapse.

Per spec/05-component-vm.md, spec/13-tree-utilities.md, ADR-0015, ADR-0159.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx import ComponentVMBuilder, MessageHub, RxDispatcher, ViewModelType
from vmx.capabilities import ExpandableState, IExpandable
from vmx.commands import RelayCommand
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


# ---------------------------------------------------------------------------
# EXP-006..008 — expansion commands (ADR-0159)
# ---------------------------------------------------------------------------


def _count_changes(command: RelayCommand) -> list[None]:
    changes: list[None] = []
    command.can_execute_changed.subscribe(on_next=changes.append)
    return changes


@pytest.mark.conformance("EXP-006")
def test_EXP_006_command_predicates_track_can_checks_and_refire() -> None:
    e = ExpandableState()
    expand = e.expand_command
    collapse = e.collapse_command
    toggle = e.toggle_expansion_command
    changes = [_count_changes(c) for c in (expand, collapse, toggle)]

    assert expand.can_execute() is True
    assert collapse.can_execute() is False
    assert toggle.can_execute() is True

    e.expand()
    assert [len(c) for c in changes] == [1, 1, 1]
    assert expand.can_execute() is False
    assert collapse.can_execute() is True
    assert toggle.can_execute() is True

    e.expand()  # a no-op verb is not an expansion change
    assert [len(c) for c in changes] == [1, 1, 1]

    e.collapse()
    assert [len(c) for c in changes] == [2, 2, 2]
    assert expand.can_execute() is True
    assert collapse.can_execute() is False

    assert e.expand_command is expand
    assert e.collapse_command is collapse
    assert e.toggle_expansion_command is toggle


@pytest.mark.conformance("EXP-007")
def test_EXP_007_executing_each_command_performs_its_verb() -> None:
    e = ExpandableState()
    observed: list[bool] = []
    e.is_expanded_changed.subscribe(on_next=observed.append)

    e.expand_command.execute()
    assert e.is_expanded is True
    e.expand_command.execute()  # predicate is false while expanded
    assert observed == [True]

    e.collapse_command.execute()
    assert e.is_expanded is False
    e.collapse_command.execute()
    assert observed == [True, False]

    e.toggle_expansion_command.execute()
    assert e.is_expanded is True
    e.toggle_expansion_command.execute()
    assert e.is_expanded is False
    assert observed == [True, False, True, False]


@pytest.mark.conformance("EXP-008")
def test_EXP_008_helper_dispose_makes_commands_inert() -> None:
    e = ExpandableState()
    commands = (e.expand_command, e.collapse_command, e.toggle_expansion_command)
    observed: list[bool] = []
    e.is_expanded_changed.subscribe(on_next=observed.append)

    e.dispose()

    for command in commands:
        assert command.can_execute() is False
        command.execute()
    assert e.is_expanded is False
    assert observed == []

    # A command first read after disposal is inert as well.
    late = ExpandableState()
    late.dispose()
    for command in (late.expand_command, late.collapse_command, late.toggle_expansion_command):
        assert command.can_execute() is False
        command.execute()
    assert late.is_expanded is False
    assert late.expand_command is late.expand_command

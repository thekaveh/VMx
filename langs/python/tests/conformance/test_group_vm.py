"""Conformance tests: GRP-001..GRP-006 and GRP-011.

GRP-001 — Add emits CollectionChanged(action=Add)
GRP-002 — Group lacks child-navigation and child-selection members
GRP-003 — Construct waits until all children reach Constructed
GRP-004 — Destruct waits until all children reach Destructed
GRP-005 — AutoConstructOnAdd(true) auto-constructs late children (spec v1.1)
GRP-006 — BatchUpdate suppresses per-mutation events and emits one Reset (spec v1.1)
GRP-011 — Group children are peers; inherited child select command is disabled
"""

from __future__ import annotations

import pytest

from vmx.collections import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _make_child(name: str = "child") -> object:
    h = _hub()
    d = _dispatcher()
    return ComponentVMBuilder().name(name).services(h, d).build()


def _make_group(
    name: str = "grp",
    hub: MessageHub[object] | None = None,
) -> tuple[GroupVM[object], MessageHub[object]]:
    h = hub if hub is not None else _hub()
    d = _dispatcher()
    grp: GroupVM[object] = GroupVMBuilder().name(name).services(h, d).children(lambda: ()).build()
    return grp, h


# ===========================================================================
# GRP-001 — Add emits CollectionChanged(action=Add)
# ===========================================================================


@pytest.mark.conformance("GRP-001")
def test_GRP_001_add_emits_collection_changed() -> None:
    """GRP-001: group.add(vm) emits CollectionChanged(action=add, new_items=[vm], new_index=0)."""
    grp, _ = _make_group()
    grp.construct()

    events: list[CollectionChangedEvent] = []
    grp.on_collection_changed.subscribe(lambda e: events.append(e))

    child = _make_child()
    grp.add(child)

    assert len(events) == 1, "Expected exactly one CollectionChanged event"
    evt = events[0]
    assert evt.action == "add", f"Expected action='add', got {evt.action!r}"
    assert evt.new_items == (child,), f"Expected new_items=(child,), got {evt.new_items!r}"
    assert evt.new_index == 0, f"Expected new_index=0, got {evt.new_index}"


# ===========================================================================
# GRP-002 — Group lacks child-navigation and child-selection members
# ===========================================================================


@pytest.mark.conformance("GRP-002")
def test_GRP_002_group_lacks_navigation_and_selection_members() -> None:
    """GRP-002: GroupVM lacks current/select_component; SelectCommand/DeselectCommand present."""
    grp, _ = _make_group()

    # Must NOT have 'current' property.
    assert not hasattr(grp, "current"), "GroupVM must not expose 'current'"

    # Must NOT have select_component / deselect_component / can_select_component.
    assert not hasattr(grp, "select_component"), "GroupVM must not expose 'select_component'"
    assert not hasattr(grp, "deselect_component"), "GroupVM must not expose 'deselect_component'"
    assert not hasattr(grp, "can_select_component"), (
        "GroupVM must not expose 'can_select_component'"
    )

    # SelectCommand and DeselectCommand MUST be present
    # (operate on the group's own selection within its parent).
    assert hasattr(grp, "select_command"), "GroupVM must expose 'select_command'"
    assert grp.select_command is not None

    assert hasattr(grp, "deselect_command"), "GroupVM must expose 'deselect_command'"
    assert grp.deselect_command is not None

    # SelectNextCommand and SelectPreviousCommand are present as baseline
    # ComponentVMProto commands but their predicate is always False (no navigable children).
    assert hasattr(grp, "select_next_command"), (
        "GroupVM must expose 'select_next_command' (always-False no-op)"
    )
    assert grp.select_next_command.can_execute() is False, (
        "select_next_command.can_execute() must always be False for GroupVM"
    )
    assert hasattr(grp, "select_previous_command"), (
        "GroupVM must expose 'select_previous_command' (always-False no-op)"
    )
    assert grp.select_previous_command.can_execute() is False, (
        "select_previous_command.can_execute() must always be False for GroupVM"
    )


@pytest.mark.conformance("GRP-011")
def test_GRP_011_group_children_are_not_selectable() -> None:
    """GRP-011: a group child has a parent but no selectable current slot."""
    h = _hub()
    d = _dispatcher()
    child = ComponentVMBuilder().name("child").services(h, d).build()
    grp: GroupVM[object] = (
        GroupVMBuilder().name("g").services(h, d).children(lambda: (child,)).build()
    )

    grp.construct()

    assert child.can_select() is False
    assert child.select_command.can_execute() is False


# ===========================================================================
# GRP-003 — Construct waits until all children reach Constructed
# ===========================================================================


@pytest.mark.conformance("GRP-003")
def test_GRP_003_construct_waits_for_all_children() -> None:
    """GRP-003: group.construct() synchronously constructs every child before returning."""
    grp, _ = _make_group()

    children = [_make_child(f"c{i}") for i in range(4)]
    for c in children:
        grp.add(c)

    grp.construct()

    assert grp.status == ConstructionStatus.CONSTRUCTED, (
        f"Group status expected Constructed, got {grp.status}"
    )
    for i, child in enumerate(children):
        assert child.status == ConstructionStatus.CONSTRUCTED, (  # type: ignore[union-attr]
            f"Child {i} expected Constructed, got {child.status}"  # type: ignore[union-attr]
        )


# ===========================================================================
# GRP-004 — Destruct waits until all children reach Destructed
# ===========================================================================


@pytest.mark.conformance("GRP-004")
def test_GRP_004_destruct_waits_for_all_children() -> None:
    """GRP-004: group.destruct() synchronously destructs every child before returning."""
    grp, _ = _make_group()

    children = [_make_child(f"c{i}") for i in range(4)]
    for c in children:
        grp.add(c)

    grp.construct()
    grp.destruct()

    assert grp.status == ConstructionStatus.DESTRUCTED, (
        f"Group status expected Destructed, got {grp.status}"
    )
    for i, child in enumerate(children):
        assert child.status == ConstructionStatus.DESTRUCTED, (  # type: ignore[union-attr]
            f"Child {i} expected Destructed, got {child.status}"  # type: ignore[union-attr]
        )


# ===========================================================================
# GRP-005 — AutoConstructOnAdd(true) auto-constructs late children (spec v1.1)
# ===========================================================================


@pytest.mark.conformance("GRP-005")
def test_GRP_005_auto_construct_on_add() -> None:
    """GRP-005: child added after Constructed reaches Constructed before the event fires."""
    h = _hub()
    d = _dispatcher()
    grp: GroupVM[object] = (
        GroupVMBuilder()
        .name("grp")
        .services(h, d)
        .auto_construct_on_add(True)
        .children(lambda: ())
        .build()
    )
    grp.construct()

    child = _make_child("late")
    assert child.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]

    seen: list[tuple[CollectionChangedEvent, ConstructionStatus]] = []
    grp.on_collection_changed.subscribe(
        lambda e: seen.append((e, child.status))  # type: ignore[arg-type, union-attr]
    )

    grp.add(child)

    assert child.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert len(seen) == 1
    evt, status_at_event = seen[0]
    assert evt.action == "add"
    assert status_at_event == ConstructionStatus.CONSTRUCTED


# ===========================================================================
# GRP-006 — BatchUpdate suppresses per-mutation events and emits one Reset
# ===========================================================================


@pytest.mark.conformance("GRP-006")
def test_GRP_006_batch_update_emits_one_reset() -> None:
    """GRP-006: mutations inside a batch produce exactly one Reset at exit."""
    grp, _ = _make_group()
    grp.construct()

    events: list[CollectionChangedEvent] = []
    grp.on_collection_changed.subscribe(events.append)

    with grp.batch_update():
        for i in range(3):
            grp.add(_make_child(f"c{i}"))

    assert len(events) == 1, f"Expected one Reset event, got {[e.action for e in events]}"
    assert events[0].action == "reset"
    assert len(grp) == 3

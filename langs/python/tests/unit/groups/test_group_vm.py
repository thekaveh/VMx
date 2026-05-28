"""Unit tests for GroupVM and GroupVMBuilder.

Tests verify:
- Constructor sets name, hint, type
- Lifecycle operations (construct/destruct/reconstruct/dispose)
- Collection operations: add/insert/remove/remove_at/clear/setitem
- CollectionChanged events emitted correctly
- No current property, no select_component family
- select_command / deselect_command ARE present (own selection in parent)
- Children are constructed/destructed when group is
- Builder fluent API (BLD-001)
"""

from __future__ import annotations

import pytest

from vmx.builders.exceptions import BuilderValidationError
from vmx.collections import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder
from vmx.components.protocols import ViewModelType
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _make_child(name: str = "child", hub: MessageHub[object] | None = None) -> object:
    h = hub if hub is not None else _hub()
    d = _dispatcher()
    return ComponentVMBuilder().name(name).services(h, d).build()


def _make_group(
    name: str = "grp",
    hub: MessageHub[object] | None = None,
) -> tuple[GroupVM[object], MessageHub[object]]:
    h = hub if hub is not None else _hub()
    d = _dispatcher()
    vm: GroupVM[object] = GroupVMBuilder().name(name).services(h, d).build()
    return vm, h


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------


class TestGroupVMIdentity:
    def test_name_set_correctly(self) -> None:
        grp, _ = _make_group(name="my-group")
        assert grp.name == "my-group"

    def test_hint_defaults_to_empty(self) -> None:
        grp, _ = _make_group()
        assert grp.hint == ""

    def test_hint_set_via_builder(self) -> None:
        h = _hub()
        d = _dispatcher()
        grp: GroupVM[object] = GroupVMBuilder().name("g").hint("tip").services(h, d).build()
        assert grp.hint == "tip"

    def test_type_is_group(self) -> None:
        grp, _ = _make_group()
        assert grp.type == ViewModelType.GROUP

    def test_initial_status_is_destructed(self) -> None:
        grp, _ = _make_group()
        assert grp.status == ConstructionStatus.DESTRUCTED

    def test_initial_is_constructed_false(self) -> None:
        grp, _ = _make_group()
        assert grp.is_constructed is False


# ---------------------------------------------------------------------------
# No current / select_component surface
# ---------------------------------------------------------------------------


class TestGroupVMNoCurrent:
    def test_no_current_attribute(self) -> None:
        """GroupVM must not expose a 'current' property."""
        grp, _ = _make_group()
        assert not hasattr(grp, "current")

    def test_no_select_component(self) -> None:
        grp, _ = _make_group()
        assert not hasattr(grp, "select_component")

    def test_no_deselect_component(self) -> None:
        grp, _ = _make_group()
        assert not hasattr(grp, "deselect_component")

    def test_no_can_select_component(self) -> None:
        grp, _ = _make_group()
        assert not hasattr(grp, "can_select_component")

    def test_select_command_present(self) -> None:
        """SelectCommand IS present — operates on the group's own selection in parent."""
        grp, _ = _make_group()
        assert grp.select_command is not None

    def test_deselect_command_present(self) -> None:
        grp, _ = _make_group()
        assert grp.deselect_command is not None

    def test_select_next_command_present_but_noop(self) -> None:
        """select_next_command is inherited from IComponentVM baseline; always-False."""
        grp, _ = _make_group()
        assert grp.select_next_command is not None
        # The command predicate is always False for GroupVM (no navigable children).
        assert grp.select_next_command.can_execute() is False

    def test_select_previous_command_present_but_noop(self) -> None:
        grp, _ = _make_group()
        assert grp.select_previous_command is not None
        assert grp.select_previous_command.can_execute() is False


# ---------------------------------------------------------------------------
# Collection operations
# ---------------------------------------------------------------------------


class TestGroupVMCollection:
    def test_initial_count_zero(self) -> None:
        grp, _ = _make_group()
        assert len(grp) == 0
        assert grp.count == 0

    def test_add_increases_count(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        grp.add(child)
        assert len(grp) == 1

    def test_add_multiple_children(self) -> None:
        grp, _ = _make_group()
        for i in range(3):
            grp.add(_make_child(name=f"c{i}"))
        assert len(grp) == 3

    def test_getitem_returns_child(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        grp.add(child)
        assert grp[0] is child

    def test_insert_at_index(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.insert(0, b)
        assert grp[0] is b
        assert grp[1] is a

    def test_remove_existing_returns_true(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        grp.add(child)
        result = grp.remove(child)
        assert result is True
        assert len(grp) == 0

    def test_remove_absent_returns_false(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        result = grp.remove(child)
        assert result is False

    def test_remove_at_removes_correct_index(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.add(b)
        grp.remove_at(0)
        assert len(grp) == 1
        assert grp[0] is b

    def test_clear_empties_group(self) -> None:
        grp, _ = _make_group()
        for i in range(3):
            grp.add(_make_child(f"c{i}"))
        grp.clear()
        assert len(grp) == 0

    def test_contains_returns_true(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        grp.add(child)
        assert child in grp

    def test_contains_returns_false_for_absent(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        assert child not in grp

    def test_iter_yields_all_children(self) -> None:
        grp, _ = _make_group()
        children = [_make_child(f"c{i}") for i in range(3)]
        for c in children:
            grp.add(c)
        assert list(grp) == children

    def test_index_of_existing(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.add(b)
        assert grp.index_of(a) == 0
        assert grp.index_of(b) == 1

    def test_index_of_absent_returns_minus_one(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        assert grp.index_of(child) == -1

    def test_del_item_removes_at_index(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.add(b)
        del grp[0]
        assert len(grp) == 1
        assert grp[0] is b


# ---------------------------------------------------------------------------
# CollectionChanged events
# ---------------------------------------------------------------------------


class TestCollectionChangedEvents:
    def _collect_events(self, grp: GroupVM[object]) -> list[CollectionChangedEvent]:
        events: list[CollectionChangedEvent] = []
        grp.on_collection_changed.subscribe(lambda e: events.append(e))
        return events

    def test_add_emits_add_event(self) -> None:
        grp, _ = _make_group()
        events = self._collect_events(grp)
        child = _make_child()
        grp.add(child)
        assert len(events) == 1
        assert events[0].action == "add"
        assert events[0].new_items == (child,)
        assert events[0].new_index == 0

    def test_add_second_child_correct_index(self) -> None:
        grp, _ = _make_group()
        events = self._collect_events(grp)
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.add(b)
        assert events[1].new_index == 1

    def test_insert_emits_add_event(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        grp.add(a)
        events = self._collect_events(grp)
        b = _make_child("b")
        grp.insert(0, b)
        assert len(events) == 1
        assert events[0].action == "add"
        assert events[0].new_items == (b,)
        assert events[0].new_index == 0

    def test_remove_emits_remove_event(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        grp.add(child)
        events = self._collect_events(grp)
        grp.remove(child)
        assert len(events) == 1
        assert events[0].action == "remove"
        assert events[0].old_items == (child,)

    def test_remove_at_emits_remove_event(self) -> None:
        grp, _ = _make_group()
        child = _make_child()
        grp.add(child)
        events = self._collect_events(grp)
        grp.remove_at(0)
        assert len(events) == 1
        assert events[0].action == "remove"

    def test_clear_emits_reset_event(self) -> None:
        grp, _ = _make_group()
        grp.add(_make_child())
        events = self._collect_events(grp)
        grp.clear()
        assert len(events) == 1
        assert events[0].action == "reset"

    def test_setitem_emits_remove_then_add(self) -> None:
        grp, _ = _make_group()
        old = _make_child("old")
        new = _make_child("new")
        grp.add(old)
        events = self._collect_events(grp)
        grp[0] = new
        assert len(events) == 2
        assert events[0].action == "remove"
        assert events[1].action == "add"


# ---------------------------------------------------------------------------
# Lifecycle — children orchestration
# ---------------------------------------------------------------------------


class TestGroupVMLifecycle:
    def test_construct_constructs_group(self) -> None:
        grp, _ = _make_group()
        grp.construct()
        assert grp.is_constructed is True

    def test_construct_constructs_children(self) -> None:
        grp, _ = _make_group()
        children = [_make_child(f"c{i}") for i in range(3)]
        for c in children:
            grp.add(c)
        grp.construct()
        for c in children:
            assert c.is_constructed is True  # type: ignore[union-attr]

    def test_destruct_destructs_children(self) -> None:
        grp, _ = _make_group()
        children = [_make_child(f"c{i}") for i in range(3)]
        for c in children:
            grp.add(c)
        grp.construct()
        grp.destruct()
        for c in children:
            assert c.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
        assert grp.status == ConstructionStatus.DESTRUCTED

    def test_children_factory_evaluated_on_construct(self) -> None:
        h = _hub()
        d = _dispatcher()
        factory_calls: list[int] = []

        def _factory() -> list[object]:
            factory_calls.append(1)
            return [_make_child("fc")]

        grp: GroupVM[object] = GroupVMBuilder().name("g").services(h, d).children(_factory).build()
        assert len(grp) == 0
        assert factory_calls == []
        grp.construct()
        assert len(factory_calls) == 1
        assert len(grp) == 1

    def test_children_factory_not_re_evaluated_on_reconstruct(self) -> None:
        h = _hub()
        d = _dispatcher()
        factory_calls: list[int] = []

        def _factory() -> list[object]:
            factory_calls.append(1)
            return []

        grp: GroupVM[object] = GroupVMBuilder().name("g").services(h, d).children(_factory).build()
        grp.construct()
        grp.reconstruct()
        # Factory should be called only once.
        assert factory_calls == [1]

    def test_dispose_disposes_children(self) -> None:
        grp, _ = _make_group()
        children = [_make_child(f"c{i}") for i in range(2)]
        for c in children:
            grp.add(c)
        grp.construct()
        grp.dispose()
        for c in children:
            assert c.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
        assert grp.status == ConstructionStatus.DISPOSED

    def test_dispose_cascade_is_depth_first(self) -> None:
        from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage

        h = _hub()
        grp, _ = _make_group(hub=h)
        children = [_make_child(f"c{i}", hub=h) for i in range(2)]
        for c in children:
            grp.add(c)
        grp.construct()

        disposed: list[str] = []
        h.messages.subscribe(
            lambda m: (
                disposed.append(m.sender_name)
                if isinstance(m, ConstructionStatusChangedMessage)
                and m.status == ConstructionStatus.DISPOSED
                else None
            )
        )

        grp.dispose()

        assert disposed.index("c0") < disposed.index("grp"), (
            "children must enter DISPOSED before the group"
        )
        assert disposed.index("c1") < disposed.index("grp")

    def test_on_construct_callback_invoked(self) -> None:
        calls: list[int] = []
        h = _hub()
        d = _dispatcher()
        grp: GroupVM[object] = (
            GroupVMBuilder().name("g").services(h, d).on_construct(lambda: calls.append(1)).build()
        )
        grp.construct()
        assert calls == [1]

    def test_on_destruct_callback_invoked(self) -> None:
        calls: list[int] = []
        h = _hub()
        d = _dispatcher()
        grp: GroupVM[object] = (
            GroupVMBuilder().name("g").services(h, d).on_destruct(lambda: calls.append(1)).build()
        )
        grp.construct()
        grp.destruct()
        assert calls == [1]


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------


class TestGroupVMBuilder:
    def test_setter_returns_new_instance(self) -> None:
        b1 = GroupVMBuilder()
        b2 = b1.name("x")
        assert b1 is not b2
        assert b1._name is None
        assert b2._name == "x"

    def test_missing_name_raises(self) -> None:
        h = _hub()
        d = _dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            GroupVMBuilder().services(h, d).build()
        assert exc_info.value.missing_field == "name"

    def test_missing_hub_raises(self) -> None:
        with pytest.raises(BuilderValidationError) as exc_info:
            GroupVMBuilder().name("g").build()
        assert exc_info.value.missing_field == "hub"

    def test_missing_dispatcher_raises(self) -> None:
        import dataclasses

        h = _hub()
        with pytest.raises(BuilderValidationError) as exc_info:
            dataclasses.replace(GroupVMBuilder(), _name="g", _hub=h).build()
        assert exc_info.value.missing_field == "dispatcher"

    def test_repeated_build_distinct_groups(self) -> None:
        h = _hub()
        d = _dispatcher()
        b = GroupVMBuilder().name("g").services(h, d)
        g1 = b.build()
        g2 = b.build()
        assert g1 is not g2
        assert g1.name == g2.name

    def test_defaults_applied(self) -> None:
        h = _hub()
        d = _dispatcher()
        grp: GroupVM[object] = GroupVMBuilder().name("g").services(h, d).build()
        assert grp.hint == ""
        assert grp.type == ViewModelType.GROUP

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

from threading import Event, Thread

import pytest

from vmx.builders.exceptions import BuilderValidationError
from vmx.collections import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.components.protocols import ViewModelType
from vmx.groups import group_vm as group_module
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
    vm: GroupVM[object] = GroupVMBuilder().name(name).services(h, d).children(lambda: ()).build()
    return vm, h


class _ThrowingDisposeChild(ComponentVM):
    def _on_dispose(self) -> None:
        raise RuntimeError("dispose hook failure")


def test_factory_output_after_reentrant_disposal_is_rejected() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    late = _make_child("late", hub)
    group: GroupVM[object]

    def children() -> tuple[object, ...]:
        group.dispose()
        return (late,)

    group = GroupVMBuilder().name("group").services(hub, dispatcher).children(children).build()

    with pytest.raises(RuntimeError, match="disposing"):
        group.construct()
    assert group.count == 0
    assert late.status is ConstructionStatus.DESTRUCTED


def test_factory_rejects_duplicate_child_identity_without_partial_membership() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    child = _make_child("duplicate", hub)
    group = (
        GroupVMBuilder()
        .name("group")
        .services(hub, dispatcher)
        .children(lambda: (child, child))
        .build()
    )

    with pytest.raises(ValueError, match="duplicate child identity"):
        group.construct()

    assert group.snapshot() == ()
    assert child._parent is None


def test_auto_construct_hook_cannot_reparent_during_membership_transaction() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    source, _ = _make_group("source", hub)
    destination, _ = _make_group("destination", hub)
    source._auto_construct_on_add = True
    source.construct()
    child: ComponentVM
    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(lambda: destination.add(child))
        .build()
    )

    with pytest.raises(RuntimeError, match="ownership transaction is in progress"):
        source.add(child)

    assert source.snapshot() == ()
    assert destination.snapshot() == ()
    assert child._parent is None


def test_auto_construct_hook_disposal_aborts_admission() -> None:
    group, hub = _make_group()
    group._auto_construct_on_add = True
    group.construct()
    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, _dispatcher())
        .on_construct(group.dispose)
        .build()
    )

    with pytest.raises(RuntimeError, match="disposing"):
        group.add(child)

    assert group.snapshot() == ()
    assert child._parent is None


def test_concurrent_admission_cannot_escape_disposal_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group, _ = _make_group()
    late = _make_child("late")
    entered = Event()
    release = Event()
    disposal_done = Event()
    failures: list[BaseException] = []
    original = group_module._begin_parent_transfer

    def blocked_transfer(child: object, parent: object) -> object:
        entered.set()
        assert release.wait(timeout=2)
        return original(child, parent)  # type: ignore[arg-type]

    monkeypatch.setattr(group_module, "_begin_parent_transfer", blocked_transfer)

    def admit() -> None:
        try:
            group.add(late)
        except BaseException as error:
            failures.append(error)

    def dispose() -> None:
        group.dispose()
        disposal_done.set()

    worker = Thread(target=admit)
    worker.start()
    assert entered.wait(timeout=2)
    disposer = Thread(target=dispose)
    disposer.start()
    assert not disposal_done.wait(timeout=0.05)
    release.set()
    worker.join(timeout=2)
    disposer.join(timeout=2)

    assert not worker.is_alive()
    assert not disposer.is_alive()
    assert failures == []
    assert late in group
    assert late.status is ConstructionStatus.DISPOSED
    assert group.status is ConstructionStatus.DISPOSED


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
        grp: GroupVM[object] = (
            GroupVMBuilder().name("g").hint("tip").services(h, d).children(lambda: ()).build()
        )
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
        """select_next_command is inherited from ComponentVMProto baseline; always-False."""
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

    def test_insert_negative_index_emits_effective_position(self) -> None:
        """spec/21 §3.2: new_index carries the actual insertion position."""
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        c = _make_child("c")
        grp.add(a)
        grp.add(b)
        events: list[CollectionChangedEvent] = []
        grp.on_collection_changed.subscribe(events.append)
        grp.insert(-1, c)
        assert grp[1] is c
        assert events[0].new_index == 1

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

    def test_remove_at_negative_index_emits_resolved_index(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.add(b)
        events = self._collect_events(grp)
        grp.remove_at(-1)  # removes the last child (b)
        assert len(events) == 1
        assert events[0].action == "remove"
        assert events[0].old_items == (b,)
        # old_index is the resolved position (1), not the raw -1.
        assert events[0].old_index == 1

    def test_setitem_negative_index_emits_resolved_index(self) -> None:
        grp, _ = _make_group()
        a = _make_child("a")
        b = _make_child("b")
        grp.add(a)
        grp.add(b)
        events = self._collect_events(grp)
        c = _make_child("c")
        grp[-1] = c  # replaces the last child (b) with c
        # remove(old) then add(new), both at the resolved index 1.
        assert [e.action for e in events] == ["remove", "add"]
        assert events[0].old_index == 1
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

    def test_failed_factory_population_rolls_back_and_retries(self) -> None:
        h = _hub()
        d = _dispatcher()
        child_a = _make_child("a", hub=h)
        child_b = _make_child("b", hub=h)
        calls = 0

        def _factory() -> object:
            nonlocal calls
            calls += 1
            yield child_a
            if calls == 1:
                raise RuntimeError("transient factory failure")
            yield child_b

        grp: GroupVM[object] = GroupVMBuilder().name("g").services(h, d).children(_factory).build()

        with pytest.raises(RuntimeError, match="transient factory failure"):
            grp.construct()

        assert grp.status == ConstructionStatus.DESTRUCTED
        assert grp.count == 0

        grp.construct()

        assert calls == 2
        assert list(grp) == [child_a, child_b]
        assert grp.status == ConstructionStatus.CONSTRUCTED

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

    def test_dispose_continues_after_child_failure_and_reraises_first_error(self) -> None:
        grp, hub = _make_group()
        dispatcher = _dispatcher()
        throwing = _ThrowingDisposeChild(name="throwing", hint="", hub=hub, dispatcher=dispatcher)
        sibling = _make_child("sibling", hub)
        grp.add(throwing)
        grp.add(sibling)

        with pytest.raises(RuntimeError, match="dispose hook failure"):
            grp.dispose()

        assert throwing.status == ConstructionStatus.DISPOSED
        assert sibling.status == ConstructionStatus.DISPOSED  # type: ignore[union-attr]
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
            GroupVMBuilder()
            .name("g")
            .services(h, d)
            .on_construct(lambda: calls.append(1))
            .children(lambda: ())
            .build()
        )
        grp.construct()
        assert calls == [1]

    def test_on_destruct_callback_invoked(self) -> None:
        calls: list[int] = []
        h = _hub()
        d = _dispatcher()
        grp: GroupVM[object] = (
            GroupVMBuilder()
            .name("g")
            .services(h, d)
            .on_destruct(lambda: calls.append(1))
            .children(lambda: ())
            .build()
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

    def test_missing_children_raises(self) -> None:
        """Per spec/10-builders.md §3 + ADR-0035: GroupVM<VM> requires a
        ``children(lambda: ...)`` factory. For an empty group, pass
        ``children(lambda: ())`` explicitly.
        """
        h = _hub()
        d = _dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            GroupVMBuilder().name("g").services(h, d).build()
        assert exc_info.value.missing_field == "children"

    def test_repeated_build_distinct_groups(self) -> None:
        h = _hub()
        d = _dispatcher()
        b = GroupVMBuilder().name("g").services(h, d).children(lambda: ())
        g1 = b.build()
        g2 = b.build()
        assert g1 is not g2
        assert g1.name == g2.name

    def test_defaults_applied(self) -> None:
        h = _hub()
        d = _dispatcher()
        grp: GroupVM[object] = (
            GroupVMBuilder().name("g").services(h, d).children(lambda: ()).build()
        )
        assert grp.hint == ""
        assert grp.type == ViewModelType.GROUP


def test_on_construct_iterates_snapshot_when_child_mutates_group() -> None:
    """A child whose construct hook mutates the group must not skip siblings."""
    h = _hub()
    d = _dispatcher()
    group, _ = _make_group(hub=h)
    b = _make_child("b", hub=h)
    a = ComponentVMBuilder().name("a").services(h, d).on_construct(lambda: group.remove(a)).build()
    group.add(a)
    group.add(b)

    group.construct()

    assert b.status is ConstructionStatus.CONSTRUCTED  # type: ignore[attr-defined]

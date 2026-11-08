"""Replacing the current child, and the Constructed check of a selection.

An index replacement keeps the replaced child owned and current until its
commit, which frees the child and clears ``current`` in one locked section.
No container can adopt the child while it is still current here, and a
failed replacement restores it silently (spec/06 §3, §4.2, §4.3 rule 6,
#1219). ``select_component`` checks Constructed again at its commit, also at
an asynchronous delivery (spec/06 §3.1, §4.3 rule 7, #1220). A child's
``select()`` silently refuses a member that is not Constructed and checks
again at the same commit (spec/05 §6, #1229). Mirrors the Swift
``CompositeVMMembershipTests`` and ``CompositeSelectionTests``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _HookFailedError(Exception):
    pass


class _QueueScheduler:
    """Queues work so a test decides when each item runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []
        self._lock = threading.Lock()

    def schedule(self, action: Any, state: Any = None) -> None:
        with self._lock:
            self.actions.append(action)

    def run_all(self) -> None:
        while True:
            with self._lock:
                if not self.actions:
                    return
                action = self.actions.pop(0)
            action(self, None)


def _immediate() -> RxDispatcher:
    return RxDispatcher(ImmediateScheduler(), ImmediateScheduler())


def _leaf(name: str, on_construct: Callable[[], None] | None = None) -> ComponentVM:
    return ComponentVM(
        name=name, hub=MessageHub(), dispatcher=_immediate(), on_construct=on_construct
    )


def _composite(
    children: list[ComponentVM],
    *,
    dispatcher: RxDispatcher | None = None,
    async_selection: bool = False,
    changes: list[str | None] | None = None,
) -> CompositeVM[ComponentVM]:
    record = changes if changes is not None else []
    composite: CompositeVM[ComponentVM] = (
        CompositeVMBuilder[ComponentVM]()
        .name("composite")
        .services(MessageHub(), dispatcher or _immediate())
        .children(lambda: children)
        .auto_construct_on_add(True)
        .async_selection(async_selection)
        .on_current_changed(lambda value: record.append(None if value is None else value.name))
        .build()
    )
    return composite


class _Replacement:
    """A Constructed composite ``[a, b]`` with ``a`` current, and a
    replacement whose construct hook runs inside the replacement's
    transaction."""

    def __init__(self, hook: Callable[[ComponentVM, CompositeVM[ComponentVM]], None]) -> None:
        self.a = _leaf("a")
        self.b = _leaf("b")
        self.changes: list[str | None] = []
        self.sut = _composite([self.a, self.b], changes=self.changes)
        self.sut.construct()
        self.sut.current = self.a
        self.changes.clear()
        self.replacement = _leaf("replacement", lambda: hook(self.a, self.sut))


def test_the_replacement_hook_sees_the_current_child_still_owned_and_flagged() -> None:
    observed: list[tuple[bool, bool, bool]] = []
    scenario = _Replacement(
        lambda a, sut: observed.append((a._parent is sut, sut.current is a, a.is_current))
    )

    scenario.sut[0] = scenario.replacement

    assert len(observed) == 1, "the replacement's construct hook ran"
    owned, current, flag = observed[0]
    assert current, "current changes only at the commit"
    assert owned, "the composite still owns its current child"
    assert flag == current, "is_current matches current inside the hook"
    assert scenario.sut.current is None
    assert not scenario.a.is_current
    assert scenario.a._parent is None
    assert scenario.changes == [None]


def test_the_replacement_hook_cannot_adopt_and_select_the_replaced_current_child() -> None:
    other = _composite([])
    other.construct()

    def hook(a: ComponentVM, _sut: CompositeVM[ComponentVM]) -> None:
        try:
            other.append(a)
            other.current = a
        except (RuntimeError, ValueError):
            pass

    scenario = _Replacement(hook)

    scenario.sut[0] = scenario.replacement

    a = scenario.a
    assert scenario.sut.current is None
    assert a.is_current == (other.current is a), (
        "the commit's clear never resets a selection in another composite (COMP-006)"
    )
    holders = [c for c in (scenario.sut, other) if any(child is a for child in c.snapshot())]
    assert len(holders) <= 1
    if holders:
        assert a._parent is holders[0]


def test_a_failed_replacement_leaves_the_replaced_child_in_exactly_one_composite() -> None:
    other = _composite([])
    other.construct()

    def hook(a: ComponentVM, _sut: CompositeVM[ComponentVM]) -> None:
        try:
            other.append(a)
        except RuntimeError:
            pass
        raise _HookFailedError

    scenario = _Replacement(hook)

    with pytest.raises(_HookFailedError):
        scenario.sut[0] = scenario.replacement

    a = scenario.a
    holders = [c for c in (scenario.sut, other) if any(child is a for child in c.snapshot())]
    assert len(holders) == 1, "a is a member of exactly one composite"
    assert a._parent is holders[0], "a's owner is the composite that holds it"
    assert list(scenario.sut.snapshot()) == [a, scenario.b]
    assert scenario.replacement._parent is None


def test_a_failed_replacement_of_the_current_child_restores_it_silently() -> None:
    def hook(_a: ComponentVM, _sut: CompositeVM[ComponentVM]) -> None:
        raise _HookFailedError

    scenario = _Replacement(hook)
    a = scenario.a
    events: list[object] = []
    properties: list[str] = []
    scenario.sut.on_collection_changed.subscribe(events.append)
    scenario.sut.property_changed.subscribe(properties.append)
    a.property_changed.subscribe(properties.append)

    with pytest.raises(_HookFailedError):
        scenario.sut[0] = scenario.replacement

    assert list(scenario.sut.snapshot()) == [a, scenario.b]
    assert scenario.sut.current is a
    assert a.is_current
    assert a._parent is scenario.sut
    assert events == []
    assert scenario.changes == []
    assert "current" not in properties
    assert "is_current" not in properties


class _DestructAfterStatusRead(ComponentVM):
    """A leaf whose next ``status`` read, once armed, destructs it and still
    returns the status it read first. It puts a destruct between a selection
    path's entry check and its commit, as another thread could (#1220)."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name, hub=MessageHub(), dispatcher=_immediate())
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    @property
    def status(self) -> ConstructionStatus:
        value = super().status
        if self._armed:
            self._armed = False
            self.destruct()
        return value


def _armed_scenario() -> tuple[CompositeVM[ComponentVM], _DestructAfterStatusRead]:
    vm = _DestructAfterStatusRead("vm")
    composite = _composite([vm])
    composite.construct()
    assert vm.status is S.CONSTRUCTED
    vm.arm()
    return composite, vm


def test_select_component_refuses_a_child_destructed_after_the_entry_check() -> None:
    composite, vm = _armed_scenario()

    with pytest.raises(ValueError, match="can_select_component"):
        composite.select_component(vm)

    assert vm.status is S.DESTRUCTED, "the seam destructed vm before the commit"
    assert composite.current is None
    assert not vm.is_current


def test_async_select_component_delivery_drops_a_child_destructed_after_the_call() -> None:
    foreground = _QueueScheduler()
    dispatcher = RxDispatcher(foreground, ImmediateScheduler())  # type: ignore[arg-type]
    vm = _leaf("vm")
    composite = _composite([vm], dispatcher=dispatcher, async_selection=True)
    composite.construct()
    foreground.run_all()

    composite.select_component(vm)
    vm.destruct()
    foreground.run_all()

    assert composite.current is None, "the delivery checks Constructed again"
    assert not vm.is_current


def test_select_component_selects_a_constructed_member() -> None:
    vm = _DestructAfterStatusRead("vm")
    composite = _composite([vm])
    composite.construct()

    composite.select_component(vm)

    assert composite.current is vm
    assert vm.is_current
    assert vm.status is S.CONSTRUCTED


# ── select() on a member that is not Constructed (#1229) ──────────────────────


def _queued_composite(
    vm: ComponentVM,
) -> tuple[CompositeVM[ComponentVM], _QueueScheduler]:
    foreground = _QueueScheduler()
    dispatcher = RxDispatcher(foreground, ImmediateScheduler())  # type: ignore[arg-type]
    composite = _composite([vm], dispatcher=dispatcher, async_selection=True)
    composite.construct()
    foreground.run_all()
    return composite, foreground


def test_select_on_a_destructed_member_selects_nothing() -> None:
    a = _leaf("a")
    changes: list[str | None] = []
    composite = _composite([a], changes=changes)
    composite.construct()
    a.destruct()

    a.select()

    assert composite.current is None
    assert not a.is_current
    assert changes == []


def test_async_select_on_a_destructed_member_selects_nothing() -> None:
    a = _leaf("a")
    composite, foreground = _queued_composite(a)
    a.destruct()

    a.select()
    foreground.run_all()

    assert composite.current is None
    assert not a.is_current


def test_async_select_delivery_drops_a_member_destructed_after_the_call() -> None:
    a = _leaf("a")
    composite, foreground = _queued_composite(a)

    a.select()
    a.destruct()
    foreground.run_all()

    assert composite.current is None, "the delivery checks Constructed again"
    assert not a.is_current


def test_select_refuses_a_member_destructed_after_the_entry_check() -> None:
    composite, vm = _armed_scenario()

    with pytest.raises(ValueError, match="can_select_component"):
        vm.select()

    assert vm.status is S.DESTRUCTED, "the seam destructed vm before the commit"
    assert composite.current is None
    assert not vm.is_current


def test_select_on_a_destructed_member_still_raises_inside_the_callers_transaction() -> None:
    a = _leaf("a")
    composite = _composite([a])
    composite.construct()
    a.destruct()
    caught: list[RuntimeError] = []

    def hook() -> None:
        try:
            a.select()
        except RuntimeError as error:
            caught.append(error)

    composite.add(_leaf("b"))
    composite[1] = _leaf("replacement", hook)

    assert len(caught) == 1
    assert "transaction" in str(caught[0])
    assert composite.current is None


def test_select_on_a_constructed_member_makes_it_current() -> None:
    a = _leaf("a")
    composite = _composite([a])
    composite.construct()

    a.select()

    assert composite.current is a
    assert a.is_current


def test_async_select_on_a_constructed_member_makes_it_current() -> None:
    a = _leaf("a")
    composite, foreground = _queued_composite(a)

    a.select()
    foreground.run_all()

    assert composite.current is a
    assert a.is_current

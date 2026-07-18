"""Conformance tests: COMP-001..013 + LIFE-013.

Each test is decorated with ``@pytest.mark.conformance("XXX-NNN")`` so the
coverage checker finds it.

COMP-006 uses TestScheduler (via TestDispatcher) to verify that IsCurrent
changes on the previously-Current child are dispatched on the foreground
scheduler (ObserveOn pattern).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from collections.abc import Callable
from threading import Barrier, BrokenBarrierError, Event, Thread

import pytest

from vmx.collections import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder
from vmx.components.component_vm import ComponentVM, ComponentVMOf
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM, CompositeVMOf
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


class _DisposeFailingComponent(ComponentVM):
    def _on_dispose(self) -> None:
        raise RuntimeError("dispose failure")


class _DisposeFailingComposite(CompositeVM[ComponentVM]):
    def _on_dispose(self) -> None:
        super()._on_dispose()
        raise RuntimeError("destination dispose failure")


def _build_composite(
    name: str = "comp",
    async_selection: bool = False,
    hub: MessageHub[object] | None = None,
    dispatcher: object | None = None,
) -> tuple[CompositeVM[ComponentVM], MessageHub[object]]:
    h = hub if hub is not None else _hub()
    d = dispatcher if dispatcher is not None else _dispatcher()
    vm: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name(name)
        .services(h, d)
        .async_selection(async_selection)
        .children(lambda: ())
        .build()
    )
    return vm, h


def _build_child(
    name: str = "child",
    hub: MessageHub[object] | None = None,
    dispatcher: object | None = None,
) -> ComponentVM:
    h = hub if hub is not None else _hub()
    d = dispatcher if dispatcher is not None else _dispatcher()
    return ComponentVMBuilder().name(name).services(h, d).build()


class _EqualByNameComponent(ComponentVM):
    def __eq__(self, other: object) -> bool:
        return isinstance(other, _EqualByNameComponent) and other.name == self.name

    __hash__ = None


def _build_equal_child(name: str) -> _EqualByNameComponent:
    return _EqualByNameComponent(
        name=name,
        hint="",
        hub=_hub(),
        dispatcher=_dispatcher(),
    )


def _prop_messages(hub: MessageHub[object]) -> list[PropertyChangedMessage]:
    collected: list[PropertyChangedMessage] = []
    hub.messages.subscribe(
        lambda m: collected.append(m) if isinstance(m, PropertyChangedMessage) else None
    )
    return collected


def test_async_selection_drops_removed_child_before_dispatch() -> None:
    """Regression: with async selection, a child removed between select_component
    and the deferred foreground dispatch must NOT become current (spec/06 §3 — a
    non-null current is always a member of the children collection)."""
    from tests.unit.helpers.test_dispatcher import TestDispatcher

    test_disp = TestDispatcher()
    hub = _hub()
    child = _build_child("a", hub=hub, dispatcher=test_disp)
    comp: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("comp")
        .services(hub, test_disp)
        .async_selection(True)
        .children(lambda: ())
        .build()
    )
    child.construct()
    comp.append(child)

    comp.select_component(child)  # deferred
    comp.remove(child)  # removed before dispatch
    test_disp.foreground_scheduler.advance_by(10)  # deliver

    assert comp.current is None, "a removed child must not become current"
    assert child.is_current is False, "removed child's is_current must not be set"


# ===========================================================================
# COMP-001 — Add emits CollectionChanged(action=Add)
# ===========================================================================


@pytest.mark.conformance("COMP-001")
def test_COMP_001_add_emits_collection_changed_add() -> None:
    """COMP-001: Add emits CollectionChanged(action=Add, newItems=[vm], newIndex=0)."""
    comp, _ = _build_composite()
    comp.construct()

    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    child = _build_child()
    comp.append(child)

    assert len(events) == 1
    assert events[0].action == "add"
    assert child in events[0].new_items
    assert events[0].new_index == 0


# ===========================================================================
# COMP-002 — Remove emits CollectionChanged(action=Remove)
# ===========================================================================


@pytest.mark.conformance("COMP-002")
def test_COMP_002_remove_emits_collection_changed_remove() -> None:
    """COMP-002: composite.Remove(vm) emits CollectionChanged(action=Remove).

    Specifically: oldItems=[vm], oldIndex=0.
    """
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)

    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.remove(child)

    assert len(events) == 1
    assert events[0].action == "remove"
    assert child in events[0].old_items
    assert events[0].old_index == 0


# ===========================================================================
# COMP-003 — select_component sets Current
# ===========================================================================


@pytest.mark.conformance("COMP-003")
def test_COMP_003_select_component_sets_current() -> None:
    """COMP-003: select_component(vm) sets Current==vm, vm.IsCurrent==True,
    emits PropertyChangedMessage('current') and PropertyChangedMessage('is_current')."""
    hub = _hub()
    disp = _dispatcher()
    child = _build_child(hub=hub, dispatcher=disp)
    comp, _ = _build_composite(hub=hub, dispatcher=disp)

    child.construct()
    comp.append(child)

    prop_msgs = _prop_messages(hub)
    comp.select_component(child)

    assert comp.current is child
    assert child.is_current is True

    current_msgs = [m for m in prop_msgs if m.property_name == "current"]
    assert len(current_msgs) >= 1

    is_current_msgs = [
        m for m in prop_msgs if m.property_name == "is_current" and m.sender is child
    ]
    assert len(is_current_msgs) >= 1


# ===========================================================================
# COMP-004 — Construct waits until all children reach Constructed
# ===========================================================================


@pytest.mark.conformance("COMP-004")
def test_COMP_004_construct_waits_for_all_children() -> None:
    """COMP-004: after composite.construct(), every child has Status==Constructed."""
    hub = _hub()
    disp = _dispatcher()
    child_a = _build_child("a", hub=hub, dispatcher=disp)
    child_b = _build_child("b", hub=hub, dispatcher=disp)
    child_c = _build_child("c", hub=hub, dispatcher=disp)

    comp: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("comp")
        .services(hub, disp)
        .children(lambda: [child_a, child_b, child_c])
        .build()
    )

    comp.construct()

    assert comp.status == ConstructionStatus.CONSTRUCTED
    for child in [child_a, child_b, child_c]:
        assert child.status == ConstructionStatus.CONSTRUCTED


# ===========================================================================
# COMP-005 — Destruct waits until all children reach Destructed
# ===========================================================================


@pytest.mark.conformance("COMP-005")
def test_COMP_005_destruct_waits_for_all_children() -> None:
    """COMP-005: after composite.destruct(), Current==None and every child Destructed."""
    hub = _hub()
    disp = _dispatcher()
    child_a = _build_child("a", hub=hub, dispatcher=disp)
    child_b = _build_child("b", hub=hub, dispatcher=disp)

    comp: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("comp")
        .services(hub, disp)
        .children(lambda: [child_a, child_b])
        .build()
    )
    comp.construct()
    comp.current = child_a

    comp.destruct()

    assert comp.current is None
    assert comp.status == ConstructionStatus.DESTRUCTED
    assert child_a.status == ConstructionStatus.DESTRUCTED
    assert child_b.status == ConstructionStatus.DESTRUCTED


# ===========================================================================
# COMP-006 — IsCurrent change on previously-Current child dispatches on foreground
# ===========================================================================


@pytest.mark.conformance("COMP-006")
def test_COMP_006_is_current_change_dispatches_on_foreground() -> None:
    """COMP-006: changing Current (or deselect_component) fires IsCurrent change
    on the foreground scheduler when using ObserveOn(dispatcher.Foreground)."""
    import reactivex.operators as ops

    from tests.unit.helpers.test_dispatcher import TestDispatcher

    test_disp = TestDispatcher()
    hub = _hub()
    child_a = _build_child("a", hub=hub, dispatcher=test_disp)
    child_b = _build_child("b", hub=hub, dispatcher=test_disp)

    comp: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("comp").services(hub, test_disp).children(lambda: ()).build()
    )

    child_a.construct()
    child_b.construct()
    comp.append(child_a)
    comp.append(child_b)
    comp.current = child_a

    # Collect IsCurrent messages for vmA observed on the foreground scheduler.
    is_current_msgs_on_fg: list[PropertyChangedMessage] = []
    hub.messages.pipe(
        ops.filter(
            lambda m: (
                isinstance(m, PropertyChangedMessage)
                and m.property_name == "is_current"
                and m.sender is child_a
            )
        ),
        ops.observe_on(test_disp.foreground),
    ).subscribe(is_current_msgs_on_fg.append)

    # Change current to vmB — this should fire IsCurrent(false) for vmA.
    comp.current = child_b

    # Without advancing the scheduler, the handler should NOT have fired yet
    # (the observe_on defers to the foreground scheduler).
    # Advance to deliver scheduled work.
    test_disp.foreground_scheduler.advance_by(10)

    assert len(is_current_msgs_on_fg) >= 1, (
        "Expected at least one IsCurrent message for vmA on foreground scheduler"
    )


# ===========================================================================
# COMP-007 — Modeled composite maps model factory output to children
# ===========================================================================


@pytest.mark.conformance("COMP-007")
def test_COMP_007_modeled_composite_maps_models_to_children() -> None:
    """COMP-007: CompositeVMOf populates children from ChildrenModels() + mapper."""

    class _M:
        def __init__(self, id_: int) -> None:
            self.id = id_

    hub = _hub()
    disp = _dispatcher()
    m1 = _M(1)
    m2 = _M(2)

    def _make_child(m: _M) -> ComponentVMOf[_M]:
        return ComponentVMOfBuilder().name(f"c{m.id}").model(m).services(hub, disp).build()

    comp: CompositeVMOf[_M, ComponentVMOf[_M]] = (
        CompositeVMOfBuilder()
        .name("comp")
        .services(hub, disp)
        .children_models(lambda: [m1, m2])
        .child_model_to_child_view_model(_make_child)
        .build()
    )

    comp.construct()

    assert comp.count == 2
    assert comp[0].model is m1
    assert comp[1].model is m2


# ===========================================================================
# COMP-008 — can_select_component returns false for non-children
# ===========================================================================


@pytest.mark.conformance("COMP-008")
def test_COMP_008_can_select_component_false_for_non_children() -> None:
    """COMP-008: can_select_component(vmB) where vmB is not in composite returns False,
    and select_component(vmB) raises."""
    comp, _ = _build_composite()
    child_a = _build_child("a")
    comp.append(child_a)
    child_a.construct()

    foreign = _build_child("foreign")
    foreign.construct()

    assert comp.can_select_component(foreign) is False

    with pytest.raises((ValueError, TypeError)):
        comp.select_component(foreign)


# ===========================================================================
# COMP-009 — Current setter raises when assigned a non-child
# ===========================================================================


@pytest.mark.conformance("COMP-009")
def test_COMP_009_current_setter_raises_on_non_child() -> None:
    """COMP-009: setting current to a VM not in children raises; current stays None."""
    comp, _ = _build_composite()
    child_a = _build_child("a")
    comp.append(child_a)
    child_a.construct()

    foreign = _build_child("foreign")
    foreign.construct()

    with pytest.raises((ValueError, TypeError)):
        comp.current = foreign

    assert comp.current is None


# ===========================================================================
# COMP-010 — AsyncSelection dispatches Current change via foreground scheduler
# ===========================================================================


@pytest.mark.conformance("COMP-010")
def test_COMP_010_async_selection_dispatches_via_foreground() -> None:
    """COMP-010: with AsyncSelection(True), select_component does NOT change Current
    synchronously; advancing the TestScheduler completes the dispatch."""
    from tests.unit.helpers.test_dispatcher import TestDispatcher

    test_disp = TestDispatcher()
    hub = _hub()
    child_a = _build_child("a", hub=hub, dispatcher=test_disp)

    comp: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("comp")
        .services(hub, test_disp)
        .async_selection(True)
        .children(lambda: ())
        .build()
    )
    child_a.construct()
    comp.append(child_a)

    # Trigger async selection.
    comp.select_component(child_a)

    # Synchronously: current should NOT be set yet (deferred to scheduler).
    assert comp.current is None, "Current should not be set synchronously with AsyncSelection"

    # Advance foreground scheduler.
    test_disp.foreground_scheduler.advance_by(1)

    assert comp.current is child_a, "Current should be set after advancing scheduler"


# ===========================================================================
# COMP-011 — deselect_component raises when vm is not Current
# ===========================================================================


@pytest.mark.conformance("COMP-011")
def test_COMP_011_deselect_component_raises_when_not_current() -> None:
    """COMP-011: deselect_component(vmB) when Current==vmA raises; Current stays vmA."""
    comp, _ = _build_composite()
    child_a = _build_child("a")
    child_b = _build_child("b")
    comp.append(child_a)
    comp.append(child_b)
    child_a.construct()
    child_b.construct()
    comp.current = child_a

    with pytest.raises((ValueError, TypeError)):
        comp.deselect_component(child_b)

    assert comp.current is child_a


# ===========================================================================
# LIFE-013 — dispose on parent disposes every child depth-first
# ===========================================================================


@pytest.mark.conformance("LIFE-013")
def test_LIFE_013_dispose_cascades_depth_first() -> None:
    """LIFE-013: dispose() on root propagates depth-first to all descendants.

    Setup:
      root (CompositeVM)
        ├── child-a (CompositeVM)
        │     ├── gc-a1 (ComponentVM)
        │     └── gc-a2 (ComponentVM)
        └── child-b (CompositeVM)
              ├── gc-b1 (ComponentVM)
              └── gc-b2 (ComponentVM)

    After root.dispose() all nodes must be Disposed.
    The disposal order is depth-first: grandchildren before their parent
    composite, children before root.  We track disposal order via hub
    ConstructionStatusChangedMessage(Disposed) — every node (composites
    included) emits one when it enters Disposed.
    """
    hub = _hub()
    disp = _dispatcher()

    # Track which node names arrive at Disposed, in order.
    disposal_order: list[str] = []
    hub.messages.subscribe(
        lambda m: (
            disposal_order.append(m.sender_name)
            if isinstance(m, ConstructionStatusChangedMessage)
            and m.status == ConstructionStatus.DISPOSED
            else None
        )
    )

    # Create leaf grandchildren.
    gc_a1 = _build_child("gc-a1", hub=hub, dispatcher=disp)
    gc_a2 = _build_child("gc-a2", hub=hub, dispatcher=disp)
    gc_b1 = _build_child("gc-b1", hub=hub, dispatcher=disp)
    gc_b2 = _build_child("gc-b2", hub=hub, dispatcher=disp)

    # Create child composites with pre-populated children.
    child_comp_a: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("child-a")
        .services(hub, disp)
        .children(lambda: [gc_a1, gc_a2])
        .build()
    )
    child_comp_b: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("child-b")
        .services(hub, disp)
        .children(lambda: [gc_b1, gc_b2])
        .build()
    )

    # Create root composite.
    root: CompositeVM[CompositeVM[ComponentVM]] = (  # type: ignore[type-arg]
        CompositeVMBuilder()
        .name("root")
        .services(hub, disp)
        .children(lambda: [child_comp_a, child_comp_b])  # type: ignore[arg-type]
        .build()
    )

    root.construct()

    # Act: dispose root.
    root.dispose()

    # Every node must be Disposed.
    assert gc_a1.status == ConstructionStatus.DISPOSED
    assert gc_a2.status == ConstructionStatus.DISPOSED
    assert gc_b1.status == ConstructionStatus.DISPOSED
    assert gc_b2.status == ConstructionStatus.DISPOSED
    assert child_comp_a.status == ConstructionStatus.DISPOSED
    assert child_comp_b.status == ConstructionStatus.DISPOSED
    assert root.status == ConstructionStatus.DISPOSED

    # Depth-first order: grandchildren before their parent composite,
    # children before root.
    assert disposal_order.index("gc-a1") < disposal_order.index("child-a"), (
        "gc-a1 must be disposed before child-a"
    )
    assert disposal_order.index("gc-a2") < disposal_order.index("child-a"), (
        "gc-a2 must be disposed before child-a"
    )
    assert disposal_order.index("gc-b1") < disposal_order.index("child-b"), (
        "gc-b1 must be disposed before child-b"
    )
    assert disposal_order.index("gc-b2") < disposal_order.index("child-b"), (
        "gc-b2 must be disposed before child-b"
    )
    assert disposal_order.index("child-a") < disposal_order.index("root"), (
        "child-a must be disposed before root"
    )
    assert disposal_order.index("child-b") < disposal_order.index("root"), (
        "child-b must be disposed before root"
    )


# ===========================================================================
# COMP-012 — AutoConstructOnAdd(true) auto-constructs late children (spec v1.1)
# ===========================================================================


@pytest.mark.conformance("COMP-012")
def test_COMP_012_auto_construct_on_add() -> None:
    """COMP-012: child added after Constructed reaches Constructed before the event fires."""
    hub = _hub()
    disp = _dispatcher()

    composite: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("comp")
        .services(hub, disp)
        .auto_construct_on_add(True)
        .children(lambda: ())
        .build()
    )
    composite.construct()

    child = _build_child("late", hub=hub, dispatcher=disp)
    assert child.status == ConstructionStatus.DESTRUCTED

    seen: list[tuple[CollectionChangedEvent, ConstructionStatus]] = []
    composite.on_collection_changed.subscribe(
        lambda e: seen.append((e, child.status))  # type: ignore[arg-type]
    )

    composite.append(child)

    assert child.status == ConstructionStatus.CONSTRUCTED
    assert len(seen) == 1
    evt, status_at_event = seen[0]
    assert evt.action == "add"
    assert status_at_event == ConstructionStatus.CONSTRUCTED


# ===========================================================================
# COMP-013 — BatchUpdate suppresses per-mutation events and emits one Reset
# ===========================================================================


@pytest.mark.conformance("COMP-013")
def test_COMP_013_batch_update_emits_one_reset() -> None:
    """COMP-013: mutations inside a batch produce exactly one Reset at exit."""
    hub = _hub()
    disp = _dispatcher()

    composite: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("comp").services(hub, disp).children(lambda: ()).build()
    )
    composite.construct()

    events: list[CollectionChangedEvent] = []
    composite.on_collection_changed.subscribe(events.append)

    with composite.batch_update():
        composite.append(_build_child("a", hub=hub, dispatcher=disp))
        composite.append(_build_child("b", hub=hub, dispatcher=disp))
        composite.append(_build_child("c", hub=hub, dispatcher=disp))

    assert len(events) == 1, f"Expected one Reset event, got {[e.action for e in events]}"
    assert events[0].action == "reset"
    assert len(composite) == 3


# ===========================================================================
# COMP-025 — current(selector) drives initial-current during construct
# ===========================================================================


@pytest.mark.conformance("COMP-025")
def test_COMP_025_current_selector_drives_initial_selection() -> None:
    """COMP-025: current(selector) runs once during construct, after all children
    reach Constructed and before the composite reaches Constructed. The
    selector's return value becomes current. See spec/06 §3.2 and ADR-0042.
    """
    hub = _hub()
    disp = _dispatcher()
    children = [_build_child(name, hub=hub, dispatcher=disp) for name in ("a", "b", "c")]

    selector_calls = 0

    def selector(xs: object) -> ComponentVM:
        nonlocal selector_calls
        selector_calls += 1
        return list(xs)[1]  # type: ignore[call-overload]

    composite: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("composite")
        .services(hub, disp)
        .children(lambda: children)
        .current(selector)
        .build()
    )

    composite.construct()

    assert composite.current is children[1]
    assert selector_calls == 1, "the selector must run exactly once during construct"

    # A null-returning selector leaves current None and publishes no
    # PropertyChangedMessage('current').
    hub2 = _hub()
    children2 = [_build_child(name, hub=hub2, dispatcher=disp) for name in ("a", "b", "c")]
    prop_msgs = _prop_messages(hub2)
    composite2: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("composite2")
        .services(hub2, disp)
        .children(lambda: children2)
        .current(lambda xs: None)
        .build()
    )
    composite2.construct()

    assert composite2.current is None
    assert [m for m in prop_msgs if m.property_name == "current"] == [], (
        "a null-returning current selector must publish no PropertyChangedMessage('current')"
    )


# ===========================================================================
# COMP-026 — on_current_changed fires after each current transition
# ===========================================================================


@pytest.mark.conformance("COMP-026")
def test_COMP_026_on_current_changed_fires_after_each_change() -> None:
    """COMP-026: on_current_changed(callback) is invoked synchronously after every
    current transition. Receives the new current value (may be None). See
    spec/06 §3.2 and ADR-0042.
    """
    hub = _hub()
    disp = _dispatcher()
    children = [_build_child(name, hub=hub, dispatcher=disp) for name in ("a", "b")]
    observed: list[ComponentVM | None] = []

    composite: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("composite")
        .services(hub, disp)
        .children(lambda: children)
        .on_current_changed(observed.append)
        .build()
    )

    composite.construct()
    composite.select_component(children[1])
    composite.deselect_component(children[1])

    assert observed == [children[1], None]

    # Combined current(first) + on_current_changed: the initial-selector
    # assignment fires the hook exactly once with the first child.
    hub2 = _hub()
    children2 = [_build_child(name, hub=hub2, dispatcher=disp) for name in ("a", "b")]
    observed2: list[ComponentVM | None] = []
    composite2: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("composite2")
        .services(hub2, disp)
        .children(lambda: children2)
        .current(lambda xs: next(iter(xs)))
        .on_current_changed(observed2.append)
        .build()
    )
    composite2.construct()

    assert observed2 == [children2[0]]

    reentrant: CompositeVM[ComponentVM] | None = None
    reentrant_hub = _hub()
    reentrant_child = _build_child("reentrant", hub=reentrant_hub, dispatcher=disp)

    callback_statuses: list[ConstructionStatus] = []

    def dispose_reentrant(selected: ComponentVM | None) -> None:
        assert reentrant is not None
        assert selected is reentrant_child
        callback_statuses.append(selected.status)
        reentrant.dispose()

    reentrant = (
        CompositeVMBuilder()
        .name("reentrant-composite")
        .services(reentrant_hub, disp)
        .children(lambda: [reentrant_child])
        .on_current_changed(dispose_reentrant)
        .build()
    )
    reentrant.construct()

    reentrant.select_component(reentrant_child)

    assert callback_statuses == [ConstructionStatus.CONSTRUCTED]
    assert reentrant.status is ConstructionStatus.DISPOSED


@pytest.mark.conformance("COMP-026")
def test_COMP_026_opposing_current_callbacks_do_not_deadlock() -> None:
    """Current callbacks on two composites cannot retain opposing membership gates."""
    dispatcher = _dispatcher()
    barrier = Barrier(2)
    refs: dict[str, CompositeVM[ComponentVM]] = {}
    first = {"a": True, "b": True}

    hub_a, hub_b = _hub(), _hub()
    child_a = _build_child("a", hub=hub_a, dispatcher=dispatcher)
    child_b = _build_child("b", hub=hub_b, dispatcher=dispatcher)

    def cross(key: str, target: str, child: ComponentVM) -> Callable[[ComponentVM | None], None]:
        def callback(_: ComponentVM | None) -> None:
            if not first[key]:
                return
            first[key] = False
            try:
                barrier.wait(0.1)
            except BrokenBarrierError:
                pass
            target_vm = refs[target]
            if target_vm.current is not child:
                target_vm.select_component(child)

        return callback

    composite_a = (
        CompositeVMBuilder()
        .name("a")
        .services(hub_a, dispatcher)
        .children(lambda: [child_a])
        .on_current_changed(cross("a", "b", child_b))
        .build()
    )
    composite_b = (
        CompositeVMBuilder()
        .name("b")
        .services(hub_b, dispatcher)
        .children(lambda: [child_b])
        .on_current_changed(cross("b", "a", child_a))
        .build()
    )
    refs.update(a=composite_a, b=composite_b)
    composite_a.construct()
    composite_b.construct()

    thread_a = Thread(target=lambda: composite_a.select_component(child_a), daemon=True)
    thread_b = Thread(target=lambda: composite_b.select_component(child_b), daemon=True)
    thread_a.start()
    thread_b.start()
    thread_a.join(2.0)
    thread_b.join(2.0)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert composite_a.current is child_a
    assert composite_b.current is child_b


@pytest.mark.conformance("COMP-026")
def test_COMP_026_collection_and_current_callbacks_do_not_deadlock() -> None:
    """A collection callback cannot wait on a coordinator held by a disposer."""
    script = textwrap.dedent(
        """
        from threading import Event, Thread

        from vmx.components.builders import ComponentVMBuilder
        from vmx.composites.builders import CompositeVMBuilder
        from vmx.services.dispatcher import RxDispatcher
        from vmx.services.message_hub import MessageHub

        dispatcher = RxDispatcher.immediate()

        def child(name):
            return ComponentVMBuilder().name(name).services(MessageHub(), dispatcher).build()

        def composite(name, callback=None):
            builder = CompositeVMBuilder().name(name).services(
                MessageHub(), dispatcher
            ).children(lambda: ())
            if callback is not None:
                builder = builder.on_current_changed(callback)
            return builder.build()

        b_transaction_entered = Event()
        a_callback_entered = Event()
        b = composite("b")

        def on_a_current(_):
            a_callback_entered.set()
            assert b_transaction_entered.wait(1.0)
            b.dispose()

        a_item = child("a-item")
        a_item.construct()
        a = composite("a", on_a_current)
        a.add(a_item)
        a.construct()
        b.construct()
        b_item = child("b-item")
        b_item.construct()

        def on_b_collection(_):
            b_transaction_entered.set()
            b.select_component(b_item)

        subscription = b.on_collection_changed.subscribe(on_b_collection)
        errors = []

        def run(action):
            try:
                action()
            except BaseException as error:
                errors.append(error)

        thread_a = Thread(target=lambda: run(lambda: a.select_component(a_item)))
        thread_a.start()
        assert a_callback_entered.wait(1.0)
        thread_b = Thread(target=lambda: run(lambda: b.add(b_item)))
        thread_b.start()
        thread_a.join()
        thread_b.join()
        subscription.dispose()
        assert errors == []
        assert b.status.name == "DISPOSED"
        assert b_item.status.name == "DISPOSED"
        """
    )

    try:
        subprocess.run([sys.executable, "-c", script], check=True, timeout=3.0)
    except subprocess.TimeoutExpired:
        pytest.fail("current and collection callbacks deadlocked across composites")


def test_auto_construct_rollback_destructs_child_after_destination_disposal() -> None:
    destination_ref: list[CompositeVM[ComponentVM]] = []
    hub, dispatcher = _hub(), _dispatcher()
    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(lambda: destination_ref[0].dispose())
        .build()
    )
    destination = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .auto_construct_on_add(True)
        .children(lambda: ())
        .build()
    )
    destination_ref.append(destination)
    destination.construct()

    with pytest.raises(RuntimeError, match="disposing"):
        destination.append(child)

    assert destination.snapshot() == ()
    assert child.status is ConstructionStatus.DESTRUCTED
    assert destination.status is ConstructionStatus.DISPOSED


@pytest.mark.conformance("COMP-040")
def test_COMP_040_population_disposal_rolls_back_constructed_child() -> None:
    destination_ref: list[CompositeVM[ComponentVM]] = []
    hub, dispatcher = _hub(), _dispatcher()
    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(lambda: destination_ref[0].dispose())
        .build()
    )
    destination = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: (child,))
        .build()
    )
    destination_ref.append(destination)

    with pytest.raises((RuntimeError, StatusTransitionError)):
        destination.construct()

    assert destination.snapshot() == ()
    assert child.status is ConstructionStatus.DESTRUCTED
    assert destination.status is ConstructionStatus.DISPOSED


def test_attachment_error_precedes_deferred_destination_disposal_error() -> None:
    hub, dispatcher = _hub(), _dispatcher()
    destination = _DisposeFailingComposite(
        name="destination",
        hint="",
        hub=hub,
        dispatcher=dispatcher,
        auto_construct_on_add=True,
    )

    def fail_attachment() -> None:
        destination.dispose()
        raise RuntimeError("attachment failure")

    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(fail_attachment)
        .build()
    )
    destination.construct()

    with pytest.raises(RuntimeError, match="attachment failure"):
        destination.append(child)


# ===========================================================================
# COMP-027 — add sets a child's parent; remove clears it
# ===========================================================================


@pytest.mark.conformance("COMP-027")
def test_COMP_027_add_sets_parent_remove_clears_it() -> None:
    """COMP-027: adding a child to a Constructed composite sets the child's internal
    parent back-reference (the child becomes selectable and select() delegates
    through it); removing the child clears it (no longer selectable, select() is a
    no-op). parent is not observable, so the wiring is asserted through the public
    selection surface. See spec/05 §6.1, spec/01 §1.3, and ADR-0050.
    """
    hub = _hub()
    disp = _dispatcher()
    composite, _ = _build_composite(hub=hub, dispatcher=disp)
    composite.construct()

    child = _build_child("c", hub=hub, dispatcher=disp)
    child.construct()

    # No parent yet → not selectable.
    assert not child.can_select()

    # add wires parent → selectable, and select() delegates through it.
    composite.add(child)
    assert child.can_select()
    child.select()
    assert composite.current is child
    assert child.is_current

    # deselect, then remove: remove clears parent → not selectable, select() no-op.
    child.deselect()
    assert composite.current is None
    assert composite.remove(child)
    assert not child.can_select()
    child.select()  # no-op: parent is None
    assert composite.current is None


@pytest.mark.conformance("COMP-038")
def test_COMP_038_add_transfers_child_from_previous_parent() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent, _ = _build_composite("old", hub=hub, dispatcher=dispatcher)
    child = _build_child("c", hub=hub, dispatcher=dispatcher)
    old_parent.add(child)
    old_parent.construct()
    group: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("group").services(hub, dispatcher).children(lambda: ()).build()
    )

    group.add(child)

    assert list(old_parent) == []
    assert list(group) == [child]
    assert child.status is ConstructionStatus.CONSTRUCTED
    assert not old_parent.remove(child)

    next_parent, _ = _build_composite("next", hub=hub, dispatcher=dispatcher)
    next_parent.construct()
    next_parent.add(child)
    assert list(group) == []
    assert child.can_select()
    child.select()
    assert next_parent.current is child


@pytest.mark.conformance("COMP-039")
def test_COMP_039_duplicate_and_cycle_rejection_is_mutation_free() -> None:
    parent, hub = _build_composite()
    child = _build_child(hub=hub)
    parent.add(child)
    events: list[CollectionChangedEvent] = []
    parent.on_collection_changed.subscribe(events.append)

    with pytest.raises(ValueError):
        parent.add(child)

    assert list(parent) == [child]
    assert events == []

    outer, _ = _build_composite("outer", hub=hub)
    inner, _ = _build_composite("inner", hub=hub)
    outer.add(inner)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        inner.add(outer)  # type: ignore[arg-type]
    assert list(outer) == [inner]
    assert list(inner) == []


@pytest.mark.conformance("COMP-039")
def test_COMP_039_membership_uses_identity_when_children_override_equality() -> None:
    child = _build_equal_child("same")
    foreign = _build_equal_child("same")
    comp: CompositeVM[_EqualByNameComponent] = (
        CompositeVMBuilder()
        .name("comp")
        .services(_hub(), _dispatcher())
        .children(lambda: ())
        .build()
    )
    comp.add(child)
    child.construct()

    assert foreign not in comp
    with pytest.raises(ValueError):
        comp.index(foreign)
    assert comp.can_select_component(foreign) is False
    with pytest.raises(ValueError):
        comp.current = foreign
    assert comp.remove(foreign) is False
    assert list(comp) == [child]

    group_child = _build_equal_child("group-same")
    group_foreign = _build_equal_child("group-same")
    group: GroupVM[_EqualByNameComponent] = (
        GroupVMBuilder().name("group").services(_hub(), _dispatcher()).children(lambda: ()).build()
    )
    group.add(group_child)

    assert group_foreign not in group
    assert group.index_of(group_foreign) == -1
    assert group.remove(group_foreign) is False
    assert list(group) == [group_child]


@pytest.mark.conformance("COMP-040")
def test_COMP_040_failed_transfer_restores_parent_index_and_current() -> None:
    hub = _hub()
    dispatcher = _dispatcher()

    def fail_construct() -> None:
        raise RuntimeError("boom")

    child = (
        ComponentVMBuilder()
        .name("failing")
        .services(hub, dispatcher)
        .on_construct(fail_construct)
        .build()
    )
    sibling = _build_child("sibling", hub=hub, dispatcher=dispatcher)
    old_parent, _ = _build_composite("old", hub=hub, dispatcher=dispatcher)
    old_parent.add(sibling)
    old_parent.add(child)
    old_parent.current = child
    destination: GroupVM[ComponentVM] = (
        GroupVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .auto_construct_on_add(True)
        .build()
    )
    destination.construct()
    events: list[str] = []
    old_parent.on_collection_changed.subscribe(lambda _event: events.append("old"))
    destination.on_collection_changed.subscribe(lambda _event: events.append("new"))

    with pytest.raises(RuntimeError, match="boom"):
        destination.add(child)

    assert list(old_parent) == [sibling, child]
    assert old_parent.current is child
    assert child.is_current
    assert child.status is ConstructionStatus.DESTRUCTED
    assert list(destination) == []
    assert events == []

    # A later failure in lazy population rolls back every earlier transfer and
    # leaves the population attempt retryable.
    bulk_destination: GroupVM[ComponentVM]

    def assert_complete_population() -> None:
        assert len(bulk_destination) == 2

    first = (
        ComponentVMBuilder()
        .name("first")
        .services(hub, dispatcher)
        .on_construct(assert_complete_population)
        .build()
    )
    blocker = (
        ComponentVMBuilder()
        .name("bulk-failing")
        .services(hub, dispatcher)
        .on_construct(fail_construct)
        .build()
    )
    bulk_old, _ = _build_composite("bulk-old", hub=hub, dispatcher=dispatcher)
    bulk_old.add(first)
    batch = [first, blocker]
    bulk_destination = (
        GroupVMBuilder()
        .name("bulk-destination")
        .services(hub, dispatcher)
        .children(lambda: tuple(batch))
        .build()
    )
    bulk_events: list[str] = []
    bulk_old.on_collection_changed.subscribe(lambda _event: bulk_events.append("old"))
    bulk_destination.on_collection_changed.subscribe(lambda _event: bulk_events.append("new"))

    with pytest.raises(RuntimeError, match="boom"):
        bulk_destination.construct()

    assert list(bulk_old) == [first]
    assert first.status is ConstructionStatus.DESTRUCTED
    assert list(bulk_destination) == []
    assert bulk_events == []
    batch.clear()
    bulk_destination.construct()
    assert list(bulk_destination) == []


@pytest.mark.conformance("COMP-040")
def test_COMP_040_defers_old_composite_disposal_until_transfer_commits() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent, _ = _build_composite("old", hub=hub, dispatcher=dispatcher)
    destination: GroupVM[ComponentVM] = (
        GroupVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .auto_construct_on_add(True)
        .build()
    )
    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(old_parent.dispose)
        .build()
    )
    old_parent.add(child)
    destination.construct()

    destination.add(child)

    assert old_parent.status is ConstructionStatus.DISPOSED
    assert list(old_parent) == []
    assert list(destination) == [child]
    assert child.status is ConstructionStatus.CONSTRUCTED
    assert child._parent is not None
    assert child._parent.owner is destination


@pytest.mark.conformance("COMP-040")
def test_COMP_040_rolls_back_before_deferred_old_group_disposal() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("old").services(hub, dispatcher).children(lambda: ()).build()
    )
    destination: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .auto_construct_on_add(True)
        .build()
    )

    def dispose_then_fail() -> None:
        old_parent.dispose()
        raise RuntimeError("boom")

    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(dispose_then_fail)
        .build()
    )
    old_parent.add(child)
    destination.construct()

    with pytest.raises(RuntimeError, match="boom"):
        destination.add(child)

    assert old_parent.status is ConstructionStatus.DISPOSED
    assert list(old_parent) == [child]
    assert list(destination) == []
    assert child.status is ConstructionStatus.DISPOSED
    assert child._parent is not None
    assert child._parent.owner is old_parent


@pytest.mark.conformance("COMP-040")
def test_COMP_040_deferred_disposal_failure_follows_committed_transfer_events() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("old").services(hub, dispatcher).children(lambda: ()).build()
    )
    destination: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .auto_construct_on_add(True)
        .build()
    )
    moving = _DisposeFailingComponent(
        name="moving",
        hint="",
        hub=hub,
        dispatcher=dispatcher,
        on_construct=old_parent.dispose,
    )
    failing_sibling = _DisposeFailingComponent(
        name="failing-sibling", hint="", hub=hub, dispatcher=dispatcher
    )
    old_parent.add(moving)
    old_parent.add(failing_sibling)
    destination.construct()
    events: list[str] = []
    old_parent.on_collection_changed.subscribe(lambda _event: events.append("old:remove"))
    destination.on_collection_changed.subscribe(lambda _event: events.append("new:add"))

    with pytest.raises(RuntimeError, match="dispose failure"):
        destination.add(moving)

    assert events == ["old:remove", "new:add"]
    assert old_parent.status is ConstructionStatus.DISPOSED
    assert failing_sibling.status is ConstructionStatus.DISPOSED
    assert list(destination) == [moving]
    assert moving._parent is not None and moving._parent.owner is destination


@pytest.mark.conformance("COMP-040")
def test_COMP_040_attachment_failure_precedes_deferred_disposal_failure() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("old").services(hub, dispatcher).children(lambda: ()).build()
    )
    destination: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .auto_construct_on_add(True)
        .build()
    )

    def dispose_then_fail() -> None:
        old_parent.dispose()
        raise RuntimeError("attachment failure")

    moving = _DisposeFailingComponent(
        name="moving",
        hint="",
        hub=hub,
        dispatcher=dispatcher,
        on_construct=dispose_then_fail,
    )
    old_parent.add(moving)
    destination.construct()

    with pytest.raises(RuntimeError, match="attachment failure"):
        destination.add(moving)

    assert old_parent.status is ConstructionStatus.DISPOSED
    assert moving.status is ConstructionStatus.DISPOSED
    assert list(old_parent) == [moving]
    assert list(destination) == []


@pytest.mark.conformance("COMP-040")
def test_COMP_040_late_disposal_failure_does_not_retry_committed_population() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("old").services(hub, dispatcher).children(lambda: ()).build()
    )
    moving = _DisposeFailingComponent(
        name="moving",
        hint="",
        hub=hub,
        dispatcher=dispatcher,
        on_construct=old_parent.dispose,
    )
    failing_sibling = _DisposeFailingComponent(
        name="failing-sibling", hint="", hub=hub, dispatcher=dispatcher
    )
    old_parent.add(moving)
    old_parent.add(failing_sibling)
    factory_calls = 0

    def children() -> tuple[ComponentVM, ...]:
        nonlocal factory_calls
        factory_calls += 1
        return (moving,)

    destination: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(children)
        .build()
    )
    events: list[str] = []
    old_parent.on_collection_changed.subscribe(lambda _event: events.append("old:remove"))
    destination.on_collection_changed.subscribe(lambda _event: events.append("new:add"))

    with pytest.raises(RuntimeError, match="dispose failure"):
        destination.construct()

    assert events == ["old:remove", "new:add"]
    assert factory_calls == 1
    assert list(destination) == [moving]

    destination.construct()

    assert factory_calls == 1
    assert destination.status is ConstructionStatus.CONSTRUCTED


@pytest.mark.conformance("COMP-040")
def test_COMP_040_concurrent_old_parent_disposal_waits_for_transfer_commit() -> None:
    hook_entered = Event()
    release_hook = Event()
    disposal_started = Event()
    disposal_done = Event()
    errors: list[BaseException] = []
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("old").services(hub, dispatcher).children(lambda: ()).build()
    )
    destination: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .auto_construct_on_add(True)
        .build()
    )

    def block_construct() -> None:
        hook_entered.set()
        assert release_hook.wait(2)

    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_construct(block_construct)
        .build()
    )
    old_parent.add(child)
    destination.construct()

    def transfer() -> None:
        try:
            destination.add(child)
        except BaseException as error:
            errors.append(error)

    def dispose() -> None:
        disposal_started.set()
        old_parent.dispose()
        disposal_done.set()

    transfer_thread = Thread(target=transfer, daemon=True)
    transfer_thread.start()
    assert hook_entered.wait(2)
    disposal_thread = Thread(target=dispose, daemon=True)
    disposal_thread.start()
    assert disposal_started.wait(2)
    assert not disposal_done.wait(0.05)

    release_hook.set()
    transfer_thread.join(2)
    disposal_thread.join(2)
    assert not transfer_thread.is_alive()
    assert not disposal_thread.is_alive()
    assert errors == []
    assert old_parent.status is ConstructionStatus.DISPOSED
    assert list(old_parent) == []
    assert list(destination) == [child]
    assert child.status is ConstructionStatus.CONSTRUCTED


@pytest.mark.conformance("COMP-041")
def test_COMP_041_transfer_publishes_old_remove_before_new_add() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    old_parent, _ = _build_composite("old", hub=hub, dispatcher=dispatcher)
    child = _build_child(hub=hub, dispatcher=dispatcher)
    old_parent.add(child)
    destination: GroupVM[ComponentVM] = (
        GroupVMBuilder().name("destination").services(hub, dispatcher).children(lambda: ()).build()
    )
    observed: list[str] = []

    def record_old(event: CollectionChangedEvent) -> None:
        assert event.action == "remove"
        assert child not in old_parent
        assert child in destination
        observed.append("old:remove")

    def record_new(event: CollectionChangedEvent) -> None:
        assert event.action == "add"
        assert child not in old_parent
        assert child in destination
        observed.append("new:add")

    old_parent.on_collection_changed.subscribe(record_old)
    destination.on_collection_changed.subscribe(record_new)

    destination.add(child)

    assert observed == ["old:remove", "new:add"]

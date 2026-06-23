"""Conformance tests: COMP-001..013 + LIFE-013.

Each test is decorated with ``@pytest.mark.conformance("XXX-NNN")`` so the
coverage checker finds it.

COMP-006 uses TestScheduler (via TestDispatcher) to verify that IsCurrent
changes on the previously-Current child are dispatched on the foreground
scheduler (ObserveOn pattern).
"""

from __future__ import annotations

import pytest

from vmx.collections import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder
from vmx.components.component_vm import ComponentVM, ComponentVMOf
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM, CompositeVMOf
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


# Alias imported by tests/conformance/test_lifecycle.py delegation.
test_LIFE_013_dispose_cascade = test_LIFE_013_dispose_cascades_depth_first  # noqa: N816


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

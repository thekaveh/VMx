"""Unit tests for CompositeVM (non-modeled).

Tests cover:
- collection add/remove/insert/clear with CollectionChangedEvent
- current setter (legal/illegal)
- select_component / deselect_component / can_select_component
- construct/destruct lifecycle orchestration
- dispose cascade
- async_selection dispatch
"""

from __future__ import annotations

import pytest

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CollectionChangedEvent, CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Helpers
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
    disp = dispatcher if dispatcher is not None else _dispatcher()
    vm: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name(name)
        .services(h, disp)
        .async_selection(async_selection)
        .children(lambda: ())
        .build()
    )
    return vm, h


def _build_child(
    name: str = "child",
    hub: object | None = None,
    dispatcher: object | None = None,
) -> ComponentVM:
    h = hub if hub is not None else _hub()
    d = dispatcher if dispatcher is not None else _dispatcher()
    return ComponentVMBuilder().name(name).services(h, d).build()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Collection mutation tests
# ---------------------------------------------------------------------------


def test_add_emits_collection_changed_add() -> None:
    comp, _ = _build_composite()
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    child = _build_child()
    comp.append(child)

    assert len(events) == 1
    assert events[0].action == "add"
    assert child in events[0].new_items
    assert events[0].new_index == 0


def test_remove_emits_collection_changed_remove() -> None:
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


def test_insert_emits_collection_changed_add_at_index() -> None:
    comp, _ = _build_composite()
    child_a = _build_child("a")
    child_b = _build_child("b")
    comp.append(child_a)
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.insert(0, child_b)

    assert len(events) == 1
    assert events[0].action == "add"
    assert events[0].new_index == 0
    assert child_b in events[0].new_items


def test_insert_negative_index_emits_effective_position() -> None:
    """spec/21 §3.2: new_index carries the actual insertion position —
    stdlib insert(-1) lands before the last child, not at raw -1."""
    comp, _ = _build_composite()
    comp.append(_build_child("a"))
    comp.append(_build_child("b"))
    child_c = _build_child("c")
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.insert(-1, child_c)

    assert events[0].new_index == 1
    assert comp[1] is child_c


def test_clear_emits_collection_changed_reset() -> None:
    comp, _ = _build_composite()
    comp.append(_build_child("a"))
    comp.append(_build_child("b"))
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.clear()

    assert len(events) == 1
    assert events[0].action == "reset"
    assert len(comp) == 0


def test_remove_at_removes_correct_child() -> None:
    comp, _ = _build_composite()
    child_a = _build_child("a")
    child_b = _build_child("b")
    comp.append(child_a)
    comp.append(child_b)
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.remove_at(0)

    assert comp[0] is child_b
    assert events[0].action == "remove"
    assert child_a in events[0].old_items


def test_setitem_emits_remove_then_add() -> None:
    comp, _ = _build_composite()
    child_a = _build_child("a")
    child_b = _build_child("b")
    comp.append(child_a)
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp[0] = child_b

    assert len(events) == 2
    assert events[0].action == "remove"
    assert events[1].action == "add"
    assert comp[0] is child_b


# ---------------------------------------------------------------------------
# Current setter tests
# ---------------------------------------------------------------------------


def test_current_default_is_none() -> None:
    comp, _ = _build_composite()
    assert comp.current is None


def test_set_current_to_none_always_legal() -> None:
    comp, _ = _build_composite()
    comp.current = None  # no-op, should not raise


def test_set_current_to_non_child_raises() -> None:
    comp, _ = _build_composite()
    foreign = _build_child("foreign")
    with pytest.raises((ValueError, TypeError)):
        comp.current = foreign


def test_set_current_to_child_works() -> None:
    hub = _hub()
    disp = _dispatcher()
    comp, _ = _build_composite(hub=hub, dispatcher=disp)
    # Child must share the same hub so its is_current messages are visible.
    child = _build_child(hub=hub, dispatcher=disp)
    comp.append(child)
    child.construct()

    prop_msgs: list[PropertyChangedMessage] = []
    hub.messages.subscribe(
        lambda m: prop_msgs.append(m) if isinstance(m, PropertyChangedMessage) else None
    )

    comp.current = child

    assert comp.current is child
    assert child.is_current is True

    current_msgs = [m for m in prop_msgs if m.property_name == "current"]
    assert len(current_msgs) == 1

    is_current_msgs = [
        m for m in prop_msgs if m.property_name == "is_current" and m.sender is child
    ]
    assert len(is_current_msgs) == 1


def test_set_current_updates_previous_child_is_current() -> None:
    comp, _ = _build_composite()
    child_a = _build_child("a")
    child_b = _build_child("b")
    comp.append(child_a)
    comp.append(child_b)
    child_a.construct()
    child_b.construct()

    comp.current = child_a
    assert child_a.is_current is True

    comp.current = child_b
    assert child_a.is_current is False
    assert child_b.is_current is True


def test_set_current_to_none_clears_selection() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    child.construct()
    comp.current = child
    assert comp.current is child

    comp.current = None
    assert comp.current is None
    assert child.is_current is False


# ---------------------------------------------------------------------------
# select_component / deselect_component / can_select_component
# ---------------------------------------------------------------------------


def test_select_component_sets_current() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    child.construct()

    comp.select_component(child)
    assert comp.current is child


def test_select_component_raises_if_not_constructed() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    # child is Destructed, not Constructed

    with pytest.raises((ValueError, TypeError)):
        comp.select_component(child)


def test_select_component_raises_for_non_child() -> None:
    comp, _ = _build_composite()
    foreign = _build_child("foreign")
    foreign.construct()
    with pytest.raises((ValueError, TypeError)):
        comp.select_component(foreign)


def test_deselect_component_clears_current() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    child.construct()
    comp.current = child

    comp.deselect_component(child)
    assert comp.current is None


def test_deselect_component_raises_if_not_current() -> None:
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


def test_can_select_component_returns_false_for_non_child() -> None:
    comp, _ = _build_composite()
    foreign = _build_child("foreign")
    foreign.construct()
    assert comp.can_select_component(foreign) is False


def test_can_select_component_returns_false_when_not_constructed() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    # child is Destructed
    assert comp.can_select_component(child) is False


def test_can_select_component_returns_true_for_constructed_child() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    child.construct()
    assert comp.can_select_component(child) is True


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


def test_construct_constructs_all_children() -> None:
    """Composite.construct() calls construct() on each child."""
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

    assert comp.status == ConstructionStatus.CONSTRUCTED
    assert child_a.status == ConstructionStatus.CONSTRUCTED
    assert child_b.status == ConstructionStatus.CONSTRUCTED


def test_factory_children_emit_collection_changed_events() -> None:
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
    events: list[object] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.construct()

    assert [e.action for e in events] == ["add", "add"]  # type: ignore[attr-defined]
    assert events[0].new_items == (child_a,)  # type: ignore[attr-defined]
    assert events[1].new_items == (child_b,)  # type: ignore[attr-defined]


def test_destruct_destructs_children_and_clears_current() -> None:
    hub = _hub()
    disp = _dispatcher()
    child = _build_child("a", hub=hub, dispatcher=disp)

    comp: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("comp").services(hub, disp).children(lambda: [child]).build()
    )
    comp.construct()
    comp.current = child

    comp.destruct()

    assert comp.status == ConstructionStatus.DESTRUCTED
    assert comp.current is None
    assert child.status == ConstructionStatus.DESTRUCTED


def test_dispose_cascade() -> None:
    """dispose() on parent disposes all children depth-first."""
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
    comp.dispose()

    assert comp.status == ConstructionStatus.DISPOSED
    assert child_a.status == ConstructionStatus.DISPOSED
    assert child_b.status == ConstructionStatus.DISPOSED


def test_remove_current_child_clears_current() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    child.construct()
    comp.current = child

    comp.remove(child)
    assert comp.current is None


def test_setitem_replacing_current_clears_current() -> None:
    comp, _ = _build_composite()
    old_child = _build_child(name="old")
    new_child = _build_child(name="new")
    comp.append(old_child)
    old_child.construct()
    comp.current = old_child

    comp[0] = new_child

    assert comp.current is None, "current must be cleared when the slot holding it is replaced"
    assert comp[0] is new_child
    assert old_child._parent is None
    assert new_child._parent is comp


def test_setitem_replacing_non_current_leaves_current_intact() -> None:
    comp, _ = _build_composite()
    other = _build_child(name="other")
    sticky = _build_child(name="sticky")
    replacement = _build_child(name="replacement")
    comp.append(other)
    comp.append(sticky)
    sticky.construct()
    comp.current = sticky

    comp[0] = replacement  # replace `other`, not `sticky`

    assert comp.current is sticky, "current must survive when a different slot is replaced"


# ---------------------------------------------------------------------------
# Parent reference
# ---------------------------------------------------------------------------


def test_add_sets_child_parent() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    assert child._parent is comp


def test_remove_clears_child_parent() -> None:
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    comp.remove(child)
    assert child._parent is None


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------


def test_builder_name_returns_new_instance() -> None:
    b1 = CompositeVMBuilder()
    b2 = b1.name("x")
    assert b1 is not b2
    assert b1._name is None
    assert b2._name == "x"


def test_builder_missing_name_raises() -> None:
    from vmx.builders.exceptions import BuilderValidationError

    hub = _hub()
    disp = _dispatcher()
    with pytest.raises(BuilderValidationError):
        CompositeVMBuilder().services(hub, disp).build()


def test_builder_missing_hub_raises() -> None:
    from vmx.builders.exceptions import BuilderValidationError

    with pytest.raises(BuilderValidationError):
        CompositeVMBuilder().name("x").build()


def test_builder_missing_children_raises() -> None:
    """Per spec/10-builders.md §3 + ADR-0035: non-modeled CompositeVM<VM>
    requires a ``children(lambda: ...)`` factory. For an empty composite,
    pass ``children(lambda: ())`` explicitly.
    """
    from vmx.builders.exceptions import BuilderValidationError

    hub = _hub()
    disp = _dispatcher()
    with pytest.raises(BuilderValidationError) as exc_info:
        CompositeVMBuilder().name("x").services(hub, disp).build()
    assert exc_info.value.missing_field == "children"


def test_clear_resets_current_child_state() -> None:
    """clear() must route through _set_current so the old current child's
    is_current flag is dropped (parity with C# Clear / _remove_at)."""
    comp, _ = _build_composite()
    child = _build_child()
    comp.append(child)
    child.construct()
    comp.current = child
    assert child.is_current is True

    comp.clear()

    assert comp.current is None
    assert child.is_current is False

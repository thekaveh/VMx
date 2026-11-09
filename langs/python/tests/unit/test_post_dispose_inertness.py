"""Members documented as inert after dispose stay inert (disposal contract)."""

from __future__ import annotations

import pytest
from reactivex.subject import BehaviorSubject

from vmx import ComponentVM, CompositeVM, MessageHub, RxDispatcher
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.messages import Message
from vmx.properties import from_sources


def test_a_disposed_child_does_not_change_its_parents_selection() -> None:
    hub: MessageHub[Message] = MessageHub()
    kids = [
        ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build()
        for name in ("a", "b")
    ]
    parent = (
        CompositeVM[ComponentVM]
        .builder()
        .name("p")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: kids)
        .build()
    )
    parent.construct()
    parent.select_component(kids[0])
    kids[0].dispose()
    kids[1].dispose()

    assert kids[0].can_deselect() is False
    kids[0].deselect()
    kids[1].select()

    assert parent.current is kids[0]


def test_a_disposed_derived_property_rejects_writes() -> None:
    writes: list[int] = []
    source: BehaviorSubject[int] = BehaviorSubject(1)
    prop = from_sources(
        source,
        transform=lambda value: value,
        can_set=lambda _: True,
        set_action=writes.append,
    )
    prop.dispose()

    assert prop.can_set(7) is False
    with pytest.raises(ValueError, match="can_set"):
        prop.set_value(7)
    assert writes == []


def _disposed_composite() -> tuple[CompositeVM[ComponentVM], ComponentVM, ComponentVM]:
    hub: MessageHub[Message] = MessageHub()
    kids = [
        ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build()
        for name in ("a", "b")
    ]
    composite = (
        CompositeVM[ComponentVM]
        .builder()
        .name("p")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: kids)
        .build()
    )
    composite.construct()
    composite.current = kids[0]
    composite.dispose()
    return composite, kids[0], kids[1]


def _extra() -> ComponentVM:
    return ComponentVM.builder().name("x").services(MessageHub(), RxDispatcher.immediate()).build()


def test_a_disposed_composite_refuses_membership_and_selection_changes() -> None:
    # Disposal contract, Python exception: membership changes and a selection
    # other than the current child raise RuntimeError (#1319).
    composite, _, _ = _disposed_composite()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.add(_extra())

    composite, _, b = _disposed_composite()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.remove(b)

    composite, _, _ = _disposed_composite()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.clear()
    assert len(composite) == 2

    composite, a, b = _disposed_composite()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.current = b
    assert composite.current is a

    composite, a, _ = _disposed_composite()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.current = None
    assert composite.current is a

    composite, a, _ = _disposed_composite()
    composite.current = a
    assert composite.current is a


def test_a_disposed_group_refuses_membership_changes() -> None:
    hub: MessageHub[Message] = MessageHub()
    a = ComponentVM.builder().name("a").services(hub, RxDispatcher.immediate()).build()
    group: GroupVM[ComponentVM] = (
        GroupVMBuilder[ComponentVM]()
        .name("g")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: [a])
        .build()
    )
    group.construct()
    group.dispose()

    with pytest.raises(RuntimeError, match="disposing"):
        group.add(_extra())
    with pytest.raises(RuntimeError, match="disposing"):
        group.remove(a)
    with pytest.raises(RuntimeError, match="disposing"):
        group.clear()
    assert len(group) == 1


def test_a_disposed_composite_refuses_index_and_move_changes() -> None:
    composite, a, b = _disposed_composite()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.insert(0, _extra())
    with pytest.raises(RuntimeError, match="disposing"):
        composite.remove_at(1)
    with pytest.raises(RuntimeError, match="disposing"):
        composite[1] = _extra()
    with pytest.raises(RuntimeError, match="disposing"):
        composite.move(0, 1)
    assert list(composite) == [a, b]
    assert composite.current is a


def test_a_disposed_group_refuses_index_and_move_changes() -> None:
    hub: MessageHub[Message] = MessageHub()
    a = ComponentVM.builder().name("a").services(hub, RxDispatcher.immediate()).build()
    b = ComponentVM.builder().name("b").services(hub, RxDispatcher.immediate()).build()
    group: GroupVM[ComponentVM] = (
        GroupVMBuilder[ComponentVM]()
        .name("g")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: [a, b])
        .build()
    )
    group.construct()
    group.dispose()

    with pytest.raises(RuntimeError, match="disposing"):
        group.insert(0, _extra())
    with pytest.raises(RuntimeError, match="disposing"):
        group.remove_at(1)
    with pytest.raises(RuntimeError, match="disposing"):
        group[1] = _extra()
    with pytest.raises(RuntimeError, match="disposing"):
        group.move(0, 1)
    assert list(group) == [a, b]

from __future__ import annotations

from typing import cast

import pytest

from vmx.collections import (
    CollectionChangedEvent,
    SelectableVmCollectionProto,
    VmCollectionProto,
)
from vmx.components import ComponentVM
from vmx.composites import CompositeVM
from vmx.groups import GroupVM, GroupVMBuilder
from vmx.lifecycle import ConstructionStatus
from vmx.services import NULL_DISPATCHER, NULL_MESSAGE_HUB


def child(name: str, *, on_construct: object = None) -> ComponentVM:
    builder = ComponentVM.builder().name(name).services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
    if callable(on_construct):
        builder = builder.on_construct(on_construct)
    return builder.build()


def composite(*children: ComponentVM, auto_construct: bool = False) -> CompositeVM[ComponentVM]:
    return (
        CompositeVM.builder()
        .name("composite")
        .services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
        .children(lambda: children)
        .auto_construct_on_add(auto_construct)
        .build()
    )


def group(*children: ComponentVM) -> GroupVM[ComponentVM]:
    return (
        GroupVMBuilder()
        .name("group")
        .services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
        .children(lambda: children)
        .build()
    )


@pytest.mark.conformance("COL-032")
def test_COL_032_shared_contract_separates_selection() -> None:
    comp = composite()
    grp = group()
    collection = cast(VmCollectionProto[ComponentVM], comp)

    assert isinstance(comp, VmCollectionProto)
    assert isinstance(grp, VmCollectionProto)
    assert isinstance(comp, SelectableVmCollectionProto)
    assert not isinstance(grp, SelectableVmCollectionProto)
    assert collection.count == 0


@pytest.mark.conformance("COL-033")
def test_COL_033_forward_move_emits_one_move_event() -> None:
    a, b, c = child("a"), child("b"), child("c")
    comp = composite(a, b, c)
    comp.construct()
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    comp.move(0, 2)

    assert list(comp) == [b, c, a]
    assert len(events) == 1
    assert events[0].action == "move"
    assert events[0].old_items == (a,)
    assert events[0].new_items == (a,)
    assert (events[0].old_index, events[0].new_index) == (0, 2)


@pytest.mark.conformance("COL-034")
def test_COL_034_backward_move_works_for_group() -> None:
    a, b, c = child("a"), child("b"), child("c")
    grp = group(a, b, c)
    grp.construct()
    events: list[CollectionChangedEvent] = []
    grp.on_collection_changed.subscribe(events.append)

    grp.move(2, 0)

    assert list(grp) == [c, a, b]
    assert [(e.action, e.old_index, e.new_index) for e in events] == [("move", 2, 0)]


@pytest.mark.conformance("COL-035")
def test_COL_035_same_index_is_a_true_no_op() -> None:
    a, b, c = child("a"), child("b"), child("c")
    comp = composite(a, b, c)
    comp.construct()
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    with comp.batch_update():
        comp.move(1, 1)

    assert list(comp) == [a, b, c]
    assert events == []


@pytest.mark.conformance("COL-036")
def test_COL_036_invalid_bounds_are_atomic() -> None:
    a, b, c = child("a"), child("b"), child("c")
    comp = composite(a, b, c)
    comp.construct()
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    with pytest.raises(IndexError):
        comp.move(-1, 0)
    with pytest.raises(IndexError):
        comp.move(0, 3)

    assert list(comp) == [a, b, c]
    assert events == []


@pytest.mark.conformance("COL-037")
def test_COL_037_move_preserves_identity_parent_lifecycle_and_current() -> None:
    a, b, c = child("a"), child("b"), child("c")
    comp = composite(a, b, c)
    comp.construct()
    comp.current = a

    comp.move(0, 2)

    assert comp[2] is a
    assert comp.current is a
    assert a.is_current
    assert a.can_deselect()
    assert a.status is ConstructionStatus.CONSTRUCTED


@pytest.mark.conformance("COL-038")
def test_COL_038_batched_move_collapses_to_reset() -> None:
    comp = composite(child("a"), child("b"), child("c"))
    comp.construct()
    events: list[CollectionChangedEvent] = []
    comp.on_collection_changed.subscribe(events.append)

    with comp.batch_update():
        comp.move(0, 2)

    assert [event.action for event in events] == ["reset"]


@pytest.mark.conformance("COL-039")
def test_COL_039_move_does_not_reconstruct_auto_constructed_child() -> None:
    constructs = 0

    def record_construct() -> None:
        nonlocal constructs
        constructs += 1

    comp = composite(auto_construct=True)
    comp.construct()
    moved = child("moved", on_construct=record_construct)
    comp.add(moved)
    comp.add(child("other"))

    comp.move(0, 1)

    assert comp[1] is moved
    assert constructs == 1

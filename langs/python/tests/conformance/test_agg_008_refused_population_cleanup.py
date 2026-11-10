"""Conformance tests: AGG-008.

Spec: spec/08-aggregate-vm.md §2 and §4, ADR-0224.

AGG-008 — A refused fixed-slot population disposes its unowned candidates
"""

from __future__ import annotations

import pytest

from vmx.aggregates.builders import AggregateVM2Builder
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

HUB: MessageHub[object] = MessageHub()
DISPATCHER = RxDispatcher.immediate()


def _leaf(name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(HUB, DISPATCHER).build()


def _owned(name: str) -> tuple[ComponentVM, CompositeVM[ComponentVM]]:
    component = _leaf(name)
    owner: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("owner")
        .services(HUB, DISPATCHER)
        .children(lambda: [component])
        .build()
    )
    owner.construct()
    assert component.status is ConstructionStatus.CONSTRUCTED
    return component, owner


def _assert_owned_by(component: ComponentVM, owner: CompositeVM[ComponentVM]) -> None:
    assert component.status is ConstructionStatus.CONSTRUCTED
    assert component._parent is not None
    assert component._parent.owner is owner
    assert owner.snapshot() == (component,)


@pytest.mark.conformance("AGG-008")
def test_refused_construct_disposes_the_unowned_candidates() -> None:
    fresh = _leaf("fresh")
    borrowed, owner = _owned("borrowed")
    aggregate = (
        AggregateVM2Builder()
        .name("aggregate")
        .services(HUB, DISPATCHER)
        .component_1(lambda: fresh)
        .component_2(lambda: borrowed)
        .build()
    )

    with pytest.raises(ValueError, match="already has a parent"):
        aggregate.construct()

    assert fresh.status is ConstructionStatus.DISPOSED
    _assert_owned_by(borrowed, owner)
    assert aggregate.component_1 is None
    assert aggregate.component_2 is None


@pytest.mark.conformance("AGG-008")
def test_refused_reconstruct_disposes_the_fresh_candidates_and_keeps_the_old_slots() -> None:
    first = _leaf("first")
    second = _leaf("second")
    replacement = _leaf("replacement")
    borrowed, owner = _owned("borrowed")
    calls = [0, 0]

    def factory1() -> ComponentVM:
        calls[0] += 1
        return first if calls[0] == 1 else replacement

    def factory2() -> ComponentVM:
        calls[1] += 1
        return second if calls[1] == 1 else borrowed

    aggregate = (
        AggregateVM2Builder()
        .name("aggregate")
        .services(HUB, DISPATCHER)
        .component_1(factory1)
        .component_2(factory2)
        .build()
    )
    aggregate.construct()

    with pytest.raises(ValueError, match="already has a parent"):
        aggregate.reconstruct()

    assert aggregate.component_1 is first
    assert aggregate.component_2 is second
    for old in (first, second):
        assert old._parent is not None
        assert old._parent.owner is aggregate
        assert old.status is ConstructionStatus.DESTRUCTED
    assert replacement.status is ConstructionStatus.DISPOSED
    assert replacement._parent is None
    _assert_owned_by(borrowed, owner)

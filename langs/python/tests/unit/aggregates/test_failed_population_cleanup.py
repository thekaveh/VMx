"""A population that fails before its commit disposes its unowned candidates (#1324).

Covers aggregate factories and preflight on ``construct()`` and
``reconstruct()``, ``CompositeVMOf`` projectors, and the first recompute of
``FilteredCompositeVM`` and ``ScoredFilteredCompositeVM``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from vmx.aggregates.builders import (
    AggregateVM1Builder,
    AggregateVM2Builder,
    AggregateVM3Builder,
    AggregateVM4Builder,
    AggregateVM5Builder,
    AggregateVM6Builder,
)
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.composites.filtered_composite_vm import FilteredCompositeVM
from vmx.composites.scored_filtered_composite_vm import ScoredFilteredCompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

HUB: MessageHub[object] = MessageHub()
DISPATCHER = RxDispatcher.immediate()

BUILDERS: dict[int, Callable[[], Any]] = {
    2: AggregateVM2Builder,
    3: AggregateVM3Builder,
    4: AggregateVM4Builder,
    5: AggregateVM5Builder,
    6: AggregateVM6Builder,
}


class FactoryFailureError(Exception):
    pass


def _leaf(name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(HUB, DISPATCHER).build()


def _aggregate(arity: int, slot: Callable[[int], ComponentVM]) -> Any:
    builder = BUILDERS[arity]().name("agg").services(HUB, DISPATCHER)
    for index in range(1, arity + 1):
        builder = getattr(builder, f"component_{index}")(lambda index=index: slot(index))
    return builder.build()


def _slots(aggregate: Any, arity: int) -> list[Any]:
    return [getattr(aggregate, f"component_{index}") for index in range(1, arity + 1)]


ARITIES = [2, 3, 4, 5, 6]


@pytest.mark.parametrize("arity", ARITIES)
def test_throwing_last_factory_on_construct_disposes_earlier_candidates(arity: int) -> None:
    built: list[ComponentVM] = []

    def slot(index: int) -> ComponentVM:
        if index == arity:
            raise FactoryFailureError
        leaf = _leaf(f"s{index}")
        built.append(leaf)
        return leaf

    aggregate = _aggregate(arity, slot)

    with pytest.raises(FactoryFailureError):
        aggregate.construct()

    assert len(built) == arity - 1
    assert all(candidate.status is ConstructionStatus.DISPOSED for candidate in built)
    assert _slots(aggregate, arity) == [None] * arity


@pytest.mark.parametrize("arity", ARITIES)
def test_owned_last_candidate_disposes_earlier_candidates_and_keeps_the_owned_one(
    arity: int,
) -> None:
    owner = (
        AggregateVM1Builder()
        .name("owner")
        .services(HUB, DISPATCHER)
        .component_1(lambda: _leaf("owned"))
        .build()
    )
    owner.construct()
    owned = owner.component_1
    assert owned is not None
    built: list[ComponentVM] = []

    def slot(index: int) -> ComponentVM:
        if index == arity:
            return owned
        leaf = _leaf(f"s{index}")
        built.append(leaf)
        return leaf

    aggregate = _aggregate(arity, slot)

    with pytest.raises(ValueError, match="already has a parent"):
        aggregate.construct()

    assert all(candidate.status is ConstructionStatus.DISPOSED for candidate in built)
    assert owned.status is ConstructionStatus.CONSTRUCTED
    assert owned._parent is not None
    assert owned._parent.owner is owner
    assert _slots(aggregate, arity) == [None] * arity


@pytest.mark.parametrize("arity", ARITIES)
def test_throwing_factory_on_reconstruct_keeps_old_slots_and_disposes_fresh_candidates(
    arity: int,
) -> None:
    failing = False
    fresh: list[ComponentVM] = []

    def slot(index: int) -> ComponentVM:
        if failing and index == arity:
            raise FactoryFailureError
        leaf = _leaf(f"s{index}")
        if failing:
            fresh.append(leaf)
        return leaf

    aggregate = _aggregate(arity, slot)
    aggregate.construct()
    old = _slots(aggregate, arity)

    failing = True
    with pytest.raises(FactoryFailureError):
        aggregate.reconstruct()

    assert _slots(aggregate, arity) == old
    assert all(child._parent.owner is aggregate for child in old)
    assert len(fresh) == arity - 1
    assert all(candidate.status is ConstructionStatus.DISPOSED for candidate in fresh)


def test_throwing_projector_disposes_earlier_children_and_leaves_the_composite_empty() -> None:
    projected: list[ComponentVM] = []

    def project(model: str) -> ComponentVM:
        if model == "b":
            raise FactoryFailureError
        leaf = _leaf(model)
        projected.append(leaf)
        return leaf

    composite = (
        CompositeVMOfBuilder[str, ComponentVM]()
        .name("c")
        .services(HUB, DISPATCHER)
        .children_models(lambda: ["a", "b"])
        .child_model_to_child_view_model(project)
        .build()
    )

    with pytest.raises(FactoryFailureError):
        composite.construct()

    assert len(projected) == 1
    assert projected[0].status is ConstructionStatus.DISPOSED
    assert len(composite) == 0


def _source() -> CompositeVM[ComponentVM]:
    source: CompositeVM[ComponentVM] = (
        CompositeVM.builder().name("source").services(HUB, DISPATCHER).children(lambda: []).build()
    )
    source.add(_leaf("a"))
    return source


def test_throwing_filter_predicate_detaches_from_the_source() -> None:
    source = _source()
    calls: list[ComponentVM] = []

    def predicate(item: ComponentVM) -> bool:
        calls.append(item)
        raise FactoryFailureError

    with pytest.raises(FactoryFailureError):
        FilteredCompositeVM(source, predicate=predicate)

    calls.clear()
    source.add(_leaf("b"))
    assert calls == []


def test_throwing_scorer_detaches_from_the_source() -> None:
    source = _source()
    calls: list[ComponentVM] = []

    def scorer(item: ComponentVM) -> float:
        calls.append(item)
        raise FactoryFailureError

    with pytest.raises(FactoryFailureError):
        ScoredFilteredCompositeVM(source, scorer=scorer)

    calls.clear()
    source.add(_leaf("b"))
    assert calls == []

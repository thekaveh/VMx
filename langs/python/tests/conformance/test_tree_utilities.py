"""Conformance tests: UTIL-001..003 (spec v1.1 — Tree utilities)."""

from __future__ import annotations

import pytest

from vmx.aggregates.aggregate_vm import AggregateVM3, AggregateVM6
from vmx.aggregates.builders import AggregateVMBuilder3, AggregateVMBuilder6
from vmx.components.base import _ComponentVMBase
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.components.protocols import ComponentVMProto, ViewModelType
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub
from vmx.tree import find, walk


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _leaf(name: str, hub: MessageHub[object], disp: RxDispatcher) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, disp).build()


@pytest.mark.conformance("UTIL-001")
def test_UTIL_001_walk_yields_root_then_descendants_in_dfs_pre_order() -> None:
    """UTIL-001: walk yields [root, a, b, b1, b2] for a nested composite tree."""
    h = _hub()
    d = _dispatcher()

    a = _leaf("a", h, d)
    b1 = _leaf("b1", h, d)
    b2 = _leaf("b2", h, d)
    b: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("b").services(h, d).children(lambda: [b1, b2]).build()
    )
    root: CompositeVM[ComponentVM] = (  # type: ignore[type-arg]
        CompositeVMBuilder().name("root").services(h, d).children(lambda: [a, b]).build()  # type: ignore[arg-type]
    )
    root.construct()

    names = [vm.name for vm in walk(root)]
    assert names == ["root", "a", "b", "b1", "b2"]


@pytest.mark.conformance("UTIL-002")
def test_UTIL_002_walk_skips_empty_aggregate_slots() -> None:
    """UTIL-002: empty Component slots in an aggregate are skipped.

    Builders require every component factory, so all slots are populated at
    construct time. To exercise the empty-slot path, we dispose the aggregate
    (which sets every component_N to None) and assert walk yields only the
    aggregate itself.
    """
    h = _hub()
    d = _dispatcher()

    a = _leaf("a", h, d)
    b = _leaf("b", h, d)
    c = _leaf("c", h, d)
    agg: AggregateVM3[ComponentVM, ComponentVM, ComponentVM] = (
        AggregateVMBuilder3()
        .name("agg")
        .services(h, d)
        .component_1(lambda: a)
        .component_2(lambda: b)
        .component_3(lambda: c)
        .build()
    )
    agg.construct()
    assert [vm.name for vm in walk(agg)] == ["agg", "a", "b", "c"]

    agg.destruct()
    agg._component2 = None
    names_after = [vm.name for vm in walk(agg)]
    assert names_after == ["agg", "a", "c"]


@pytest.mark.conformance("UTIL-002")
def test_UTIL_002_walk_visits_component_6_on_aggregate_vm6() -> None:
    """UTIL-002: AggregateVM6's sixth slot is reachable by walk()."""
    h = _hub()
    d = _dispatcher()
    leaves = [_leaf(name, h, d) for name in ("a", "b", "c", "d", "e", "f")]
    agg: AggregateVM6[
        ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM
    ] = (
        AggregateVMBuilder6()
        .name("agg6")
        .services(h, d)
        .component_1(lambda: leaves[0])
        .component_2(lambda: leaves[1])
        .component_3(lambda: leaves[2])
        .component_4(lambda: leaves[3])
        .component_5(lambda: leaves[4])
        .component_6(lambda: leaves[5])
        .build()
    )
    agg.construct()
    assert [vm.name for vm in walk(agg)] == ["agg6", "a", "b", "c", "d", "e", "f"]


@pytest.mark.conformance("UTIL-002")
def test_UTIL_002_walk_descends_via_typed_components_accessor_beyond_arity_6() -> None:
    """VMX-137: walk descends into aggregate slots via the typed ``components()``
    accessor, not a ``range(1, 7)`` ``component_{i}`` probe — so an aggregate
    with MORE than six slots (a future AggregateVM7+) is traversed in full. The
    old probe would have silently dropped slot 7 and beyond with no test
    failure."""
    h = _hub()
    d = _dispatcher()
    children = [_leaf(f"c{i}", h, d) for i in range(1, 8)]  # seven slots

    class _Arity7Aggregate(_ComponentVMBase):
        @property
        def type(self) -> ViewModelType:
            return ViewModelType.AGGREGATE

        def components(self) -> list[ComponentVMProto]:
            return list(children)

    agg = _Arity7Aggregate(name="agg7", hint="", hub=h, dispatcher=d)
    assert [vm.name for vm in walk(agg)] == [
        "agg7",
        "c1",
        "c2",
        "c3",
        "c4",
        "c5",
        "c6",
        "c7",
    ]


@pytest.mark.conformance("UTIL-003")
def test_UTIL_003_find_returns_first_match_and_short_circuits() -> None:
    """UTIL-003: find returns the first matching node; predicate is not invoked after the match."""
    h = _hub()
    d = _dispatcher()

    a = _leaf("a", h, d)
    b1 = _leaf("b1", h, d)
    b2 = _leaf("b2", h, d)
    b: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("b").services(h, d).children(lambda: [b1, b2]).build()
    )
    root: CompositeVM[ComponentVM] = (  # type: ignore[type-arg]
        CompositeVMBuilder().name("root").services(h, d).children(lambda: [a, b]).build()  # type: ignore[arg-type]
    )
    root.construct()

    visited: list[str] = []

    def predicate(vm: object) -> bool:
        visited.append(vm.name)  # type: ignore[attr-defined]
        return vm.name == "b1"  # type: ignore[attr-defined,no-any-return]

    result = find(root, predicate)
    assert result is b1
    assert visited == ["root", "a", "b", "b1"]

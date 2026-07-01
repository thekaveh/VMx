"""Conformance tests: COMP-028..037 — filtered and scored composite views."""

from __future__ import annotations

import pytest

from vmx.components.component_vm import ComponentVM
from vmx.composites.composite_vm import CompositeVM
from vmx.composites.filtered_composite_vm import FilteredCompositeVM, FilteredCursorPolicy
from vmx.composites.scored_filtered_composite_vm import ScoredFilteredCompositeVM
from vmx.services.null_dispatcher import NULL_DISPATCHER
from vmx.services.null_message_hub import NULL_MESSAGE_HUB


def child(name: str) -> ComponentVM:
    return ComponentVM.builder().name(name).with_null_services().build()


def source(*names: str) -> CompositeVM[ComponentVM]:
    vm: CompositeVM[ComponentVM] = (
        CompositeVM.builder()
        .name("source")
        .services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
        .children(lambda: [])
        .build()
    )
    for name in names:
        vm.add(child(name))
    return vm


@pytest.mark.conformance("COMP-028")
def test_COMP_028_filtered_visible_projection() -> None:
    sut = FilteredCompositeVM(source("alpha", "beta"), predicate=lambda vm: "a" in vm.name)
    assert [vm.name for vm in sut.visible] == ["alpha", "beta"]


@pytest.mark.conformance("COMP-029")
def test_COMP_029_visible_count() -> None:
    sut = FilteredCompositeVM(source("alpha", "bee"), predicate=lambda vm: "a" in vm.name)
    assert sut.visible_count == 1


@pytest.mark.conformance("COMP-030")
def test_COMP_030_current_maps_to_visible_domain() -> None:
    src = source("alpha", "bee")
    sut = FilteredCompositeVM(src, predicate=lambda vm: "a" in vm.name)
    sut.current = sut.visible[0]
    assert sut.current is src[0]


@pytest.mark.conformance("COMP-031")
def test_COMP_031_predicate_change_recomputes_projection() -> None:
    sut = FilteredCompositeVM(source("alpha", "bee"), predicate=lambda vm: "a" in vm.name)
    sut.set_predicate(lambda vm: "e" in vm.name)
    assert [vm.name for vm in sut.visible] == ["bee"]


@pytest.mark.conformance("COMP-032")
def test_COMP_032_source_mutation_reconciles_projection() -> None:
    src = source("alpha")
    sut = FilteredCompositeVM(src, predicate=lambda vm: "z" in vm.name)
    src.add(child("zulu"))
    assert [vm.name for vm in sut.visible] == ["zulu"]


@pytest.mark.conformance("COMP-033")
def test_COMP_033_cursor_policies() -> None:
    src = source("alpha", "bee")
    snap = FilteredCompositeVM(src, predicate=lambda vm: True)
    snap.current = src[1]
    snap.set_predicate(lambda vm: vm.name == "alpha")
    assert snap.current is src[0]

    clear = FilteredCompositeVM(
        src,
        predicate=lambda vm: True,
        cursor_policy=FilteredCursorPolicy.CLEAR,
    )
    clear.current = src[1]
    clear.set_predicate(lambda vm: vm.name == "alpha")
    assert clear.current is None


@pytest.mark.conformance("COMP-034")
def test_COMP_034_visible_navigation_wraps() -> None:
    src = source("alpha", "bee", "gamma")
    sut = FilteredCompositeVM(src, predicate=lambda vm: "a" in vm.name)
    sut.current = sut.visible[0]
    sut.move_to_next_visible()
    assert sut.current is sut.visible[1]
    sut.move_to_previous_visible()
    assert sut.current is sut.visible[0]


@pytest.mark.conformance("COMP-035")
def test_COMP_035_dispose_stops_source_subscription() -> None:
    src = source("alpha")
    sut = FilteredCompositeVM(src, predicate=lambda vm: True)
    sut.dispose()
    src.add(child("bee"))
    assert [vm.name for vm in sut.visible] == ["alpha"]


@pytest.mark.conformance("COMP-036")
def test_COMP_036_scored_filter_sorts_by_score_with_stable_ties() -> None:
    src = source("alpha", "bee", "ax")
    sut = ScoredFilteredCompositeVM(src, scorer=lambda vm: 1 if vm.name.startswith("a") else None)
    assert [vm.name for vm in sut.visible] == ["alpha", "ax"]


@pytest.mark.conformance("COMP-037")
def test_COMP_037_scored_filter_recomputes_order_when_scores_change() -> None:
    weights = {"alpha": 1, "bee": 2}
    src = source("alpha", "bee")
    sut = ScoredFilteredCompositeVM(src, scorer=lambda vm: weights[vm.name])
    assert [vm.name for vm in sut.visible] == ["bee", "alpha"]
    weights["alpha"] = 3
    sut.refresh_scores()
    assert [vm.name for vm in sut.visible] == ["alpha", "bee"]

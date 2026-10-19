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
    src = source("alpha", "bee", "beta", "gamma")
    sut = FilteredCompositeVM(src, predicate=lambda vm: "a" in vm.name)
    # "bee" is excluded; source order of the accepted children is preserved.
    assert [vm.name for vm in sut.visible] == ["alpha", "beta", "gamma"]
    assert [id(vm) for vm in sut.visible] == [id(src[0]), id(src[2]), id(src[3])]


@pytest.mark.conformance("COMP-029")
def test_COMP_029_visible_count() -> None:
    sut = FilteredCompositeVM(source("alpha", "bee"), predicate=lambda vm: "a" in vm.name)
    assert sut.visible_count == 1


@pytest.mark.conformance("COMP-030")
def test_COMP_030_current_maps_to_visible_domain() -> None:
    src = source("bee", "alpha", "cee", "gamma")
    sut = FilteredCompositeVM(src, predicate=lambda vm: "a" in vm.name)
    # Non-first visible item whose visible index (1) differs from its source index (3).
    sut.current = sut.visible[1]
    assert sut.current is src[3]
    sut.current = sut.visible[0]
    assert sut.current is src[1]


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
def test_COMP_034_visible_navigation_clamps() -> None:
    src = source("alpha", "bee", "gamma")
    sut = FilteredCompositeVM(src, predicate=lambda vm: "a" in vm.name)
    sut.current = sut.visible[0]
    sut.move_to_next_visible()
    assert sut.current is sut.visible[1]
    # Clamps at the upper bound.
    sut.move_to_next_visible()
    assert sut.current is sut.visible[1]
    sut.move_to_previous_visible()
    assert sut.current is sut.visible[0]
    # Clamps at the lower bound.
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
    # Distinct scores exercise descending order; "alpha"/"ab" tie (source order
    # kept); "bee" scores None and is excluded.
    scores: dict[str, int | None] = {"alpha": 1, "bee": None, "ax": 3, "ab": 1, "az": 2}
    src = source("alpha", "bee", "ax", "ab", "az")
    sut = ScoredFilteredCompositeVM(src, scorer=lambda vm: scores[vm.name])
    assert [vm.name for vm in sut.visible] == ["ax", "az", "alpha", "ab"]


@pytest.mark.conformance("COMP-037")
def test_COMP_037_scored_filter_recomputes_order_when_scores_change() -> None:
    weights = {"alpha": 1, "bee": 2}
    src = source("alpha", "bee")
    sut = ScoredFilteredCompositeVM(src, scorer=lambda vm: weights[vm.name])
    assert [vm.name for vm in sut.visible] == ["bee", "alpha"]
    weights["alpha"] = 3
    sut.refresh_scores()
    assert [vm.name for vm in sut.visible] == ["alpha", "bee"]


def test_throwing_predicate_leaves_the_previous_projection_in_place() -> None:
    src = source("alpha", "beta")
    sut = FilteredCompositeVM(src, predicate=lambda _vm: True)
    beta = sut.visible[1]
    sut.set_current(beta)

    def boom(_vm: ComponentVM) -> bool:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        sut.set_predicate(boom)

    assert [vm.name for vm in sut.visible] == ["alpha", "beta"]
    assert sut.current is beta
    src.add(child("gamma"))  # the previous predicate still runs
    assert [vm.name for vm in sut.visible] == ["alpha", "beta", "gamma"]


def test_raising_observer_keeps_the_new_predicate() -> None:
    src = source("alpha", "beta")
    sut = FilteredCompositeVM(src, predicate=lambda _vm: True)

    raised: list[bool] = []

    def boom_once(_: None) -> None:
        if not raised:
            raised.append(True)
            raise RuntimeError("observer")

    sut.on_changed.subscribe(boom_once)
    with pytest.raises(RuntimeError):
        sut.set_predicate(lambda vm: vm.name == "alpha")

    assert [vm.name for vm in sut.visible] == ["alpha"]
    src.add(child("gamma"))  # the new predicate runs, not the previous one
    assert [vm.name for vm in sut.visible] == ["alpha"]

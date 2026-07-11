"""COL-040..047 — ObservableList replace_all conformance."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from vmx.collections.observable_list import ObservableList


def observed(*items: int) -> tuple[ObservableList[int], list[str]]:
    sut: ObservableList[int] = ObservableList()
    for item in items:
        sut.append(item)
    events: list[str] = []
    sut.on_item_added.subscribe(lambda _: events.append("add"))
    sut.on_item_removed.subscribe(lambda _: events.append("remove"))
    sut.on_item_replaced.subscribe(lambda _: events.append("replace"))
    sut.on_reset.subscribe(lambda _: events.append("reset"))
    sut.on_property_changed.subscribe(lambda name: events.append(f"property:{name}"))
    return sut, events


@pytest.mark.conformance("COL-040")
def test_COL_040_growth_emits_one_reset_and_count() -> None:
    sut, events = observed(1)
    sut.replace_all([2, 3, 4])
    assert list(sut) == [2, 3, 4]
    assert events == ["reset", "property:Count"]


@pytest.mark.conformance("COL-041")
def test_COL_041_shrink_emits_one_reset_and_count() -> None:
    sut, events = observed(1, 2, 3)
    sut.replace_all([9])
    assert list(sut) == [9]
    assert events == ["reset", "property:Count"]


@pytest.mark.conformance("COL-042")
def test_COL_042_equal_count_and_identical_contents_emit_reset() -> None:
    sut, events = observed(1, 2)
    sut.replace_all([3, 4])
    sut.replace_all([3, 4])
    assert events == ["reset", "reset"]

    class EqualityBomb:
        def __eq__(self, other: object) -> bool:
            raise AssertionError("equality invoked")

    bomb = EqualityBomb()
    unconstrained: ObservableList[EqualityBomb] = ObservableList()
    unconstrained.append(bomb)
    unconstrained.replace_all([bomb])


@pytest.mark.conformance("COL-043")
def test_COL_043_empty_cases_distinguish_noop_from_replacement() -> None:
    empty, empty_events = observed()
    empty.replace_all([])
    assert empty_events == []
    sut, events = observed(1)
    sut.replace_all([])
    assert events == ["reset", "property:Count"]


@pytest.mark.conformance("COL-044")
def test_COL_044_input_is_snapshotted_before_mutation() -> None:
    sut, events = observed(1, 2, 3)
    sut.replace_all(sut)
    assert list(sut) == [1, 2, 3]
    assert events == ["reset"]


@pytest.mark.conformance("COL-045")
def test_COL_045_nested_replacement_emits_only_outermost_reset() -> None:
    sut, events = observed(1)
    with sut.batch_update():
        sut.replace_all([2, 3])
        assert events == []
    assert events == ["reset", "property:Count"]


@pytest.mark.conformance("COL-046")
def test_COL_046_exceptional_batch_exit_restores_scope() -> None:
    sut, events = observed(1)
    with pytest.raises(RuntimeError, match="boom"):
        with sut.batch_update():
            sut.replace_all([2, 3])
            raise RuntimeError("boom")
    assert events == ["reset", "property:Count"]
    sut.replace_all([4, 5])
    assert events == ["reset", "property:Count", "reset"]


@pytest.mark.conformance("COL-047")
def test_COL_047_reset_precedes_count_and_observes_final_state() -> None:
    sut, _ = observed(1)
    observations: list[str] = []
    sut.on_reset.subscribe(lambda _: observations.append(f"reset:{list(sut)}"))
    sut.on_property_changed.subscribe(lambda name: observations.append(f"{name}:{list(sut)}"))
    sut.replace_all([7, 8])
    assert observations == ["reset:[7, 8]", "Count:[7, 8]"]


def test_replace_all_snapshot_failure_is_atomic() -> None:
    sut, events = observed(1, 2)

    def failing() -> Iterator[int]:
        yield 9
        raise RuntimeError("iteration failed")

    with pytest.raises(RuntimeError, match="iteration failed"):
        sut.replace_all(failing())
    assert list(sut) == [1, 2]
    assert events == []

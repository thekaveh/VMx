"""Conformance tests: COL-005..COL-009 — ObservableList[T] granular events.

Per spec/21-collections.md §3 and ADR-0026.
"""

from __future__ import annotations

import pytest

from vmx.collections.observable_list import ObservableList

# ---------------------------------------------------------------------------
# COL-005 — ItemAdded payload shape
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-005")
def test_COL_005_item_added_payload_shape() -> None:
    """COL-005: ObservableList ItemAdded emits (item, index) on Add."""
    sut: ObservableList[str] = ObservableList()
    sut.append("a")

    received: list[tuple[str, int]] = []
    sut.on_item_added.subscribe(received.append)

    sut.append("b")

    assert len(received) == 1
    item, index = received[0]
    assert item == "b"
    assert index == 1


# ---------------------------------------------------------------------------
# COL-006 — ItemRemoved payload shape
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-006")
def test_COL_006_item_removed_payload_shape() -> None:
    """COL-006: ObservableList ItemRemoved emits (item, indexBeforeRemoval) on RemoveAt."""
    sut: ObservableList[str] = ObservableList()
    sut.append("x")
    sut.append("y")
    sut.append("z")

    received: list[tuple[str, int]] = []
    sut.on_item_removed.subscribe(received.append)

    sut.remove_at(1)  # remove "y" at index 1

    assert len(received) == 1
    item, index = received[0]
    assert item == "y"
    assert index == 1  # index before removal


# ---------------------------------------------------------------------------
# COL-007 — ItemReplaced payload shape
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-007")
def test_COL_007_item_replaced_payload_shape() -> None:
    """COL-007: ObservableList ItemReplaced emits (newItem, oldItem, index) on Replace."""
    sut: ObservableList[str] = ObservableList()
    sut.append("old")
    sut.append("other")

    received: list[tuple[str, str, int]] = []
    sut.on_item_replaced.subscribe(received.append)

    sut.replace(0, "new")

    assert len(received) == 1
    new_item, old_item, index = received[0]
    assert new_item == "new"
    assert old_item == "old"
    assert index == 0


# ---------------------------------------------------------------------------
# COL-008 — Count/PropertyChanged ordering after add
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-008")
def test_COL_008_count_property_changed_ordering_after_add() -> None:
    """COL-008: ItemAdded fires before PropertyChanged('Count') on every add."""
    sut: ObservableList[int] = ObservableList()
    call_order: list[str] = []

    sut.on_item_added.subscribe(lambda _: call_order.append("item_added"))
    sut.on_property_changed.subscribe(lambda name: call_order.append(f"property_changed:{name}"))

    sut.append(42)

    # ItemAdded must fire before PropertyChanged("Count")
    assert call_order == ["item_added", "property_changed:Count"]


# ---------------------------------------------------------------------------
# COL-009 — batch suppression
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-009")
def test_COL_009_batch_suppression_only_reset_fires() -> None:
    """COL-009: Inside BatchUpdate only a single Reset fires; granular events are suppressed."""
    sut: ObservableList[int] = ObservableList()

    granular_events: list[str] = []
    resets: list[None] = []

    sut.on_item_added.subscribe(lambda _: granular_events.append("added"))
    sut.on_item_removed.subscribe(lambda _: granular_events.append("removed"))
    sut.on_item_replaced.subscribe(lambda _: granular_events.append("replaced"))
    sut.on_reset.subscribe(lambda _: resets.append(None))

    with sut.batch_update():
        sut.append(1)
        sut.append(2)
        sut.remove_at(0)
        sut.replace(0, 99)

    # Granular events suppressed; only one Reset fires at the end
    assert granular_events == []
    assert len(resets) == 1


# ---------------------------------------------------------------------------
# COL-023 — ObservableList batch-end Count notification
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-023")
def test_COL_023_batch_end_count_notification_when_count_changes() -> None:
    """COL-023: Batch with count-changing mutations emits Reset then PropertyChanged('Count')."""
    sut: ObservableList[int] = ObservableList()
    sut.append(10)  # pre-populate: count = 1

    call_order: list[str] = []
    count_at_reset: list[int] = []
    count_at_prop_changed: list[int] = []

    sut.on_reset.subscribe(lambda _: (call_order.append("reset"), count_at_reset.append(sut.count)))
    sut.on_property_changed.subscribe(
        lambda name: (
            (
                call_order.append(f"property_changed:{name}"),
                count_at_prop_changed.append(sut.count),
            )
            if name == "Count"
            else None
        )
    )

    # Add two items — count goes from 1 to 3
    with sut.batch_update():
        sut.append(20)
        sut.append(30)

    # Reset fires before PropertyChanged("Count") — ordering is normative
    assert call_order == ["reset", "property_changed:Count"]
    # Count is already updated when both events fire
    assert count_at_reset == [3]
    assert count_at_prop_changed == [3]


@pytest.mark.conformance("COL-023")
def test_COL_023_empty_batch_emits_nothing() -> None:
    """COL-023: Empty batch emits neither Reset nor PropertyChanged('Count')."""
    sut: ObservableList[int] = ObservableList()
    sut.append(1)

    events: list[str] = []
    sut.on_reset.subscribe(lambda _: events.append("reset"))
    sut.on_property_changed.subscribe(lambda name: events.append(f"pc:{name}"))

    # Empty batch — no mutations
    with sut.batch_update():
        pass

    assert events == []


@pytest.mark.conformance("COL-023")
def test_COL_023_count_preserving_batch_emits_reset_but_not_count() -> None:
    """COL-023: Replace-only batch emits Reset but NOT PropertyChanged('Count')."""
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    sut.append(2)

    events: list[str] = []
    sut.on_reset.subscribe(lambda _: events.append("reset"))
    sut.on_property_changed.subscribe(lambda name: events.append(f"pc:{name}"))

    # Only a replace — count stays at 2
    with sut.batch_update():
        sut.replace(0, 99)

    # Reset fires because there was a mutation, but no Count notification
    assert events == ["reset"]

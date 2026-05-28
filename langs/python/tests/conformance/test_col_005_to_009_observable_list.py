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

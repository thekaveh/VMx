"""Unit tests for ObservableList[T].

Conformance-level tests live in tests/conformance/test_col_005_to_009_observable_list.py.
"""

from __future__ import annotations

import pytest

from vmx.collections.observable_list import ObservableList

# ---------------------------------------------------------------------------
# Basic mutations — no subscribers
# ---------------------------------------------------------------------------


def test_append_increments_count() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    sut.append(2)
    assert sut.count == 2


def test_insert_at_position() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(10)
    sut.append(30)
    sut.insert(1, 20)
    assert list(sut) == [10, 20, 30]


def test_remove_returns_true_when_found() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("a")
    result = sut.remove("a")
    assert result is True
    assert sut.count == 0


def test_remove_returns_false_when_not_found() -> None:
    sut: ObservableList[str] = ObservableList()
    result = sut.remove("nonexistent")
    assert result is False


def test_remove_at_removes_correct_item() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(10)
    sut.append(20)
    sut.append(30)
    sut.remove_at(1)
    assert list(sut) == [10, 30]


def test_replace_changes_item_in_place() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("old")
    sut.replace(0, "new")
    assert sut[0] == "new"
    assert sut.count == 1


def test_clear_empties_list() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    sut.append(2)
    sut.clear()
    assert sut.count == 0


# ---------------------------------------------------------------------------
# on_item_added
# ---------------------------------------------------------------------------


def test_item_added_fires_on_append() -> None:
    sut: ObservableList[str] = ObservableList()
    received: list[tuple[str, int]] = []
    sut.on_item_added.subscribe(received.append)

    sut.append("hello")

    assert received == [("hello", 0)]


def test_item_added_fires_on_insert_with_correct_index() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(10)
    sut.append(30)
    received: list[tuple[int, int]] = []
    sut.on_item_added.subscribe(received.append)

    sut.insert(1, 20)

    assert received == [(20, 1)]


def test_item_added_fires_on_add_alias() -> None:
    sut: ObservableList[str] = ObservableList()
    received: list[tuple[str, int]] = []
    sut.on_item_added.subscribe(received.append)

    sut.add("via_add")

    assert len(received) == 1
    assert received[0][0] == "via_add"


def test_item_added_index_increments_correctly() -> None:
    sut: ObservableList[int] = ObservableList()
    received: list[tuple[int, int]] = []
    sut.on_item_added.subscribe(received.append)

    sut.append(1)
    sut.append(2)
    sut.append(3)

    assert received == [(1, 0), (2, 1), (3, 2)]


# ---------------------------------------------------------------------------
# on_item_removed
# ---------------------------------------------------------------------------


def test_item_removed_fires_on_remove() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("x")
    received: list[tuple[str, int]] = []
    sut.on_item_removed.subscribe(received.append)

    sut.remove("x")

    assert received == [("x", 0)]


def test_item_removed_fires_on_remove_at() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(10)
    sut.append(20)
    sut.append(30)
    received: list[tuple[int, int]] = []
    sut.on_item_removed.subscribe(received.append)

    sut.remove_at(1)

    assert received == [(20, 1)]


def test_item_removed_carries_index_before_removal() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("a")
    sut.append("b")
    sut.append("c")
    received: list[tuple[str, int]] = []
    sut.on_item_removed.subscribe(received.append)

    sut.remove("b")  # "b" is at index 1 before removal

    assert received == [("b", 1)]


# ---------------------------------------------------------------------------
# on_item_replaced
# ---------------------------------------------------------------------------


def test_item_replaced_fires_on_replace() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("old")
    received: list[tuple[str, str, int]] = []
    sut.on_item_replaced.subscribe(received.append)

    sut.replace(0, "new")

    assert received == [("new", "old", 0)]


def test_item_replaced_does_not_fire_count_changed() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("a")
    prop_events: list[str] = []
    sut.on_property_changed.subscribe(prop_events.append)

    sut.replace(0, "b")

    # Replace does not change Count, so no PropertyChanged("Count")
    assert prop_events == []


# ---------------------------------------------------------------------------
# on_reset
# ---------------------------------------------------------------------------


def test_reset_fires_on_clear() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    sut.append(2)
    resets: list[None] = []
    sut.on_reset.subscribe(resets.append)

    sut.clear()

    assert len(resets) == 1


def test_clear_fires_count_changed_after_reset() -> None:
    """Clear changes Count, so PropertyChanged("Count") fires after Reset.

    spec/21 §3.3 (clarified by ADR-0037): Count fires after every mutation
    that changes Count — including bulk clears, matching the batch-exit rule.
    """
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    events: list[str] = []
    sut.on_reset.subscribe(lambda _: events.append("reset"))
    sut.on_property_changed.subscribe(events.append)

    sut.clear()

    assert events == ["reset", "Count"]


def test_clear_on_empty_list_does_not_fire_count_changed() -> None:
    """Clearing an empty list does not change Count, so no notification."""
    sut: ObservableList[int] = ObservableList()
    prop_events: list[str] = []
    sut.on_property_changed.subscribe(prop_events.append)

    sut.clear()

    assert "Count" not in prop_events


# ---------------------------------------------------------------------------
# PropertyChanged("Count") ordering
# ---------------------------------------------------------------------------


def test_count_property_changed_fires_after_item_added_on_remove() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    call_order: list[str] = []

    sut.on_item_removed.subscribe(lambda _: call_order.append("item_removed"))
    sut.on_property_changed.subscribe(lambda name: call_order.append(f"property_changed:{name}"))

    sut.remove_at(0)

    assert call_order == ["item_removed", "property_changed:Count"]


# ---------------------------------------------------------------------------
# Batch update
# ---------------------------------------------------------------------------


def test_batch_with_no_mutations_fires_no_reset() -> None:
    sut: ObservableList[int] = ObservableList()
    resets: list[None] = []
    sut.on_reset.subscribe(resets.append)

    with sut.batch_update():
        pass  # no mutations

    assert resets == []


def test_batch_suppresses_granular_fires_one_reset() -> None:
    sut: ObservableList[int] = ObservableList()
    granular: list[str] = []
    resets: list[None] = []

    sut.on_item_added.subscribe(lambda _: granular.append("added"))
    sut.on_item_removed.subscribe(lambda _: granular.append("removed"))
    sut.on_item_replaced.subscribe(lambda _: granular.append("replaced"))
    sut.on_reset.subscribe(resets.append)

    with sut.batch_update():
        sut.append(1)
        sut.append(2)
        sut.remove_at(0)
        sut.replace(0, 99)

    assert granular == []
    assert len(resets) == 1


def test_nested_batch_fires_reset_only_on_outermost_exit() -> None:
    sut: ObservableList[int] = ObservableList()
    resets: list[None] = []
    granular: list[str] = []

    sut.on_item_added.subscribe(lambda _: granular.append("added"))
    sut.on_reset.subscribe(resets.append)

    with sut.batch_update():
        sut.append(1)
        with sut.batch_update():
            sut.append(2)
            # inner batch exits — no reset yet
        assert resets == []
        assert granular == []
    # outermost batch exits — one reset
    assert len(resets) == 1
    assert granular == []


def test_after_batch_normal_events_resume() -> None:
    sut: ObservableList[int] = ObservableList()
    received: list[tuple[int, int]] = []
    sut.on_item_added.subscribe(received.append)

    with sut.batch_update():
        sut.append(1)

    # After batch, granular events should fire normally
    sut.append(2)

    assert len(received) == 1
    assert received[0] == (2, 1)


def test_batch_exception_still_fires_reset() -> None:
    sut: ObservableList[int] = ObservableList()
    resets: list[None] = []
    sut.on_reset.subscribe(resets.append)

    with pytest.raises(RuntimeError):
        with sut.batch_update():
            sut.append(1)
            raise RuntimeError("test error")

    # Reset must fire even when batch exits via exception
    assert len(resets) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_list_remove_returns_false() -> None:
    sut: ObservableList[int] = ObservableList()
    assert sut.remove(42) is False


def test_duplicate_items_remove_first_occurrence() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("dup")
    sut.append("dup")
    received: list[tuple[str, int]] = []
    sut.on_item_removed.subscribe(received.append)

    sut.remove("dup")

    assert list(sut) == ["dup"]  # second "dup" remains
    assert received == [("dup", 0)]


def test_getitem_and_len() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(10)
    sut.append(20)
    assert sut[0] == 10
    assert sut[1] == 20
    assert len(sut) == 2


def test_slice_getitem() -> None:
    sut: ObservableList[int] = ObservableList()
    for i in range(5):
        sut.append(i)
    assert sut[1:3] == [1, 2]


def test_iter() -> None:
    sut: ObservableList[str] = ObservableList()
    sut.append("a")
    sut.append("b")
    assert list(sut) == ["a", "b"]


# ---------------------------------------------------------------------------
# Batch Count notification (spec §3.3)
# ---------------------------------------------------------------------------


def test_batch_count_grew_emits_property_changed_count() -> None:
    sut: ObservableList[int] = ObservableList()
    prop_changes: list[str] = []
    sut.on_property_changed.subscribe(prop_changes.append)

    with sut.batch_update():
        sut.append(1)
        sut.append(2)

    assert "Count" in prop_changes


def test_batch_count_shrank_emits_property_changed_count() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    sut.append(2)
    sut.append(3)
    prop_changes: list[str] = []
    sut.on_property_changed.subscribe(prop_changes.append)

    with sut.batch_update():
        sut.remove_at(0)
        sut.remove_at(0)

    assert "Count" in prop_changes


def test_batch_count_unchanged_replace_only_does_not_emit_count() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    sut.append(2)
    prop_changes: list[str] = []
    sut.on_property_changed.subscribe(prop_changes.append)

    # Replace operations keep count the same
    with sut.batch_update():
        sut.replace(0, 10)
        sut.replace(1, 20)

    assert "Count" not in prop_changes


def test_batch_add_and_remove_net_zero_does_not_emit_count() -> None:
    sut: ObservableList[int] = ObservableList()
    sut.append(1)
    prop_changes: list[str] = []
    sut.on_property_changed.subscribe(prop_changes.append)

    # Add one, remove one — net count change = 0
    with sut.batch_update():
        sut.append(99)
        sut.remove_at(1)

    assert "Count" not in prop_changes


def test_batch_nested_count_changed_emits_on_outermost_exit() -> None:
    sut: ObservableList[int] = ObservableList()
    prop_changes: list[str] = []
    sut.on_property_changed.subscribe(prop_changes.append)

    with sut.batch_update():
        with sut.batch_update():
            sut.append(1)
        # inner exited — no Count notification yet
        assert "Count" not in prop_changes

    # outermost exited — count changed (0 → 1), notification fires
    assert "Count" in prop_changes

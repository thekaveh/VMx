"""Conformance stubs: COL-005..COL-009 — ObservableList[T] granular events.

Per spec/21-collections.md §3 and ADR-0026.
Implemented in Substage 1C.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# COL-005 — ItemAdded payload shape
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-005")
def test_COL_005_item_added_payload_shape() -> None:
    """COL-005: ObservableList ItemAdded emits (item, index) on Add."""
    pytest.skip("COL-005 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-006 — ItemRemoved payload shape
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-006")
def test_COL_006_item_removed_payload_shape() -> None:
    """COL-006: ObservableList ItemRemoved emits (item, indexBeforeRemoval) on RemoveAt."""
    pytest.skip("COL-006 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-007 — ItemReplaced payload shape
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-007")
def test_COL_007_item_replaced_payload_shape() -> None:
    """COL-007: ObservableList ItemReplaced emits (newItem, oldItem, index) on Replace."""
    pytest.skip("COL-007 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-008 — Count/PropertyChanged ordering after add
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-008")
def test_COL_008_count_property_changed_ordering_after_add() -> None:
    """COL-008: ItemAdded fires before PropertyChanged('Count') on every add."""
    pytest.skip("COL-008 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-009 — batch suppression
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-009")
def test_COL_009_batch_suppression_only_reset_fires() -> None:
    """COL-009: Inside BatchUpdate only a single Reset fires; granular events are suppressed."""
    pytest.skip("COL-009 stub — implement in Substage 1C")
    raise NotImplementedError

"""Conformance stubs: COL-010..COL-015 — ObservableDictionary (multi-key).

Per spec/21-collections.md §4 and ADR-0025.
Implemented in Substage 1C.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# COL-010 — insert and retrieve
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-010")
def test_COL_010_insert_and_retrieve() -> None:
    """COL-010: ObservableDictionary insert sets ContainsKey and indexer."""
    pytest.skip("COL-010 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-011 — remove
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-011")
def test_COL_011_remove() -> None:
    """COL-011: ObservableDictionary Remove clears the entry and decrements Count."""
    pytest.skip("COL-011 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-012 — replace
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-012")
def test_COL_012_replace() -> None:
    """COL-012: Replacing an existing entry returns the new value without changing Count."""
    pytest.skip("COL-012 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-013 — distinct-key observable views
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-013")
def test_COL_013_distinct_key_observable_views_stay_in_sync() -> None:
    """COL-013: Keys1 and Keys2 observable views reflect distinct keys in insertion order."""
    pytest.skip("COL-013 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-014 — enumeration order
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-014")
def test_COL_014_enumeration_order_is_insertion_order() -> None:
    """COL-014: Enumerating ObservableDictionary yields entries in insertion order."""
    pytest.skip("COL-014 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-015 — clear empties key views
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-015")
def test_COL_015_clear_empties_key_views() -> None:
    """COL-015: Clear() resets Count to 0 and empties Keys1 and Keys2."""
    pytest.skip("COL-015 stub — implement in Substage 1C")
    raise NotImplementedError

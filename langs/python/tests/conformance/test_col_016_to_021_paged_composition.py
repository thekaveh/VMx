"""Conformance stubs: COL-016..COL-021 — PagedComposition[TVM].

Per spec/21-collections.md §5 and ADR-0023.
Implemented in Substage 1C.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# COL-016 — clamping CurrentPageIndex when source shrinks
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-016")
def test_COL_016_clamps_current_page_index_when_source_shrinks() -> None:
    """COL-016: CurrentPageIndex is clamped to [0, PageCount-1] when the source shrinks."""
    pytest.skip("COL-016 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-017 — PageCount derivation under add and remove
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-017")
def test_COL_017_page_count_derivation_under_add_and_remove() -> None:
    """COL-017: PageCount equals ceil(sourceCount / PageSize) and updates on mutations."""
    pytest.skip("COL-017 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-018 — navigation no-ops at bounds
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-018")
def test_COL_018_navigation_no_ops_at_bounds() -> None:
    """COL-018: move_to_first/last_page are no-ops when already at the respective bound."""
    pytest.skip("COL-018 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-019 — PageSize=0 passes through all items
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-019")
def test_COL_019_page_size_zero_passes_through_all_items() -> None:
    """COL-019: PageSize==0 disables paging; Items yields the full source."""
    pytest.skip("COL-019 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-020 — empty-source behavior
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-020")
def test_COL_020_empty_source_behavior() -> None:
    """COL-020: On empty source, PageCount==0, Items is empty, navigation is a no-op."""
    pytest.skip("COL-020 stub — implement in Substage 1C")
    raise NotImplementedError


# ---------------------------------------------------------------------------
# COL-021 — composition with SearchableState
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-021")
def test_COL_021_composition_with_searchable_state() -> None:
    """COL-021: Wrapping SearchableState filtered view pages the filtered count, not the total."""
    pytest.skip("COL-021 stub — implement in Substage 1C")
    raise NotImplementedError

"""Conformance tests: COL-016..COL-021 — PagedComposition[TVM].

Per spec/21-collections.md §5 and ADR-0023.
"""

from __future__ import annotations

import pytest

from vmx.capabilities.searchable_state import SearchableState
from vmx.collections.observable_list import ObservableList
from vmx.collections.paged_composition import PagedComposition

# ---------------------------------------------------------------------------
# COL-016 — clamping CurrentPageIndex when source shrinks
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-016")
def test_COL_016_clamps_current_page_index_when_source_shrinks() -> None:
    """COL-016: CurrentPageIndex is clamped to [0, PageCount-1] when the source shrinks.

    Given a PagedComposition wrapping a 10-item source with page_size=3 and
    current_page_index=2 (last page), when items are removed until 4 remain
    (2 full pages), then page_count==2 and current_page_index clamps to 1.
    """
    source: ObservableList[str] = ObservableList()
    for i in range(10):
        source.append(f"item{i}")

    sut: PagedComposition[str] = PagedComposition(source, page_size=3)
    assert sut.page_count == 4  # ceil(10/3) = 4

    sut.current_page_index = 2
    assert sut.current_page_index == 2

    # Remove items until only 4 remain
    while source.count > 4:
        source.remove_at(source.count - 1)

    assert sut.page_count == 2  # ceil(4/3) = 2
    assert sut.current_page_index == 1  # re-clamped from 2 to 1

    sut.dispose()


# ---------------------------------------------------------------------------
# COL-017 — PageCount derivation under add and remove
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-017")
def test_COL_017_page_count_derivation_under_add_and_remove() -> None:
    """COL-017: PageCount equals ceil(sourceCount / page_size) and updates on mutations.

    Given page_size=5, empty source: page_count==0.
    After 5 adds: page_count==1.  After 1 more: page_count==2.
    After removing that extra item: page_count==1.
    """
    source: ObservableList[int] = ObservableList()
    sut: PagedComposition[int] = PagedComposition(source, page_size=5)

    # Empty source + paging enabled → page_count == 0 (spec §5.4)
    assert sut.page_count == 0

    for i in range(5):
        source.append(i)
    assert sut.page_count == 1

    source.append(99)
    assert sut.page_count == 2

    source.remove(99)
    assert sut.page_count == 1

    sut.dispose()


# ---------------------------------------------------------------------------
# COL-018 — navigation no-ops at bounds
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-018")
def test_COL_018_navigation_no_ops_at_bounds() -> None:
    """COL-018: move_to_first/last_page are no-ops when already at the respective bound.

    Given page_size=3 over 8 items (page_count=3):
    - move_to_first_page at index 0 → stays 0.
    - move_to_last_page at last page → stays PageCount-1.
    - move_to_next_page at upper bound → stays PageCount-1.
    - move_to_previous_page at first page → stays 0.
    """
    source: ObservableList[int] = ObservableList()
    for i in range(8):
        source.append(i)

    sut: PagedComposition[int] = PagedComposition(source, page_size=3)
    assert sut.page_count == 3  # ceil(8/3) = 3

    # At lower bound
    assert sut.current_page_index == 0
    sut.move_to_first_page()
    assert sut.current_page_index == 0

    sut.move_to_previous_page()
    assert sut.current_page_index == 0

    # Navigate to upper bound
    sut.move_to_last_page()
    assert sut.current_page_index == 2

    sut.move_to_last_page()
    assert sut.current_page_index == 2

    sut.move_to_next_page()
    assert sut.current_page_index == 2

    sut.dispose()


# ---------------------------------------------------------------------------
# COL-019 — PageSize=0 passes through all items
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-019")
def test_COL_019_page_size_zero_passes_through_all_items() -> None:
    """COL-019: page_size==0 disables paging; items yields the full source.

    Given a 7-item source with page_size=0:
    is_paging_enabled==False, page_count==1, current_page_index==0,
    items yields all 7 items.
    """
    source: ObservableList[int] = ObservableList()
    for i in range(7):
        source.append(i)

    sut: PagedComposition[int] = PagedComposition(source, page_size=0)

    assert sut.is_paging_enabled is False
    assert sut.page_count == 1
    assert sut.current_page_index == 0
    assert sut.items == list(range(7))

    sut.dispose()


# ---------------------------------------------------------------------------
# COL-020 — empty-source behavior
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-020")
def test_COL_020_empty_source_behavior() -> None:
    """COL-020: On empty source, page_count==0, items is empty, navigation is a no-op.

    Given an empty source with page_size=5:
    page_count==0, current_page_index==0, items is empty,
    all four navigation verbs are no-ops (no exception raised).
    """
    source: ObservableList[str] = ObservableList()
    sut: PagedComposition[str] = PagedComposition(source, page_size=5)

    assert sut.page_count == 0
    assert sut.current_page_index == 0
    assert sut.items == []

    # All navigation verbs must be no-ops — must not raise
    sut.move_to_first_page()
    sut.move_to_previous_page()
    sut.move_to_next_page()
    sut.move_to_last_page()

    assert sut.current_page_index == 0

    sut.dispose()


# ---------------------------------------------------------------------------
# COL-021 — composition with SearchableState
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-021")
def test_COL_021_composition_with_searchable_state() -> None:
    """COL-021: Wrapping SearchableState filtered view pages the filtered count, not the total.

    Filter-first-then-page ordering (spec §6.1):
    - 10 items total: 4 starting with "Alpha", 6 starting with "Zeta".
    - SearchableState: empty term → all 10 pass; term "Alpha" → 4 pass.
    - PagedComposition wraps the filtered view (page_size=3).
    - page_count reflects the FILTERED count.
    """
    items = [f"Alpha{i}" for i in range(4)] + [f"Zeta{i}" for i in range(6)]

    # SearchableState: filter by prefix matching the search term
    searchable: SearchableState[str] = SearchableState(
        items=lambda: items,
        predicate=lambda item, term: not term or item.lower().startswith(term.lower()),
        debounce_seconds=0,
    )

    # Track the current filtered snapshot
    filtered_snapshot: list[str] = []
    searchable.filtered.subscribe(
        on_next=lambda snap: (
            (filtered_snapshot.__class__ and filtered_snapshot.clear())
            or filtered_snapshot.extend(snap)
        )
    )

    # Force initial emission (debounce=0 with synchronous scheduler may need a trigger)
    searchable.search()
    # After the initial pass with empty term all 10 items are in the snapshot
    # (SearchableState initialises with "" → all match)

    # PagedComposition wraps a lazy factory that always reads the current snapshot
    sut: PagedComposition[str] = PagedComposition(
        source=lambda: list(filtered_snapshot),
        page_size=3,
    )

    # With empty search term all 10 items pass → ceil(10/3) = 4 pages
    assert sut.page_count == 4

    # Apply search term → 4 Alpha items → ceil(4/3) = 2 pages
    searchable.search_term = "Alpha"
    searchable.search()  # force synchronous recompute (debounce=0)

    assert sut.page_count == 2

    # Page 0 yields the first 3 filtered items
    sut.current_page_index = 0
    page0 = sut.items
    assert page0 == ["Alpha0", "Alpha1", "Alpha2"]

    # No Zeta items should appear on page 0
    assert not any(item.startswith("Zeta") for item in page0)

    sut.dispose()
    searchable.dispose()

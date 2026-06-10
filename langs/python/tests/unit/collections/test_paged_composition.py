"""Unit tests for PagedComposition[TVM].

Conformance-level tests live in tests/conformance/test_col_016_to_021_paged_composition.py.
"""

from __future__ import annotations

import pytest

from vmx.collections.observable_list import ObservableList
from vmx.collections.paged_composition import PagedComposition

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_page_size_is_zero() -> None:
    source: ObservableList[int] = ObservableList()
    sut: PagedComposition[int] = PagedComposition(source)
    assert sut.page_size == 0
    assert sut.is_paging_enabled is False
    sut.dispose()


def test_negative_page_size_clamped_to_zero() -> None:
    source: ObservableList[int] = ObservableList()
    sut: PagedComposition[int] = PagedComposition(source, page_size=-5)
    assert sut.page_size == 0
    sut.dispose()


def test_none_source_raises() -> None:
    with pytest.raises(TypeError):
        PagedComposition(None, page_size=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PageCount derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item_count,page_size,expected",
    [
        (10, 3, 4),  # ceil(10/3) = 4
        (9, 3, 3),  # ceil(9/3) = 3
        (1, 5, 1),  # ceil(1/5) = 1
        (5, 5, 1),  # ceil(5/5) = 1
        (6, 5, 2),  # ceil(6/5) = 2
    ],
)
def test_page_count_reflects_source_count(item_count: int, page_size: int, expected: int) -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(item_count):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=page_size)
    assert sut.page_count == expected
    sut.dispose()


def test_page_count_empty_source_with_paging_enabled_is_zero() -> None:
    source: ObservableList[int] = ObservableList()
    sut: PagedComposition[int] = PagedComposition(source, page_size=5)
    assert sut.page_count == 0
    sut.dispose()


def test_page_count_page_size_zero_is_always_one() -> None:
    source: ObservableList[int] = ObservableList()
    source.append(1)
    source.append(2)
    sut: PagedComposition[int] = PagedComposition(source, page_size=0)
    assert sut.page_count == 1
    sut.dispose()


# ---------------------------------------------------------------------------
# Items / slicing
# ---------------------------------------------------------------------------


def test_items_first_page_yields_correct_slice() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(10):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=3)
    sut.current_page_index = 0
    assert sut.items == [0, 1, 2]
    sut.dispose()


def test_items_last_page_yields_remainder() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(10):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=3)
    sut.current_page_index = 3  # 4th page: only item 9
    assert sut.items == [9]
    sut.dispose()


def test_items_page_size_zero_yields_all() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(5):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=0)
    assert sut.items == [0, 1, 2, 3, 4]
    sut.dispose()


def test_count_reflects_current_page_item_count() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(7):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=3)
    sut.current_page_index = 0
    assert sut.count == 3

    sut.current_page_index = 2  # last page: 1 item (7 mod 3 == 1)
    assert sut.count == 1
    sut.dispose()


# ---------------------------------------------------------------------------
# current_page_index clamping
# ---------------------------------------------------------------------------


def test_current_page_index_set_beyond_page_count_clamps_to_max() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(6):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)  # page_count=3
    sut.current_page_index = 99
    assert sut.current_page_index == 2
    sut.dispose()


def test_current_page_index_set_negative_clamps_to_zero() -> None:
    source: ObservableList[int] = ObservableList()
    source.append(1)
    sut: PagedComposition[int] = PagedComposition(source, page_size=1)
    sut.current_page_index = -1
    assert sut.current_page_index == 0
    sut.dispose()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def test_move_to_first_page_sets_index_to_zero() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(6):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)
    sut.move_to_last_page()
    sut.move_to_first_page()
    assert sut.current_page_index == 0
    sut.dispose()


def test_move_to_last_page_sets_index_to_page_count_minus_1() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(6):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)
    sut.move_to_last_page()
    assert sut.current_page_index == 2
    sut.dispose()


def test_move_to_next_page_advances_index() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(6):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)
    sut.move_to_next_page()
    assert sut.current_page_index == 1
    sut.dispose()


def test_move_to_previous_page_decrements_index() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(6):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)
    sut.move_to_last_page()
    sut.move_to_previous_page()
    assert sut.current_page_index == 1
    sut.dispose()


# ---------------------------------------------------------------------------
# page_size mutation re-clamps current_page_index
# ---------------------------------------------------------------------------


def test_page_size_setting_larger_reclamps_index() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(10):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)  # page_count=5
    sut.current_page_index = 4
    sut.page_size = 5  # page_count = 2 now; index 4 > max(1) → clamp to 1
    assert sut.current_page_index == 1
    sut.dispose()


# ---------------------------------------------------------------------------
# on_property_changed observable
# ---------------------------------------------------------------------------


def test_property_changed_fires_on_navigation() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(6):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)

    changed: list[str] = []
    sut.on_property_changed.subscribe(on_next=changed.append)

    sut.move_to_next_page()

    assert "current_page_index" in changed
    assert "items" in changed
    sut.dispose()


def test_property_changed_fires_on_source_mutation() -> None:
    source: ObservableList[int] = ObservableList()
    for i in range(3):
        source.append(i)
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)

    changed: list[str] = []
    sut.on_property_changed.subscribe(on_next=changed.append)

    source.append(99)  # triggers _on_source_mutated

    assert "page_count" in changed
    sut.dispose()


# ---------------------------------------------------------------------------
# source property
# ---------------------------------------------------------------------------


def test_source_returns_original_source() -> None:
    source: ObservableList[int] = ObservableList()
    sut: PagedComposition[int] = PagedComposition(source, page_size=2)
    assert sut.source is source
    sut.dispose()


def test_source_callable_is_preserved() -> None:
    items = [1, 2, 3]

    def factory() -> list[int]:
        return items

    sut: PagedComposition[int] = PagedComposition(factory, page_size=2)
    assert sut.source is factory
    sut.dispose()


# ---------------------------------------------------------------------------
# Dispose
# ---------------------------------------------------------------------------


def test_dispose_is_idempotent() -> None:
    source: ObservableList[int] = ObservableList()
    source.append(1)
    sut: PagedComposition[int] = PagedComposition(source, page_size=1)
    sut.dispose()
    sut.dispose()  # second call must not raise


def test_replace_on_source_refreshes_items() -> None:
    """replace() mutates page contents, so the composition must re-emit items."""
    source: ObservableList[int] = ObservableList()
    source.append(1)
    source.append(2)
    sut: PagedComposition[int] = PagedComposition(source, page_size=10)
    events: list[str] = []
    sut.on_property_changed.subscribe(events.append)

    source.replace(0, 99)

    assert "items" in events
    assert sut.items[0] == 99
    sut.dispose()

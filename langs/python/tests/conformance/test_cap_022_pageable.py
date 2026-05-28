"""Conformance tests: CAP-022 — Pageable capability contract.

Per spec/14-capabilities.md §2.10 and ADR-0023, Pageable exposes mutable
page_size and current_page_index, derived page_count and is_paging_enabled,
and four navigation methods that are no-ops at their respective bounds.

PageCount rule (per spec §5.4):
    ceil(item_count / page_size)  when page_size > 0  (0 when source is empty)
    1                             when page_size == 0 (paging disabled)
"""

from __future__ import annotations

import math

import pytest

from vmx.capabilities import Pageable

# ---------------------------------------------------------------------------
# Minimal opt-in implementer (used only by CAP-022)
# ---------------------------------------------------------------------------


class _PageableFixture(Pageable):
    """Minimal Pageable implementer that tracks an item count."""

    def __init__(self, item_count: int) -> None:
        self._item_count = item_count
        self._page_size: int = 10
        self._current_page_index: int = 0

    # ── page_size ────────────────────────────────────────────────────────────

    @property
    def page_size(self) -> int:
        return self._page_size

    @page_size.setter
    def page_size(self, value: int) -> None:
        self._page_size = max(0, value)
        # Re-clamp after resize
        self._current_page_index = self._clamp(self._current_page_index)

    # ── current_page_index ───────────────────────────────────────────────────

    @property
    def current_page_index(self) -> int:
        return self._current_page_index

    @current_page_index.setter
    def current_page_index(self, value: int) -> None:
        self._current_page_index = self._clamp(value)

    # ── derived ──────────────────────────────────────────────────────────────

    @property
    def page_count(self) -> int:
        if self._page_size <= 0:
            return 1
        return math.ceil(self._item_count / self._page_size)

    @property
    def is_paging_enabled(self) -> bool:
        return self._page_size > 0

    # ── navigation ───────────────────────────────────────────────────────────

    def move_to_first_page(self) -> None:
        self._current_page_index = 0

    def move_to_previous_page(self) -> None:
        if self._current_page_index > 0:
            self._current_page_index -= 1

    def move_to_next_page(self) -> None:
        if self._current_page_index < self.page_count - 1:
            self._current_page_index += 1

    def move_to_last_page(self) -> None:
        self._current_page_index = self.page_count - 1

    # ── helpers ──────────────────────────────────────────────────────────────

    def _clamp(self, index: int) -> int:
        if self.page_count == 0:
            return 0  # empty source: index stays at 0
        max_idx = self.page_count - 1
        if index < 0:
            return 0
        if index > max_idx:
            return max_idx
        return index


# ---------------------------------------------------------------------------
# CAP-022 — Pageable capability contract surface and clamping/navigation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-022")
def test_CAP_022_pageable_contract() -> None:
    """CAP-022: Pageable capability contract surface and clamping/navigation.

    Verifies:
    1. Initial state: page_size=10, current_page_index=0, derived values correct.
    2. page_size=0: is_paging_enabled=False, page_count=1, navigation no-ops.
    3. Clamping current_page_index: above max clamps down; below 0 clamps up.
    4. Navigation: first/last/next/previous work; no-ops at bounds.
    5. page_size resize clamps current_page_index if out of range.
    6. item_count=0 with page_size>0 yields page_count=0 (empty source).
    """
    # ── 1. Initial state ─────────────────────────────────────────────────────
    sut = _PageableFixture(item_count=25)
    assert sut.page_size == 10
    assert sut.current_page_index == 0
    assert sut.is_paging_enabled is True
    assert sut.page_count == 3  # ceil(25/10)

    # ── 2. page_size = 0 ─────────────────────────────────────────────────────
    sut.page_size = 0
    assert sut.is_paging_enabled is False
    assert sut.page_count == 1  # disabled → everything is one page

    # Navigation while paging disabled — no-ops, index stays 0
    sut.move_to_first_page()
    sut.move_to_last_page()
    assert sut.current_page_index == 0

    # ── 3. Clamping current_page_index ────────────────────────────────────────
    sut.page_size = 10  # re-enable; page_count = 3 again
    sut.current_page_index = 99
    assert sut.current_page_index == 2  # clamped to page_count - 1

    sut.current_page_index = -1
    assert sut.current_page_index == 0  # clamped to 0

    # ── 4. Navigation ─────────────────────────────────────────────────────────
    sut.current_page_index = 1
    sut.move_to_first_page()
    assert sut.current_page_index == 0

    sut.move_to_last_page()
    assert sut.current_page_index == 2

    # move_to_next_page at upper bound is a no-op
    sut.move_to_next_page()
    assert sut.current_page_index == 2

    # move_to_previous_page decrements
    sut.move_to_previous_page()
    assert sut.current_page_index == 1

    # move_to_previous_page at lower bound is a no-op
    sut.move_to_first_page()
    sut.move_to_previous_page()
    assert sut.current_page_index == 0

    # move_to_next_page advances
    sut.move_to_next_page()
    assert sut.current_page_index == 1

    # ── 5. page_size resize clamps current_page_index ────────────────────────
    sut.current_page_index = 2  # move to page 3 of 3
    sut.page_size = 20  # now page_count = ceil(25/20) = 2 → pages 0..1
    assert sut.current_page_index == 1  # clamped from 2 to 1

    # ── 6. item_count=0 with page_size>0 yields page_count=0 ─────────────────
    empty = _PageableFixture(item_count=0)
    empty.page_size = 5
    assert empty.page_count == 0  # ceil(0/5) = 0 (empty source has no pages)

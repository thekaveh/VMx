"""Paging capability contract. See spec/14-capabilities.md §2.10 and ADR-0023."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Pageable(ABC):
    """A view that exposes a paged navigation surface over its underlying data.

    ``page_size`` and ``current_page_index`` are mutable.
    ``page_count`` and ``is_paging_enabled`` are derived (implementer computes
    them from the underlying item count and ``page_size``).

    Clamping contract (implementer responsibility, verified by CAP-022):

    - Setting ``current_page_index`` outside ``[0, page_count-1]`` must clamp
      to the nearest bound.
    - Resizing ``page_size`` must re-clamp ``current_page_index`` if it falls
      out of range.
    - All navigation methods are no-ops when already at the respective bound.

    When ``page_size`` is 0 paging is disabled: every item fits in a single
    page (``page_count == 1``, ``is_paging_enabled == False``).
    """

    @property
    @abstractmethod
    def page_size(self) -> int:
        """Number of items per page.

        0 means "all items in one page" (paging disabled).
        Must not be negative; implementers may clamp negative assignments to 0.
        """
        ...

    @page_size.setter
    @abstractmethod
    def page_size(self, value: int) -> None: ...

    @property
    @abstractmethod
    def current_page_index(self) -> int:
        """Zero-based index of the currently visible page.

        Setting a value outside ``[0, page_count-1]`` must clamp to the
        nearest bound.
        """
        ...

    @current_page_index.setter
    @abstractmethod
    def current_page_index(self, value: int) -> None: ...

    @property
    @abstractmethod
    def page_count(self) -> int:
        """Total number of pages.

        Derived as ``max(1, ceil(item_count / page_size))`` when paging is
        enabled; 1 when paging is disabled.
        """
        ...

    @property
    @abstractmethod
    def is_paging_enabled(self) -> bool:
        """``True`` when ``page_size > 0``."""
        ...

    @abstractmethod
    def move_to_first_page(self) -> None:
        """Set ``current_page_index`` to 0.

        No-op when already at the first page.
        """
        ...

    @abstractmethod
    def move_to_previous_page(self) -> None:
        """Decrement ``current_page_index`` by 1.

        No-op when ``current_page_index`` is already 0.
        """
        ...

    @abstractmethod
    def move_to_next_page(self) -> None:
        """Increment ``current_page_index`` by 1.

        No-op when ``current_page_index`` is already ``page_count - 1``.
        """
        ...

    @abstractmethod
    def move_to_last_page(self) -> None:
        """Set ``current_page_index`` to ``page_count - 1``.

        No-op when already at the last page.
        """
        ...

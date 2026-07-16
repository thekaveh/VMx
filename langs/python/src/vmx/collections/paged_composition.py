"""PagedComposition — paged-view decorator for any sequence.

Implements the ``Pageable`` capability over any source iterable. If the
source is an :class:`~vmx.collections.observable_list.ObservableList`, mutations
are observed automatically so that ``page_count`` and ``items`` stay in sync.

See spec/21-collections.md §5 and ADR-0023.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.capabilities.pageable import Pageable

TVM = TypeVar("TVM")


class PagedComposition(Pageable, Generic[TVM]):
    """Decorates any source sequence with paged-view semantics.

    The source is never mutated; this class computes a read-only slice on
    demand.  If the source exposes ``on_item_added`` / ``on_item_removed`` /
    ``on_reset`` observables (i.e. an :class:`~vmx.collections.observable_list.ObservableList`),
    mutations are observed automatically.

    ``page_size = 0`` disables paging: all source items appear on a single
    page (``page_count == 1``, ``is_paging_enabled == False``).

    Empty source with ``page_size > 0``: ``page_count == 0``,
    ``current_page_index`` stays 0, ``items`` is empty.

    Args:
        source: The sequence to page over.  A callable (lazy factory) is
            also accepted; the callable is invoked on each access so that
            external filtered views (e.g. ``SearchableState.filtered``) are
            always read fresh.
        page_size: Initial page size (default 0 = paging disabled).
            Negative values are clamped to 0.
    """

    def __init__(
        self,
        source: Iterable[TVM] | Callable[[], Iterable[TVM]],
        page_size: int = 0,
    ) -> None:
        if source is None:
            raise TypeError("source must not be None")
        self._source_factory: Callable[[], Iterable[TVM]]
        if callable(source) and not isinstance(source, Iterable):
            self._source_factory = source
        elif isinstance(source, Iterator):
            snapshot = list(source)
            self._source_factory = lambda: snapshot
        else:
            # Wrap the iterable in a zero-arg callable so _items() is uniform.
            # We keep the original reference so observers can subscribe to it.
            _src = source
            self._source_factory = lambda: _src

        self._raw_source = source
        self._page_size: int = max(0, page_size)
        self._current_page_index: int = 0
        self._disposed = False

        # Property-changed observable
        self._prop_changed: Subject[str] = Subject()

        # Subscribe to source mutations if the source supports it.
        self._subscriptions: list[object] = []
        self._try_subscribe_source(source)

    # ── Pageable ABC ──────────────────────────────────────────────────────────

    @property
    def page_size(self) -> int:
        return self._page_size

    @page_size.setter
    def page_size(self, value: int) -> None:
        if self._disposed:
            return
        clamped = max(0, value)
        if self._page_size == clamped:
            return
        self._page_size = clamped
        self._current_page_index = self._clamp_index(self._current_page_index)
        self._prop_changed.on_next("page_size")
        self._prop_changed.on_next("is_paging_enabled")
        self._prop_changed.on_next("page_count")
        self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    @property
    def current_page_index(self) -> int:
        return self._current_page_index

    @current_page_index.setter
    def current_page_index(self, value: int) -> None:
        if self._disposed:
            return
        clamped = self._clamp_index(value)
        if self._current_page_index == clamped:
            return
        self._current_page_index = clamped
        self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    @property
    def page_count(self) -> int:
        if self._page_size == 0:
            return 1
        n = self._source_count()
        if n == 0:
            # Spec §5.4: empty source → PageCount == 0 (not max(1, …))
            return 0
        return math.ceil(n / self._page_size)

    @property
    def is_paging_enabled(self) -> bool:
        return self._page_size > 0

    def move_to_first_page(self) -> None:
        if self._disposed:
            return
        if self._current_page_index == 0:
            return
        self._current_page_index = 0
        self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    def move_to_previous_page(self) -> None:
        if self._disposed:
            return
        if self._current_page_index <= 0:
            return
        self._current_page_index -= 1
        self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    def move_to_next_page(self) -> None:
        if self._disposed:
            return
        max_idx = self.page_count - 1
        if self._current_page_index >= max_idx:
            return
        self._current_page_index += 1
        self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    def move_to_last_page(self) -> None:
        if self._disposed:
            return
        last = self.page_count - 1
        if self._current_page_index >= last:
            return
        self._current_page_index = last
        self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    # ── PagedComposition-specific surface ─────────────────────────────────────

    @property
    def source(self) -> Iterable[TVM] | Callable[[], Iterable[TVM]]:
        """The raw source passed to the constructor (never mutated)."""
        return self._raw_source

    @property
    def items(self) -> list[TVM]:
        """The items on the current page (materialised list).

        Returns all source items when paging is disabled (``page_size == 0``).
        Returns an empty list when the source is empty.
        """
        src = list(self._source_factory())
        if self._page_size == 0:
            return src
        if not src:
            return []
        start = self._current_page_index * self._page_size
        return src[start : start + self._page_size]

    @property
    def count(self) -> int:
        """Number of items on the current page (not the total source count)."""
        return len(self.items)

    @property
    def on_property_changed(self) -> rx.Observable[str]:
        """Observable that emits property names when they change.

        The backing Subject is sealed behind ``as_observable`` so external
        subscribers can only subscribe — never ``on_next``/``dispose`` the
        internal stream (VMX-013).
        """
        return self._prop_changed.pipe(ops.as_observable())

    # ── Disposal ──────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Detach from source observables.  Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        for sub in self._subscriptions:
            try:
                sub.dispose()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._subscriptions.clear()
        self._prop_changed.on_completed()
        self._prop_changed.dispose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _source_count(self) -> int:
        src = self._source_factory()
        # Fast path for sized sequences
        try:
            return len(src)  # type: ignore[arg-type]
        except TypeError:
            return sum(1 for _ in src)

    def _clamp_index(self, index: int) -> int:
        # When page_count == 0 (empty source + paging enabled), index stays at 0
        max_idx = max(0, self.page_count - 1)
        if index < 0:
            return 0
        if index > max_idx:
            return max_idx
        return index

    def _on_source_mutated(self) -> None:
        """Called when the source signals a mutation."""
        clamped = self._clamp_index(self._current_page_index)
        index_changed = clamped != self._current_page_index
        if index_changed:
            self._current_page_index = clamped
        self._prop_changed.on_next("page_count")
        if index_changed:
            self._prop_changed.on_next("current_page_index")
        self._prop_changed.on_next("items")

    def _try_subscribe_source(self, source: Iterable[TVM] | Callable[[], Iterable[TVM]]) -> None:
        """Subscribe to source mutation events if the source supports them."""
        # ObservableList exposes on_item_added, on_item_removed,
        # on_item_replaced, on_reset — replace mutates page contents too.
        for attr in ("on_item_added", "on_item_removed", "on_item_replaced", "on_reset"):
            observable = getattr(source, attr, None)
            if observable is not None:
                sub = observable.subscribe(on_next=lambda _: self._on_source_mutated())
                self._subscriptions.append(sub)
        # CompositeVM and GroupVM expose one typed collection-changed stream.
        observable = getattr(source, "on_collection_changed", None)
        if observable is not None:
            sub = observable.subscribe(on_next=lambda _: self._on_source_mutated())
            self._subscriptions.append(sub)

"""ObservableList — granular per-mutation event observable list.

See spec/21-collections.md §3 and ADR-0026.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex.subject import Subject

T = TypeVar("T")


class ObservableList(Generic[T]):
    """An observable list that raises granular per-mutation events.

    Four observables are exposed:

    - ``on_item_added``    — ``Observable[tuple[T, int]]`` emits ``(item, index)``
    - ``on_item_removed``  — ``Observable[tuple[T, int]]`` emits ``(item, index)``
      (index is position before removal)
    - ``on_item_replaced`` — ``Observable[tuple[T, T, int]]`` emits ``(new_item, old_item, index)``
    - ``on_reset``         — ``Observable[None]``

    A ``PropertyChanged("Count")`` signal is emitted via ``on_property_changed``
    **after** the granular event for every mutation that changes Count (add and
    remove; not replace). This ordering is normative per spec §3.3 and ADR-0026.

    Inside a ``batch_update()`` context manager, granular events are suppressed.
    A single ``Reset`` fires when the outermost batch exits (ref-counted).

    See spec/21-collections.md §3 and ADR-0026.
    """

    def __init__(self) -> None:
        self._items: list[T] = []
        self._batch_depth: int = 0
        self._mutated_in_batch: bool = False

        # Granular event subjects
        self._added_subject: Subject[tuple[T, int]] = Subject()
        self._removed_subject: Subject[tuple[T, int]] = Subject()
        self._replaced_subject: Subject[tuple[T, T, int]] = Subject()
        self._reset_subject: Subject[None] = Subject()
        # Property-changed subject (emits the property name as a string)
        self._prop_changed_subject: Subject[str] = Subject()

    # ── Observable properties ─────────────────────────────────────────────────

    @property
    def on_item_added(self) -> rx.Observable[tuple[T, int]]:
        """Hot observable: emits ``(item, index)`` on every add/insert."""
        return self._added_subject

    @property
    def on_item_removed(self) -> rx.Observable[tuple[T, int]]:
        """Hot observable: emits ``(item, index)`` (index before removal) on remove."""
        return self._removed_subject

    @property
    def on_item_replaced(self) -> rx.Observable[tuple[T, T, int]]:
        """Hot observable: emits ``(new_item, old_item, index)`` on replace."""
        return self._replaced_subject

    @property
    def on_reset(self) -> rx.Observable[None]:
        """Hot observable: emits ``None`` on clear or batch completion."""
        return self._reset_subject

    @property
    def on_property_changed(self) -> rx.Observable[str]:
        """Hot observable: emits the property name on every property change."""
        return self._prop_changed_subject

    # ── Count / indexing ──────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of items in the list."""
        return len(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        if isinstance(index, slice):
            return self._items[index]
        return self._items[index]

    # ── Mutations ─────────────────────────────────────────────────────────────

    def add(self, item: T) -> None:
        """Append *item* to the end of the list (alias for :meth:`append`)."""
        self.append(item)

    def append(self, item: T) -> None:
        """Append *item* to the end of the list."""
        index = len(self._items)
        self._items.append(item)
        self._on_added(item, index)

    def insert(self, index: int, item: T) -> None:
        """Insert *item* at *index*."""
        self._items.insert(index, item)
        self._on_added(item, index)

    def remove(self, item: T) -> bool:
        """Remove the first occurrence of *item*. Returns ``True`` if removed."""
        try:
            idx = self._items.index(item)
        except ValueError:
            return False
        del self._items[idx]
        self._on_removed(item, idx)
        return True

    def remove_at(self, index: int) -> None:
        """Remove the item at *index*."""
        item = self._items[index]
        del self._items[index]
        self._on_removed(item, index)

    def replace(self, index: int, new_item: T) -> None:
        """Replace the item at *index* with *new_item*."""
        old_item = self._items[index]
        self._items[index] = new_item
        self._on_replaced(new_item, old_item, index)

    def clear(self) -> None:
        """Remove all items and emit Reset."""
        self._items.clear()
        self._on_reset()

    # ── Batch update ──────────────────────────────────────────────────────────

    @contextmanager
    def batch_update(self) -> Generator[None, None, None]:
        """Context manager that suppresses granular events during the block.

        On exit of the outermost batch (ref-counted), a single ``Reset`` is
        emitted if any mutations occurred.
        """
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self._mutated_in_batch:
                self._mutated_in_batch = False
                self._reset_subject.on_next(None)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _on_added(self, item: T, index: int) -> None:
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._added_subject.on_next((item, index))
        self._prop_changed_subject.on_next("Count")

    def _on_removed(self, item: T, index: int) -> None:
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._removed_subject.on_next((item, index))
        self._prop_changed_subject.on_next("Count")

    def _on_replaced(self, new_item: T, old_item: T, index: int) -> None:
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._replaced_subject.on_next((new_item, old_item, index))
        # Count does not change on replace — no PropertyChanged("Count")

    def _on_reset(self) -> None:
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._reset_subject.on_next(None)

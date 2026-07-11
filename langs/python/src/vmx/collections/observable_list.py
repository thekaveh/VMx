"""ObservableList — granular per-mutation event observable list.

See spec/21-collections.md §3 and ADR-0026.
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex import operators as ops
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
        self._count_at_batch_start: int = 0
        self._disposed: bool = False

        # Granular event subjects
        self._added_subject: Subject[tuple[T, int]] = Subject()
        self._removed_subject: Subject[tuple[T, int]] = Subject()
        self._replaced_subject: Subject[tuple[T, T, int]] = Subject()
        self._reset_subject: Subject[None] = Subject()
        # Property-changed subject (emits the property name as a string)
        self._prop_changed_subject: Subject[str] = Subject()

    # ── Observable properties ─────────────────────────────────────────────────
    # Each Subject is sealed behind ``as_observable`` so external subscribers
    # can only subscribe — never ``on_next``/``dispose`` the internal stream and
    # corrupt other subscribers (VMX-013).

    @property
    def on_item_added(self) -> rx.Observable[tuple[T, int]]:
        """Hot observable: emits ``(item, index)`` on every add/insert."""
        return self._added_subject.pipe(ops.as_observable())

    @property
    def on_item_removed(self) -> rx.Observable[tuple[T, int]]:
        """Hot observable: emits ``(item, index)`` (index before removal) on remove."""
        return self._removed_subject.pipe(ops.as_observable())

    @property
    def on_item_replaced(self) -> rx.Observable[tuple[T, T, int]]:
        """Hot observable: emits ``(new_item, old_item, index)`` on replace."""
        return self._replaced_subject.pipe(ops.as_observable())

    @property
    def on_reset(self) -> rx.Observable[None]:
        """Hot observable: emits ``None`` on clear or batch completion."""
        return self._reset_subject.pipe(ops.as_observable())

    @property
    def on_property_changed(self) -> rx.Observable[str]:
        """Hot observable: emits the property name on every property change."""
        return self._prop_changed_subject.pipe(ops.as_observable())

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
        """Insert *item* at *index* (stdlib semantics: negative indexes count
        from the end; out-of-range indexes clamp like :meth:`list.insert`).
        """
        # Normalize before emitting: spec/21 §3.2 mandates the payload carry
        # the actual insertion index — a raw -1 (or an out-of-range 99 that
        # stdlib silently clamps to len) violates the contract.
        if index < 0:
            index = max(index + len(self._items), 0)
        elif index > len(self._items):
            index = len(self._items)
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
        """Remove the item at *index* (negative indexes count from the end)."""
        # Normalize before emitting: spec/21 §3.2 mandates the payload carry
        # the index *before removal* — a raw -1 violates the contract even
        # though negative indexing itself is Python-idiomatic (ADR-0006).
        if index < 0:
            index += len(self._items)
            if index < 0:
                raise IndexError("list index out of range")
        item = self._items[index]
        del self._items[index]
        self._on_removed(item, index)

    def replace(self, index: int, new_item: T) -> None:
        """Replace the item at *index* (negative indexes count from the end)."""
        if index < 0:
            index += len(self._items)
            if index < 0:
                raise IndexError("list index out of range")
        old_item = self._items[index]
        self._items[index] = new_item
        self._on_replaced(new_item, old_item, index)

    def replace_all(self, items: Iterable[T]) -> None:
        """Replace all contents from a snapshot and emit one reset.

        Empty-to-empty is the only no-op. Equal-length and element-for-element
        identical non-empty inputs still emit Reset without comparing elements.
        """
        snapshot = list(items)
        old_count = len(self._items)
        if old_count == 0 and not snapshot:
            return

        self._items[:] = snapshot
        self._on_reset()
        if old_count != len(snapshot) and self._batch_depth == 0 and not self._disposed:
            self._prop_changed_subject.on_next("Count")

    def clear(self) -> None:
        """Remove all items, emitting Reset then ``Count`` — but only when the
        list was non-empty. Clearing an already-empty list changes nothing and
        emits nothing (ADR-0037 §2.2, mirroring the empty-batch precedent)."""
        count_changed = bool(self._items)
        self._items.clear()
        # Clearing an empty list is a no-op: emit neither Reset nor Count.
        if count_changed:
            self._on_reset()
        # spec/21 §3.3: PropertyChanged("Count") fires after every mutation
        # that changes Count. Inside a batch the batch-exit path emits it.
        if count_changed and self._batch_depth == 0 and not self._disposed:
            self._prop_changed_subject.on_next("Count")

    # ── Batch update ──────────────────────────────────────────────────────────

    @contextmanager
    def batch_update(self) -> Generator[None, None, None]:
        """Context manager that suppresses granular events during the block.

        On exit of the outermost batch (ref-counted), a single ``Reset`` is
        emitted if any mutations occurred. If the count actually changed during
        the batch, a ``PropertyChanged("Count")`` is also emitted (spec §3.3).
        """
        if self._batch_depth == 0:
            self._count_at_batch_start = len(self._items)
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self._mutated_in_batch and not self._disposed:
                final_count = len(self._items)
                self._mutated_in_batch = False
                self._reset_subject.on_next(None)
                # Emit Count notification only if count actually changed (spec §3.3).
                if final_count != self._count_at_batch_start:
                    self._prop_changed_subject.on_next("Count")

    # ── Disposal ──────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Complete and dispose every backing Subject. Idempotent (VMX-096).

        After disposal the list no longer emits; subscribing to the (now
        completed) streams behaves like any disposed reactivex Subject.
        """
        if self._disposed:
            return
        self._disposed = True
        for subject in (
            self._added_subject,
            self._removed_subject,
            self._replaced_subject,
            self._reset_subject,
            self._prop_changed_subject,
        ):
            subject.on_completed()
            subject.dispose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _on_added(self, item: T, index: int) -> None:
        if self._disposed:
            return
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._added_subject.on_next((item, index))
        self._prop_changed_subject.on_next("Count")

    def _on_removed(self, item: T, index: int) -> None:
        if self._disposed:
            return
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._removed_subject.on_next((item, index))
        self._prop_changed_subject.on_next("Count")

    def _on_replaced(self, new_item: T, old_item: T, index: int) -> None:
        if self._disposed:
            return
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._replaced_subject.on_next((new_item, old_item, index))
        # Count does not change on replace — no PropertyChanged("Count")

    def _on_reset(self) -> None:
        if self._disposed:
            return
        if self._batch_depth > 0:
            self._mutated_in_batch = True
            return
        self._reset_subject.on_next(None)


class ReadOnlyObservableList(Generic[T]):
    """Read-only facade over an :class:`ObservableList`.

    Exposes the query surface (``count``, length, iteration, indexing,
    containment) and the granular observable streams, but **none** of the
    mutation methods. A consumer handed this view can observe the list but
    cannot mutate it — so it cannot desync state the owner maintains in lockstep
    (VMX-014). The view reads through to the live source, so it always reflects
    the current contents.
    """

    __slots__ = ("_source",)

    def __init__(self, source: ObservableList[T]) -> None:
        self._source = source

    # ── Query surface ─────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of items currently in the underlying list."""
        return self._source.count

    def __len__(self) -> int:
        return len(self._source)

    def __iter__(self) -> Iterator[T]:
        return iter(self._source)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        return self._source[index]

    def __contains__(self, item: object) -> bool:
        return any(item == existing for existing in self._source)

    # ── Observable surface (delegated; already sealed by the source) ───────────

    @property
    def on_item_added(self) -> rx.Observable[tuple[T, int]]:
        """Hot observable: emits ``(item, index)`` on every add/insert."""
        return self._source.on_item_added

    @property
    def on_item_removed(self) -> rx.Observable[tuple[T, int]]:
        """Hot observable: emits ``(item, index)`` on every remove."""
        return self._source.on_item_removed

    @property
    def on_item_replaced(self) -> rx.Observable[tuple[T, T, int]]:
        """Hot observable: emits ``(new_item, old_item, index)`` on replace."""
        return self._source.on_item_replaced

    @property
    def on_reset(self) -> rx.Observable[None]:
        """Hot observable: emits ``None`` on clear or batch completion."""
        return self._source.on_reset

    @property
    def on_property_changed(self) -> rx.Observable[str]:
        """Hot observable: emits the property name on every property change."""
        return self._source.on_property_changed

"""ServicedObservableCollection — observable list that optionally publishes to a hub.

See spec/21-collections.md §2 and ADR-0024.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, MutableSequence
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex import operators as ops
from reactivex.abc import DisposableBase
from reactivex.subject import Subject

from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHubProto

T = TypeVar("T")


class ServicedObservableCollection(MutableSequence[T], Generic[T]):
    """An observable list that optionally publishes :class:`CollectionChangedMessage`
    events to an :any:`MessageHub`-compatible hub.

    When *hub* is ``None`` the class behaves like a plain observable list — local
    ``on_collection_changed`` subscribers are notified on every mutation, but nothing
    is published to a hub.

    Ownership stays with the caller: removing, replacing, or clearing an item does
    not call ``dispose``/``destruct`` on that item.

    Parameters
    ----------
    hub:
        Optional hub.  Any object that exposes ``.send(message)`` is accepted.
        Pass ``None`` for standalone (no-publication) mode.
    """

    def __init__(
        self,
        hub: MessageHubProto[CollectionChangedMessage[T]] | None = None,
    ) -> None:
        self._hub = hub
        self._items: list[T] = []
        self._subject: Subject[CollectionChangedMessage[T]] = Subject()

    # ── Public surface ────────────────────────────────────────────────────────

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedMessage[T]]:
        """Hot observable of :class:`CollectionChangedMessage` events.

        The backing Subject is sealed behind ``as_observable`` so external
        subscribers can only subscribe — never ``on_next``/``dispose`` the
        internal stream (VMX-013).
        """
        return self._subject.pipe(ops.as_observable())

    def snapshot(self) -> tuple[T, ...]:
        """Return the current ordered membership snapshot."""
        return tuple(self._items)

    def subscribe_membership(self, callback: Callable[[], None]) -> DisposableBase:
        """Subscribe to payload-free structural membership pulses."""
        return self.on_collection_changed.subscribe(lambda _message: callback())

    # ── MutableSequence ABC ───────────────────────────────────────────────────

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

    @overload
    def __setitem__(self, index: int, value: T) -> None: ...

    @overload
    def __setitem__(self, index: slice, value: Iterable[T]) -> None: ...

    def __setitem__(self, index: int | slice, value: T | Iterable[T]) -> None:
        if isinstance(index, slice):
            # Slice replacement: emit reset (coarse-grained)
            items: Iterable[T] = value  # type: ignore[assignment]
            self._items[index] = list(items)
            self._emit(CollectionChangedMessage.for_reset(self))
        else:
            new_item: T = value  # type: ignore[assignment]
            self.replace(index, new_item)

    def __delitem__(self, index: int | slice) -> None:
        if isinstance(index, slice):
            del self._items[index]
            self._emit(CollectionChangedMessage.for_reset(self))
        else:
            self.remove_at(index)

    def insert(self, index: int, value: T) -> None:
        """Insert *value* before *index* (stdlib semantics: negative indexes
        count from the end; out-of-range indexes clamp like
        :meth:`list.insert`). The emitted payload carries the actual
        insertion index (spec/21 §3.2).
        """
        if index < 0:
            index = max(index + len(self._items), 0)
        elif index > len(self._items):
            index = len(self._items)
        self._items.insert(index, value)
        self._emit(CollectionChangedMessage.for_add(self, value, index))

    # Override append/clear for direct index access (insert would work too)

    def append(self, value: T) -> None:
        """Append *value* to the end of the collection."""
        index = len(self._items)
        self._items.append(value)
        self._emit(CollectionChangedMessage.for_add(self, value, index))

    def clear(self) -> None:
        """Remove all items and emit a Reset event."""
        if not self._items:
            return
        self._items.clear()
        self._emit(CollectionChangedMessage.for_reset(self))

    def remove(self, value: T) -> None:
        """Remove the first occurrence of *value*."""
        index = self._items.index(value)
        item = self._items[index]
        del self._items[index]
        self._emit(CollectionChangedMessage.for_remove(self, item, index))

    def remove_at(self, index: int) -> T:
        """Remove and return the item at *index* using Python index semantics."""
        item = self._items[index]
        resolved_index = index + len(self._items) if index < 0 else index
        del self._items[index]
        self._emit(CollectionChangedMessage.for_remove(self, item, resolved_index))
        return item

    def replace(self, index: int, new_item: T) -> T:
        """Replace the item at *index* and return the former item."""
        old_item = self._items[index]
        resolved_index = index + len(self._items) if index < 0 else index
        self._items[index] = new_item
        self._emit(CollectionChangedMessage.for_replace(self, new_item, old_item, resolved_index))
        return old_item

    def replace_all(self, values: Iterable[T]) -> None:
        """Replace all contents with a fully materialized snapshot of *values*."""
        replacement = list(values)
        if not self._items and not replacement:
            return
        self._items = replacement
        self._emit(CollectionChangedMessage.for_reset(self))

    def move(self, from_index: int, to_index: int) -> None:
        """Move one item between strict pre-move indices."""
        count = len(self._items)
        if from_index < 0 or from_index >= count or to_index < 0 or to_index >= count:
            raise IndexError("collection move index out of range")
        if from_index == to_index:
            return
        item = self._items.pop(from_index)
        self._items.insert(to_index, item)
        self._emit(CollectionChangedMessage.for_move(self, item, from_index, to_index))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _emit(self, msg: CollectionChangedMessage[T]) -> None:
        """Notify local observers then publish to hub (if present)."""
        # 1. Notify local on_collection_changed subscribers.
        self._subject.on_next(msg)
        # 2. Publish to hub (when one is wired).
        if self._hub is not None:
            self._hub.send(msg)

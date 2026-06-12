"""ServicedObservableCollection — observable list that optionally publishes to a hub.

See spec/21-collections.md §2 and ADR-0024.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, MutableSequence
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex.subject import Subject

from vmx.messages.collection_changed import CollectionChangedMessage

T = TypeVar("T")


class ServicedObservableCollection(MutableSequence[T], Generic[T]):
    """An observable list that optionally publishes :class:`CollectionChangedMessage`
    events to an :any:`MessageHub`-compatible hub.

    When *hub* is ``None`` the class behaves like a plain observable list — local
    ``on_collection_changed`` subscribers are notified on every mutation, but nothing
    is published to a hub.

    Parameters
    ----------
    hub:
        Optional hub.  Any object that exposes ``.send(message)`` is accepted.
        Pass ``None`` for standalone (no-publication) mode.
    """

    def __init__(
        self,
        hub: object = None,
    ) -> None:
        self._hub = hub
        self._items: list[T] = []
        self._subject: Subject[CollectionChangedMessage[T]] = Subject()

    # ── Public surface ────────────────────────────────────────────────────────

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedMessage[T]]:
        """Hot observable of :class:`CollectionChangedMessage` events."""
        return self._subject

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
            old_item: T = self._items[index]
            new_item: T = value  # type: ignore[assignment]
            self._items[index] = new_item
            self._emit(CollectionChangedMessage.for_replace(self, new_item, old_item, index))

    def __delitem__(self, index: int | slice) -> None:
        if isinstance(index, slice):
            del self._items[index]
            self._emit(CollectionChangedMessage.for_reset(self))
        else:
            item: T = self._items[index]
            del self._items[index]
            self._emit(CollectionChangedMessage.for_remove(self, item, index))

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
        self._items.clear()
        self._emit(CollectionChangedMessage.for_reset(self))

    def remove(self, value: T) -> None:
        """Remove the first occurrence of *value*."""
        index = self._items.index(value)
        del self._items[index]
        self._emit(CollectionChangedMessage.for_remove(self, value, index))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _emit(self, msg: CollectionChangedMessage[T]) -> None:
        """Notify local observers then publish to hub (if present)."""
        # 1. Notify local on_collection_changed subscribers.
        self._subject.on_next(msg)
        # 2. Publish to hub (when one is wired).
        if self._hub is not None:
            send: Callable[[CollectionChangedMessage[T]], None] = self._hub.send  # type: ignore[attr-defined]
            send(msg)

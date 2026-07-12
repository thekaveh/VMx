"""Ordered serviced collection with captured, unique-key lookup.

See spec/21-collections.md sections 2.8-2.15 and ADR-0097.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator, MutableSequence
from typing import Generic, TypeVar, overload

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHubProto

TKey = TypeVar("TKey", bound=Hashable)
T = TypeVar("T")


class KeyedServicedObservableCollection(MutableSequence[T], Generic[TKey, T]):
    """A caller-owned ordered collection with expected-O(1) key lookup.

    ``key_of`` runs only when a candidate membership is introduced or
    explicitly replaced. Its result is captured for that membership, so later
    lookup, movement, and removal never reproject stored items.
    """

    def __init__(
        self,
        key_of: Callable[[T], TKey],
        hub: MessageHubProto[CollectionChangedMessage[T]] | None = None,
    ) -> None:
        self._key_of = key_of
        self._hub = hub
        self._items: list[T] = []
        self._keys: list[TKey] = []
        self._index_by_key: dict[TKey, int] = {}
        self._subject: Subject[CollectionChangedMessage[T]] = Subject()

    @property
    def on_collection_changed(self) -> rx.Observable[CollectionChangedMessage[T]]:
        """Hot, read-only stream of committed collection changes."""
        return self._subject.pipe(ops.as_observable())

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
        if not isinstance(index, slice):
            new_item: T = value  # type: ignore[assignment]
            self.replace(index, new_item)
            return

        inserted: Iterable[T] = value  # type: ignore[assignment]
        inserted_items = list(inserted)
        inserted_keys = [self._key_of(item) for item in inserted_items]
        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()

        # Native list assignment performs slice normalization and enforces
        # extended-slice cardinality entirely on disposable candidate state.
        candidate_items[index] = inserted_items
        candidate_keys[index] = inserted_keys
        candidate_index = self._build_index(candidate_keys)

        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_reset(self))

    def __delitem__(self, index: int | slice) -> None:
        if not isinstance(index, slice):
            self.remove_at(index)
            return

        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()
        del candidate_items[index]
        del candidate_keys[index]
        candidate_index = self._build_index(candidate_keys)

        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_reset(self))

    def get(self, key: TKey) -> T | None:
        """Return the item captured under ``key``, or ``None`` on a miss."""
        index = self._index_by_key.get(key)
        return None if index is None else self._items[index]

    def contains_key(self, key: TKey) -> bool:
        """Return whether a membership captured ``key``."""
        return key in self._index_by_key

    def insert(self, index: int, value: T) -> None:
        """Insert using native ``list.insert`` index normalization."""
        resolved_index = self._normalize_insert_index(index)
        key = self._key_of(value)
        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()
        candidate_items.insert(resolved_index, value)
        candidate_keys.insert(resolved_index, key)
        candidate_index = self._build_index(candidate_keys)

        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_add(self, value, resolved_index))

    def append(self, value: T) -> None:
        """Append one uniquely keyed membership."""
        self.insert(len(self._items), value)

    def clear(self) -> None:
        """Remove every membership without managing any item lifecycle."""
        if not self._items:
            return
        self._commit([], [], {})
        self._emit(CollectionChangedMessage.for_reset(self))

    def remove(self, value: T) -> None:
        """Remove the first equal item, using its captured key."""
        self.remove_at(self._items.index(value))

    def remove_at(self, index: int) -> T:
        """Remove and return one item using Python integer-index semantics."""
        resolved_index = self._resolve_index(index)
        item = self._items[resolved_index]
        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()
        del candidate_items[resolved_index]
        del candidate_keys[resolved_index]
        candidate_index = self._build_index(candidate_keys)

        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_remove(self, item, resolved_index))
        return item

    def replace(self, index: int, new_item: T) -> T:
        """Replace one membership, explicitly recapturing its projected key."""
        resolved_index = self._resolve_index(index)
        old_item = self._items[resolved_index]
        new_key = self._key_of(new_item)
        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()
        candidate_items[resolved_index] = new_item
        candidate_keys[resolved_index] = new_key
        candidate_index = self._build_index(candidate_keys)

        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_replace(self, new_item, old_item, resolved_index))
        return old_item

    def replace_all(self, values: Iterable[T]) -> None:
        """Atomically install a fully materialized, uniquely keyed snapshot."""
        replacement = list(values)
        replacement_keys = [self._key_of(item) for item in replacement]
        replacement_index = self._build_index(replacement_keys)
        if not self._items and not replacement:
            return

        self._commit(replacement, replacement_keys, replacement_index)
        self._emit(CollectionChangedMessage.for_reset(self))

    def move(self, from_index: int, to_index: int) -> None:
        """Move one item between strict, non-negative pre-move indices."""
        count = len(self._items)
        if from_index < 0 or from_index >= count or to_index < 0 or to_index >= count:
            raise IndexError("collection move index out of range")
        if from_index == to_index:
            return

        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()
        item = candidate_items.pop(from_index)
        key = candidate_keys.pop(from_index)
        candidate_items.insert(to_index, item)
        candidate_keys.insert(to_index, key)
        candidate_index = self._build_index(candidate_keys)

        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_move(self, item, from_index, to_index))

    def upsert(self, item: T) -> bool:
        """Append a missing key or replace its stable position.

        Returns ``True`` for Add and ``False`` for Replace.
        """
        key = self._key_of(item)
        index = self._index_by_key.get(key)
        if index is None:
            candidate_items = [*self._items, item]
            candidate_keys = [*self._keys, key]
            candidate_index = self._build_index(candidate_keys)
            insertion_index = len(self._items)
            self._commit(candidate_items, candidate_keys, candidate_index)
            self._emit(CollectionChangedMessage.for_add(self, item, insertion_index))
            return True

        old_item = self._items[index]
        candidate_items = self._items.copy()
        candidate_keys = self._keys.copy()
        candidate_items[index] = item
        candidate_keys[index] = key
        candidate_index = self._build_index(candidate_keys)
        self._commit(candidate_items, candidate_keys, candidate_index)
        self._emit(CollectionChangedMessage.for_replace(self, item, old_item, index))
        return False

    def delete(self, key: TKey) -> bool:
        """Delete a captured key, returning whether it existed."""
        index = self._index_by_key.get(key)
        if index is None:
            return False
        self.remove_at(index)
        return True

    def _normalize_insert_index(self, index: int) -> int:
        if index < 0:
            return max(index + len(self._items), 0)
        return min(index, len(self._items))

    def _resolve_index(self, index: int) -> int:
        # Indexing first preserves Python's exact bounds behavior and ensures an
        # invalid target never invokes the user projector.
        self._items[index]
        return index + len(self._items) if index < 0 else index

    def _build_index(self, keys: list[TKey]) -> dict[TKey, int]:
        result: dict[TKey, int] = {}
        for index, key in enumerate(keys):
            if key in result:
                raise ValueError("duplicate key in KeyedServicedObservableCollection")
            result[key] = index
        return result

    def _commit(
        self,
        items: list[T],
        keys: list[TKey],
        index_by_key: dict[TKey, int],
    ) -> None:
        self._items = items
        self._keys = keys
        self._index_by_key = index_by_key

    def _emit(self, message: CollectionChangedMessage[T]) -> None:
        self._subject.on_next(message)
        if self._hub is not None:
            self._hub.send(message)

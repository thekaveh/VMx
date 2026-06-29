"""ObservableDictionary — two-key observable dictionary.

See spec/21-collections.md §4 and ADR-0025.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.collections.observable_list import ObservableList, ReadOnlyObservableList
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHubProto

TKey1 = TypeVar("TKey1")
TKey2 = TypeVar("TKey2")
TValue = TypeVar("TValue")


class ObservableDictionary(Generic[TKey1, TKey2, TValue]):
    """A two-key observable dictionary with distinct-key observable views.

    Entries are stored in insertion order. Four observables surface mutations:

    - ``on_item_added``    — ``Observable[tuple[TKey1, TKey2, TValue]]``
    - ``on_item_removed``  — ``Observable[tuple[TKey1, TKey2, TValue]]``
    - ``on_item_replaced`` — ``Observable[tuple[TKey1, TKey2, TValue, TValue]]``
      emits ``(key1, key2, new_value, old_value)``
    - ``on_reset``         — ``Observable[None]`` — fired by :meth:`clear`

    ``keys1`` and ``keys2`` are live :class:`ObservableList` views of the
    distinct Key1 / Key2 values currently present, in insertion order of
    their first appearance.

    Null (``None``) keys are not permitted; a :class:`TypeError` is raised.

    When *hub* is provided every mutation also publishes a
    :class:`~vmx.messages.collection_changed.CollectionChangedMessage` to the hub
    (local granular event fires first, then hub publication — same thread).

    See spec/21-collections.md §4 and ADR-0025.
    """

    def __init__(
        self, hub: MessageHubProto[CollectionChangedMessage[object]] | None = None
    ) -> None:
        # Optional hub — a MessageHub-compatible pub/sub sink.
        self._hub = hub
        self._disposed: bool = False

        # Insertion-ordered backing: list for order, dict for O(1) lookup.
        self._key_order: list[tuple[TKey1, TKey2]] = []
        self._data: dict[tuple[TKey1, TKey2], TValue] = {}

        # Distinct-key observable views (mutated internally to stay in lockstep
        # with the entries). The public ``keys1``/``keys2`` hand out read-only
        # facades so a caller cannot mutate them and desync the key axis
        # (VMX-014).
        self._keys1: ObservableList[TKey1] = ObservableList()
        self._keys2: ObservableList[TKey2] = ObservableList()
        self._keys1_view: ReadOnlyObservableList[TKey1] = ReadOnlyObservableList(self._keys1)
        self._keys2_view: ReadOnlyObservableList[TKey2] = ReadOnlyObservableList(self._keys2)

        # Event subjects
        self._added_subject: Subject[tuple[TKey1, TKey2, TValue]] = Subject()
        self._removed_subject: Subject[tuple[TKey1, TKey2, TValue]] = Subject()
        self._replaced_subject: Subject[tuple[TKey1, TKey2, TValue, TValue]] = Subject()
        self._reset_subject: Subject[None] = Subject()

    # ── Observable properties ─────────────────────────────────────────────────
    # Each Subject is sealed behind ``as_observable`` so external subscribers can
    # only subscribe — never ``on_next``/``dispose`` the internal stream
    # (VMX-013).

    @property
    def on_item_added(self) -> rx.Observable[tuple[TKey1, TKey2, TValue]]:
        """Hot observable: emits ``(key1, key2, value)`` on every insert."""
        return self._added_subject.pipe(ops.as_observable())

    @property
    def on_item_removed(self) -> rx.Observable[tuple[TKey1, TKey2, TValue]]:
        """Hot observable: emits ``(key1, key2, value)`` on every remove."""
        return self._removed_subject.pipe(ops.as_observable())

    @property
    def on_item_replaced(
        self,
    ) -> rx.Observable[tuple[TKey1, TKey2, TValue, TValue]]:
        """Hot observable: emits ``(key1, key2, new_value, old_value)`` on replace."""
        return self._replaced_subject.pipe(ops.as_observable())

    @property
    def on_reset(self) -> rx.Observable[None]:
        """Hot observable: emits ``None`` on :meth:`clear`."""
        return self._reset_subject.pipe(ops.as_observable())

    # ── Distinct-key views ────────────────────────────────────────────────────

    @property
    def keys1(self) -> ReadOnlyObservableList[TKey1]:
        """Read-only observable view of distinct Key1 values, in insertion order.

        The view reflects the live key axis but exposes no mutators, so a caller
        cannot desync it from the entries (VMX-014).
        """
        return self._keys1_view

    @property
    def keys2(self) -> ReadOnlyObservableList[TKey2]:
        """Read-only observable view of distinct Key2 values, in insertion order.

        The view reflects the live key axis but exposes no mutators, so a caller
        cannot desync it from the entries (VMX-014).
        """
        return self._keys2_view

    # ── Count / containment ───────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Total number of entries."""
        return len(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def contains_key(self, key1: TKey1, key2: TKey2) -> bool:
        """Return ``True`` if an entry exists for ``(key1, key2)``."""
        if key1 is None:
            raise TypeError("key1 must not be None")
        if key2 is None:
            raise TypeError("key2 must not be None")
        return (key1, key2) in self._data

    def __contains__(self, key: object) -> bool:
        """Support ``(k1, k2) in d`` membership test."""
        if not isinstance(key, tuple) or len(key) != 2:
            return False
        k1, k2 = key
        return (k1, k2) in self._data

    # ── Item access ───────────────────────────────────────────────────────────

    def get(self, key1: TKey1, key2: TKey2) -> TValue:
        """Return the value for ``(key1, key2)``.

        Raises :class:`KeyError` if absent.
        """
        if key1 is None:
            raise TypeError("key1 must not be None")
        if key2 is None:
            raise TypeError("key2 must not be None")
        return self._data[(key1, key2)]

    def try_get_value(self, key1: TKey1, key2: TKey2) -> tuple[bool, TValue | None]:
        """Try to get the value for ``(key1, key2)``.

        Returns ``(True, value)`` if found, ``(False, None)`` if absent.
        Equivalent to :meth:`get` plus try/except but without raising.
        """
        if key1 is None:
            raise TypeError("key1 must not be None")
        if key2 is None:
            raise TypeError("key2 must not be None")
        value = self._data.get((key1, key2))
        if value is not None or (key1, key2) in self._data:
            return True, value
        return False, None

    def __getitem__(self, key: tuple[TKey1, TKey2]) -> TValue:
        k1, k2 = key
        return self._data[(k1, k2)]

    def __setitem__(self, key: tuple[TKey1, TKey2], value: TValue) -> None:
        k1, k2 = key
        if k1 is None:
            raise TypeError("key1 must not be None")
        if k2 is None:
            raise TypeError("key2 must not be None")
        if (k1, k2) in self._data:
            old = self._data[(k1, k2)]
            self._data[(k1, k2)] = value
            self._on_replaced(k1, k2, value, old)
        else:
            self._internal_add(k1, k2, value)

    # ── Mutations ─────────────────────────────────────────────────────────────

    def add(self, key1: TKey1, key2: TKey2, value: TValue) -> None:
        """Insert a new entry.

        Raises :class:`KeyError` if ``(key1, key2)`` already exists.
        """
        if key1 is None:
            raise TypeError("key1 must not be None")
        if key2 is None:
            raise TypeError("key2 must not be None")
        if (key1, key2) in self._data:
            raise KeyError(f"Key ({key1!r}, {key2!r}) already exists")
        self._internal_add(key1, key2, value)

    def remove(self, key1: TKey1, key2: TKey2) -> bool:
        """Remove entry for ``(key1, key2)``.

        Returns ``True`` if the entry was found and removed, ``False`` otherwise.
        """
        if key1 is None:
            raise TypeError("key1 must not be None")
        if key2 is None:
            raise TypeError("key2 must not be None")
        if (key1, key2) not in self._data:
            return False

        value = self._data.pop((key1, key2))
        self._key_order.remove((key1, key2))

        # Update key-axis views: drop only when no other entry uses this key.
        if not any(k[0] == key1 for k in self._data):
            self._keys1.remove(key1)
        if not any(k[1] == key2 for k in self._data):
            self._keys2.remove(key2)

        self._on_removed(key1, key2, value)
        return True

    def __delitem__(self, key: tuple[TKey1, TKey2]) -> None:
        k1, k2 = key
        if not self.remove(k1, k2):
            raise KeyError(key)

    def clear(self) -> None:
        """Remove all entries and emit on_reset. Does NOT fire per-entry events."""
        self._data.clear()
        self._key_order.clear()
        self._keys1.clear()
        self._keys2.clear()
        self._on_reset()

    # ── Enumeration ───────────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[tuple[TKey1, TKey2, TValue]]:
        """Iterate entries as ``(key1, key2, value)`` triples in insertion order."""
        for k1, k2 in self._key_order:
            yield k1, k2, self._data[(k1, k2)]

    def items(self) -> Iterator[tuple[TKey1, TKey2, TValue]]:
        """Iterate entries as ``(key1, key2, value)`` triples in insertion order."""
        return iter(self)

    # ── Disposal ──────────────────────────────────────────────────────────────

    def dispose(self) -> None:
        """Complete and dispose every backing Subject (and the key views).

        Idempotent (VMX-096).
        """
        if self._disposed:
            return
        self._disposed = True
        for subject in (
            self._added_subject,
            self._removed_subject,
            self._replaced_subject,
            self._reset_subject,
        ):
            subject.on_completed()
            subject.dispose()
        self._keys1.dispose()
        self._keys2.dispose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _internal_add(self, key1: TKey1, key2: TKey2, value: TValue) -> None:
        self._key_order.append((key1, key2))
        self._data[(key1, key2)] = value

        # Update key-axis views on first appearance only.
        if not self._keys1_contains(key1):
            self._keys1.add(key1)
        if not self._keys2_contains(key2):
            self._keys2.add(key2)

        self._on_added(key1, key2, value)

    def _keys1_contains(self, key1: TKey1) -> bool:
        # ObservableList does not expose __contains__; iterate to check.
        return any(k == key1 for k in self._keys1)

    def _keys2_contains(self, key2: TKey2) -> bool:
        return any(k == key2 for k in self._keys2)

    def _publish_to_hub(self, msg: CollectionChangedMessage[object]) -> None:
        """Send *msg* to the hub if one is wired (no-op otherwise)."""
        if self._hub is not None:
            self._hub.send(msg)

    def _on_added(self, key1: TKey1, key2: TKey2, value: TValue) -> None:
        # 1. Local granular event first.
        self._added_subject.on_next((key1, key2, value))
        # 2. Publish to hub (if present).
        self._publish_to_hub(
            CollectionChangedMessage.for_add(self, (key1, key2, value), len(self._key_order) - 1)
        )

    def _on_removed(self, key1: TKey1, key2: TKey2, value: TValue) -> None:
        # 1. Local granular event first.
        self._removed_subject.on_next((key1, key2, value))
        # 2. Publish to hub (if present).
        self._publish_to_hub(CollectionChangedMessage.for_remove(self, (key1, key2, value), -1))

    def _on_replaced(self, key1: TKey1, key2: TKey2, new_value: TValue, old_value: TValue) -> None:
        # 1. Local granular event first.
        self._replaced_subject.on_next((key1, key2, new_value, old_value))
        # 2. Publish to hub (if present).
        self._publish_to_hub(
            CollectionChangedMessage.for_replace(
                self, (key1, key2, new_value), (key1, key2, old_value), -1
            )
        )

    def _on_reset(self) -> None:
        # 1. Local event first.
        self._reset_subject.on_next(None)
        # 2. Publish to hub (if present).
        self._publish_to_hub(CollectionChangedMessage.for_reset(self))

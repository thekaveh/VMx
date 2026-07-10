"""Canonical CollectionChangedEvent payload shared by composites and groups."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class CollectionChangedEvent:
    """Immutable payload emitted on collection mutations.

    Mirrors WPF's ``NotifyCollectionChangedEventArgs`` shape. The ``action``
    field is one of ``"add"``, ``"remove"``, ``"move"`` or ``"reset"``. Indexer assignment
    is decomposed into a Remove followed by an Add.
    """

    action: str
    new_items: tuple[object, ...] = ()
    new_index: int = -1
    old_items: tuple[object, ...] = ()
    old_index: int = -1

"""Cross-container collection-change event payload.

Both :class:`vmx.composites.CompositeVM` and :class:`vmx.groups.GroupVM` emit
:class:`CollectionChangedEvent` on their ``on_collection_changed`` Observable.
The schema mirrors WPF's ``NotifyCollectionChangedEventArgs``.
"""

from __future__ import annotations

from vmx.collections.collection_changed import CollectionChangedEvent

__all__ = ["CollectionChangedEvent"]

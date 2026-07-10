"""Cross-container collection-change event payload + batch-update handle.

Both :class:`vmx.composites.CompositeVM` and :class:`vmx.groups.GroupVM` emit
:class:`CollectionChangedEvent` on their ``on_collection_changed`` Observable.
The schema mirrors WPF's ``NotifyCollectionChangedEventArgs``.

:class:`ServicedObservableCollection` is a standalone observable list that
optionally publishes :class:`CollectionChangedMessage` events to a hub.
See spec/21-collections.md §2 and ADR-0024.

:class:`ObservableList` is a standalone observable list with granular per-mutation
events. See spec/21-collections.md §3 and ADR-0026.

:class:`ObservableDictionary` is a two-key observable dictionary with distinct-key
observable views. See spec/21-collections.md §4 and ADR-0025.
"""

from __future__ import annotations

from vmx.collections.batch import BatchUpdateHandle
from vmx.collections.collection_changed import CollectionChangedEvent
from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.collections.observable_list import ObservableList
from vmx.collections.paged_composition import PagedComposition
from vmx.collections.protocols import SelectableVmCollectionProto, VmCollectionProto
from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.collections.token_paged_composition import TokenPagedComposition

__all__ = [
    "BatchUpdateHandle",
    "CollectionChangedEvent",
    "ObservableDictionary",
    "ObservableList",
    "PagedComposition",
    "SelectableVmCollectionProto",
    "ServicedObservableCollection",
    "TokenPagedComposition",
    "VmCollectionProto",
]

"""Message protocols and concrete messages.

Public API
----------
- :class:`Message` — base protocol (sender_name, sender_object)
- :class:`TypedMessage` — generic protocol adding typed sender
- :class:`PropertyChangedMessage` — emitted when a VM property changes value
- :class:`ConstructionStatusChangedMessage` — emitted on lifecycle transitions
- :class:`CollectionChangedMessage` — emitted by ServicedObservableCollection
- :class:`TreeStructureChangedMessage` — emitted on HierarchicalVM structural mutations
- :class:`TreeStructureChange` — enum for tree mutation kind (ADDED / REMOVED / REPARENTED)
"""

from __future__ import annotations

from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.messages.construction_status import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import (
    ConstructionStatusChangedMessageProto,
    Message,
    PropertyChangedMessageProto,
    TypedMessage,
)
from vmx.messages.tree_structure_changed import TreeStructureChange, TreeStructureChangedMessage

__all__ = [
    "CollectionChangedMessage",
    "ConstructionStatusChangedMessage",
    "ConstructionStatusChangedMessageProto",
    "Message",
    "PropertyChangedMessage",
    "PropertyChangedMessageProto",
    "TreeStructureChange",
    "TreeStructureChangedMessage",
    "TypedMessage",
]

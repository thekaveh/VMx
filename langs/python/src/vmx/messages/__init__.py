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
- :class:`FormRevertedMessage` — emitted when a FormVM reverts its Model to Snapshot
- :func:`property_value_changed_messages_for` — convenience helper returning an
  ``Observable[Any]`` of property values rather than full message envelopes (ADR-0032)
"""

from __future__ import annotations

from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.form_reverted import FormRevertedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.property_value_changed import property_value_changed_messages_for
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
    "FormRevertedMessage",
    "Message",
    "PropertyChangedMessage",
    "PropertyChangedMessageProto",
    "TreeStructureChange",
    "TreeStructureChangedMessage",
    "TypedMessage",
    "property_value_changed_messages_for",
]

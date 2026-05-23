"""Message protocols and concrete messages.

Public API
----------
- :class:`Message` — base protocol (sender_name, sender_object)
- :class:`TypedMessage` — generic protocol adding typed sender
- :class:`PropertyChangedMessage` — emitted when a VM property changes value
- :class:`ConstructionStatusChangedMessage` — emitted on lifecycle transitions
"""

from __future__ import annotations

from vmx.messages.construction_status import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import (
    ConstructionStatusChangedMessageProto,
    Message,
    PropertyChangedMessageProto,
    TypedMessage,
)

__all__ = [
    "ConstructionStatusChangedMessage",
    "ConstructionStatusChangedMessageProto",
    "Message",
    "PropertyChangedMessage",
    "PropertyChangedMessageProto",
    "TypedMessage",
]

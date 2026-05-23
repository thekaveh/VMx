"""PropertyChangedMessage — emitted when a VM property changes value.

See spec/03-messages.md §PropertyChangedMessage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

TSender = TypeVar("TSender")


@dataclass(frozen=True, slots=True)
class PropertyChangedMessage(Generic[TSender]):
    """Immutable message emitted when a property's setter accepts a new value.

    Parameters
    ----------
    sender:
        Strongly-typed sender instance.
    sender_name:
        Human-readable sender identifier (typically ``sender.name``).
    property_name:
        Name of the property whose value changed.
    """

    sender: TSender
    sender_name: str
    property_name: str

    @property
    def sender_object(self) -> object:
        """Return the sender as an untyped object (satisfies Message protocol)."""
        return self.sender

    @classmethod
    def create(
        cls,
        sender: TSender,
        sender_name: str,
        property_name: str,
    ) -> PropertyChangedMessage[TSender]:
        """Factory method — equivalent to direct construction."""
        return cls(sender=sender, sender_name=sender_name, property_name=property_name)

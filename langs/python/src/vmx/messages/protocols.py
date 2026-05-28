from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from vmx.lifecycle.status import ConstructionStatus

TSender = TypeVar("TSender", covariant=True)


@runtime_checkable
class Message(Protocol):
    """Protocol for all VMx hub messages. See spec/03-messages.md."""

    @property
    def sender_name(self) -> str:
        """Should return the sender's name as a string."""
        ...

    @property
    def sender_object(self) -> object:
        """Should return the sender object."""
        ...


@runtime_checkable
class TypedMessage(Message, Protocol, Generic[TSender]):
    """Typed hub message protocol carrying a strongly-typed Sender.

    See spec/03-messages.md §IMessage shape.
    """

    @property
    def sender(self) -> TSender:
        """Should return the sender, typed according to the Sender type variable."""
        ...


@runtime_checkable
class PropertyChangedMessageProto(TypedMessage[TSender], Protocol[TSender]):
    """Protocol for property-changed messages."""

    @property
    def property_name(self) -> str:
        """Name of the property whose value changed."""
        ...


@runtime_checkable
class ConstructionStatusChangedMessageProto(Message, Protocol):
    """Protocol for construction-status-changed messages."""

    @property
    def status(self) -> ConstructionStatus:
        """The new ConstructionStatus after the transition."""
        ...

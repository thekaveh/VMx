from typing import Protocol, runtime_checkable, TypeVar, Generic

Sender = TypeVar("Sender", covariant=True)


@runtime_checkable
class Message(Protocol):
    @property
    def sender_name(self) -> str:
        """Should return the sender's name as a string."""
        pass

    @property
    def sender_object(self) -> object:
        """Should return the sender object."""
        pass


@runtime_checkable
class TypedMessage(Message, Protocol, Generic[Sender]):
    @property
    def sender(self) -> Sender:
        """Should return the sender, typed according to the Sender type variable."""
        pass

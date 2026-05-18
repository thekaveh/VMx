"""Message hub protocol.

The concrete `MessageHub` implementation arrives in Phase 3 (see the design spec).
This file currently only declares the Protocol that consumers code against.
"""

from typing import Protocol, TypeVar, runtime_checkable

from reactivex import Observable

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", contravariant=True)


@runtime_checkable
class MessageHub(Protocol[TMessage]):
    @property
    def messages(self) -> Observable[Message]:
        """Provides an Observable stream of messages."""
        ...

    def send(self, message: TMessage) -> None:
        """Sends a message of type TMessage."""
        ...

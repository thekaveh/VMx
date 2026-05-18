from typing import TypeVar, Protocol, runtime_checkable
from rx.core.observable.observable import Observable

from messages.contracts.message import Message

TMessage = TypeVar("TMessage", contravariant=True)


@runtime_checkable
class MessageHub(Protocol[TMessage]):
    @property
    def messages(self) -> Observable:
        """Provides an Observable stream of messages."""
        pass

    def send(self, message: TMessage) -> None:
        """Sends a message of type TMessage."""
        pass

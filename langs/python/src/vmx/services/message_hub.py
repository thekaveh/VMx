"""Message hub — Protocol and concrete Subject-backed implementation."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

import reactivex as rx
from reactivex.abc import DisposableBase, ObserverBase
from reactivex.subject import Subject

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", bound=Message, contravariant=True)


@runtime_checkable
class MessageHubProto(Protocol[TMessage]):
    """Hot pub/sub stream for IMessage events.

    Structural Protocol — any class that provides ``.messages`` and ``.send()``
    satisfies this interface without explicit inheritance.
    """

    @property
    def messages(self) -> rx.Observable[Message]:
        """Observable stream of all messages published to this hub."""
        ...

    def send(self, message: TMessage) -> None:
        """Publish *message* to all current subscribers."""
        ...


_THubMessage = TypeVar("_THubMessage", bound=Message)


class MessageHub(Generic[_THubMessage]):
    """Default Subject-backed hub.  Hot stream — no replay buffer.

    Subscriber-handler exceptions are isolated per-subscription so a raising
    handler does not terminate the stream for other subscribers (HUB-007).
    """

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()
        self._disposed: bool = False

    @property
    def messages(self) -> rx.Observable[Message]:
        """Per HUB-007: wrap each subscription so exceptions are swallowed."""
        return rx.create(self._subscribe_safely)

    def _subscribe_safely(
        self,
        observer: ObserverBase[Message],
        scheduler: object = None,
    ) -> DisposableBase:
        def on_next(value: Message) -> None:
            try:
                observer.on_next(value)
            except Exception:
                pass  # swallow — spec/03-messages.md §Subscriber resilience

        return self._subject.subscribe(
            on_next=on_next,
            on_error=observer.on_error,
            on_completed=observer.on_completed,
        )

    def send(self, message: _THubMessage) -> None:
        """Publish *message* synchronously to all current subscribers."""
        if self._disposed:
            return
        self._subject.on_next(message)

    def dispose(self) -> None:
        """Complete and dispose the underlying subject."""
        if self._disposed:
            return
        self._disposed = True
        self._subject.on_completed()
        self._subject.dispose()

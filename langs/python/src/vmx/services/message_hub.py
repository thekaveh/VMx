"""Message hub — Protocol and concrete Subject-backed implementation."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from threading import RLock
from typing import Generic, Protocol, TypeVar, runtime_checkable

import reactivex as rx
from reactivex.abc import DisposableBase, ObserverBase
from reactivex.subject import Subject

from vmx.messages.protocols import Message

_logger = logging.getLogger(__name__)

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


@runtime_checkable
class TransactionalMessageHubProto(MessageHubProto[TMessage], Protocol[TMessage]):
    """Additive capability for hubs that support message transactions."""

    def batch(self) -> AbstractContextManager[None]:
        """Return a synchronous, nestable message transaction scope."""
        ...


_THubMessage = TypeVar("_THubMessage", bound=Message)


class MessageHub(Generic[_THubMessage]):
    """Default Subject-backed hub.  Hot stream — no replay buffer.

    Subscriber-handler exceptions are isolated per-subscription so a raising
    handler does not terminate the stream for other subscribers (HUB-007).
    """

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()
        self._gate = RLock()
        self._pending: deque[Message] = deque()
        self._disposed: bool = False
        self._draining = False
        self._batch_depth = 0

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
                # Isolate the failing subscriber (HUB-007): the exception is
                # swallowed so it cannot terminate the stream for other
                # subscribers (spec/03-messages.md §Subscriber resilience). It
                # is logged (not silently discarded) so the failure is still
                # observable to operators via the logging framework.
                _logger.exception(
                    "MessageHub subscriber raised while handling %r; isolating per HUB-007",
                    type(value).__name__,
                )

        return self._subject.subscribe(
            on_next=on_next,
            on_error=observer.on_error,
            on_completed=observer.on_completed,
        )

    def send(self, message: _THubMessage) -> None:
        """Publish *message* synchronously to all current subscribers."""
        with self._gate:
            if self._disposed:
                return
            self._pending.append(message)
            if self._batch_depth == 0 and not self._draining:
                self._drain()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Defer messages until the outermost transaction scope exits."""
        self._gate.acquire()
        self._batch_depth += 1
        try:
            try:
                yield
            except BaseException:
                self._batch_depth -= 1
                try:
                    if self._batch_depth == 0 and not self._disposed and not self._draining:
                        self._drain()
                except BaseException:
                    pass  # the transaction body's original error takes precedence
                raise
            else:
                self._batch_depth -= 1
                if self._batch_depth == 0 and not self._disposed and not self._draining:
                    self._drain()
        finally:
            self._gate.release()

    def _drain(self) -> None:
        self._draining = True
        delivered = 0
        message_types: set[str] = set()
        try:
            while not self._disposed and self._pending:
                message = self._pending.popleft()
                if __debug__:
                    message_types.add(type(message).__name__)
                self._subject.on_next(message)
                if __debug__:
                    delivered += 1
                    if delivered >= 10_000 and self._pending:
                        message_types.update(type(item).__name__ for item in self._pending)
                        self._pending.clear()
                        names = ", ".join(sorted(message_types))
                        raise RuntimeError(
                            "MessageHub drain exceeded 10000 messages; "
                            f"possible publish cycle involving: {names}"
                        )
        finally:
            self._draining = False

    def dispose(self) -> None:
        """Complete and dispose the underlying subject."""
        with self._gate:
            if self._disposed:
                return
            self._disposed = True
            self._pending.clear()
            self._subject.on_completed()
            self._subject.dispose()

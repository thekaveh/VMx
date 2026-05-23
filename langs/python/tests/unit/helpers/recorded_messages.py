"""Test helper: subscribe to an Observable[Message] and record everything."""

from __future__ import annotations

from typing import Generic, TypeVar

import reactivex as rx
import reactivex.operators as ops

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", bound=Message)


class RecordedMessages(Generic[TMessage]):
    """Wraps an Observable[Message] subscription. Test code asserts on ``.items``."""

    def __init__(self, source: rx.Observable[Message], message_type: type[TMessage]) -> None:
        self.items: list[TMessage] = []
        self._subscription = source.pipe(
            ops.filter(lambda m: isinstance(m, message_type)),
        ).subscribe(self.items.append)

    def dispose(self) -> None:
        self._subscription.dispose()

    def __enter__(self) -> RecordedMessages[TMessage]:
        return self

    def __exit__(self, *exc: object) -> None:
        self.dispose()

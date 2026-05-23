"""In-process IMessageHub-equivalent for unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import reactivex as rx
from reactivex.subject import Subject

from vmx.messages.protocols import Message

if TYPE_CHECKING:
    pass

TMessage = TypeVar("TMessage", bound=Message)


class TestHub:
    """Subject-backed test hub. Subscribers can use Rx operators directly.

    This is a stand-alone helper that does NOT inherit from ``MessageHub``
    (the concrete class lands in Task 4).  It satisfies the structural
    ``MessageHubProto`` interface: ``.messages`` and ``.send()``.
    """

    __test__ = False  # tell pytest this is not a test class

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()

    @property
    def messages(self) -> rx.Observable[Message]:
        return self._subject

    def send(self, message: TMessage) -> None:
        self._subject.on_next(message)

    def dispose(self) -> None:
        self._subject.on_completed()
        self._subject.dispose()

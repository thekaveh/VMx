"""NullMessageHub — null-object variant of IMessageHub.

See spec/03-messages.md §"Null variant" and ADR-0017.
"""

from __future__ import annotations

from typing import TypeVar

import reactivex as rx
from reactivex import Observable

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", bound=Message)


class NullMessageHub:
    """Stateless message hub whose operations are safe no-ops.

    ``send(...)`` does nothing. ``messages`` returns the empty observable
    (completes immediately with no values). Useful for tests, defaults, and
    headless components.
    """

    def __init__(self) -> None:
        self._messages: Observable[Message] = rx.empty()

    @property
    def messages(self) -> Observable[Message]:
        return self._messages

    def send(self, message: TMessage) -> None:
        return None


NULL_MESSAGE_HUB: NullMessageHub = NullMessageHub()
"""Shared singleton instance (the hub holds no state)."""

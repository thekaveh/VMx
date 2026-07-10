"""NullMessageHub — null-object variant of the MessageHubProto Protocol.

See spec/03-messages.md §"Null variant" and ADR-0017.

Typing notes
------------
:data:`NULL_MESSAGE_HUB` is typed as :class:`~vmx.services.message_hub.MessageHubProto`
``[Message]`` — the structural :class:`~typing.Protocol`. This means downstream
``mypy --strict`` consumers can assign it to either:

* a ``MessageHubProto[Message]`` annotation (preferred public surface), or
* a ``MessageHub[Message]`` annotation (concrete class) — Python structural
  subtyping accepts the assignment since :class:`NullMessageHub` satisfies the
  same shape.

When a strictly-typed hub of a narrower :class:`~vmx.messages.protocols.Message`
subtype is needed, use :func:`null_message_hub_of` — a generic factory that
returns a freshly typed null hub bound to the message type parameter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

import reactivex as rx
from reactivex import Observable

from vmx.messages.protocols import Message
from vmx.services.message_hub import TransactionalMessageHubProto

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

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Execute the body while continuing to publish nothing."""
        yield


NULL_MESSAGE_HUB: TransactionalMessageHubProto[Message] = NullMessageHub()
"""Shared singleton instance (the hub holds no state).

Typed as :class:`MessageHubProto[Message]` so downstream
``mypy --strict`` consumers can assign it to either a ``MessageHubProto[Message]``
or a ``MessageHub[Message]`` annotation without an extra cast.
"""


def null_message_hub_of(message_type: type[TMessage]) -> TransactionalMessageHubProto[TMessage]:
    """Return a fresh null message hub typed for ``message_type``.

    Use this when a strictly-typed null hub of a narrower :class:`Message`
    subtype is needed (e.g. a hub of ``MyDomainMessage`` for ``mypy --strict``
    callers). The returned hub is the same null-object implementation; only
    the *declared* type parameter narrows.

    Args:
        message_type: The :class:`Message` subtype to bind the hub to.

    Returns:
        A :class:`MessageHubProto` whose ``send`` accepts ``message_type``.
    """
    del message_type  # only used to infer the type parameter
    return NullMessageHub()

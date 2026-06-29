"""Documentation tests for the null-services typing pattern.

These tests are *type-check tests* as much as runtime tests — the assignments
below would fail under ``mypy --strict`` if the public typing surface ever
regressed. Downstream consumers writing ``mypy --strict`` code should follow
the same pattern.

Background:
``MessageHub[Message]`` is the concrete generic class. ``MessageHubProto[Message]``
is the structural :class:`~typing.Protocol` that ``MessageHub`` and
``NullMessageHub`` both satisfy.

* For a strictly-typed null hub, annotate the variable as
  ``MessageHubProto[Message]`` and assign :data:`NULL_MESSAGE_HUB`.
* For a narrower message type, use :func:`null_message_hub_of` which returns
  ``MessageHubProto[T]``.
"""

from __future__ import annotations

from vmx import (
    NULL_DISPATCHER,
    NULL_MESSAGE_HUB,
    ConstructionStatusChangedMessage,
    Message,
    MessageHubProto,
    NullDispatcher,
    NullMessageHub,
)
from vmx.services import null_message_hub_of
from vmx.services.dispatcher import Dispatcher

# ---------------------------------------------------------------------------
# Test 1 — NULL_MESSAGE_HUB satisfies MessageHubProto[Message]
# ---------------------------------------------------------------------------


def test_null_message_hub_satisfies_protocol_annotation() -> None:
    """The downstream-recommended annotation must accept the singleton."""
    hub: MessageHubProto[Message] = NULL_MESSAGE_HUB
    # exercise the protocol surface to make sure it's a no-op
    assert hub.messages is not None
    hub.send(  # safe no-op
        ConstructionStatusChangedMessage.create(object(), "x", None)  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Test 2 — null_message_hub_of(T) returns a MessageHubProto[T]
# ---------------------------------------------------------------------------


def test_null_message_hub_of_returns_narrowly_typed_hub() -> None:
    """The factory must return a ``MessageHubProto`` bound to the requested type."""
    hub: MessageHubProto[ConstructionStatusChangedMessage] = null_message_hub_of(
        ConstructionStatusChangedMessage
    )
    assert hub.messages is not None
    # send accepts the narrower type
    hub.send(
        ConstructionStatusChangedMessage.create(object(), "x", None)  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Test 3 — NULL_DISPATCHER satisfies the Dispatcher Protocol
# ---------------------------------------------------------------------------


def test_null_dispatcher_satisfies_protocol_annotation() -> None:
    """``NULL_DISPATCHER`` already works because ``Dispatcher`` is a Protocol."""
    disp: Dispatcher = NULL_DISPATCHER
    assert disp.foreground is not None
    assert disp.background is not None


# ---------------------------------------------------------------------------
# Test 4 — NullMessageHub class itself satisfies MessageHubProto[Message]
# ---------------------------------------------------------------------------


def test_nullmessagehub_class_instance_satisfies_protocol() -> None:
    """Instantiating ``NullMessageHub()`` directly also satisfies the protocol."""
    hub: MessageHubProto[Message] = NullMessageHub()
    assert hub.messages is not None


# ---------------------------------------------------------------------------
# Test 5 — same for NullDispatcher
# ---------------------------------------------------------------------------


def test_nulldispatcher_class_instance_satisfies_protocol() -> None:
    disp: Dispatcher = NullDispatcher()
    assert disp.foreground is not None
    assert disp.background is not None

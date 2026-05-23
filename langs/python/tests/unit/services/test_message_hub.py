"""Unit tests for MessageHub.

Covers:
- send() delivers to current subscribers (HUB-001)
- late subscribers do not see prior messages (HUB-002)
- single-producer FIFO order (HUB-003)
- subscriber exception isolated — hub continues for other subs (HUB-007)
"""

from __future__ import annotations

from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHub, MessageHubProto

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(name: str) -> PropertyChangedMessage[object]:
    sentinel = object()
    return PropertyChangedMessage.create(sentinel, "vm", name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_send_delivers_to_current_subscriber() -> None:
    """HUB-001: Send delivers the message to an active subscriber."""
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    received: list[PropertyChangedMessage[object]] = []
    hub.messages.subscribe(received.append)

    msg = _make_msg("X")
    hub.send(msg)

    assert received == [msg]
    hub.dispose()


def test_late_subscriber_does_not_see_prior_messages() -> None:
    """HUB-002: A subscriber that subscribes after a Send does not receive that message."""
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    msg_a = _make_msg("A")
    msg_b = _make_msg("B")

    hub.send(msg_a)  # sent before any subscriber

    received: list[PropertyChangedMessage[object]] = []
    hub.messages.subscribe(received.append)

    hub.send(msg_b)  # sent after subscription

    assert received == [msg_b], f"expected only [B], got {received}"
    hub.dispose()


def test_single_producer_fifo_order() -> None:
    """HUB-003: Messages from a single producer are observed in send order."""
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    msgs = [_make_msg(c) for c in ["A", "B", "C"]]
    received: list[PropertyChangedMessage[object]] = []
    hub.messages.subscribe(received.append)

    for m in msgs:
        hub.send(m)

    assert [r.property_name for r in received] == ["A", "B", "C"]
    hub.dispose()


def test_subscriber_exception_isolated() -> None:
    """HUB-007: A raising subscriber does not break the hub or other subscribers."""
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()

    def bad_handler(m: object) -> None:
        raise RuntimeError("subscriber boom")

    good_received: list[object] = []
    hub.messages.subscribe(bad_handler)
    hub.messages.subscribe(good_received.append)

    msg1 = _make_msg("M1")
    msg2 = _make_msg("M2")
    hub.send(msg1)
    hub.send(msg2)

    # The good subscriber must receive both messages and no exception propagated.
    assert len(good_received) == 2
    hub.dispose()


def test_message_hub_satisfies_proto() -> None:
    """MessageHub is structurally compatible with MessageHubProto."""
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    assert isinstance(hub, MessageHubProto)
    hub.dispose()

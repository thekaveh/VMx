"""Unit tests for MessageHub.

Covers:
- send() delivers to current subscribers (HUB-001)
- late subscribers do not see prior messages (HUB-002)
- single-producer FIFO order (HUB-003)
- subscriber exception isolated — hub continues for other subs (HUB-007)
"""

from __future__ import annotations

from threading import Event, Thread, get_ident

import pytest

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


def test_concurrent_producer_waits_for_batch_and_delivers_on_own_thread() -> None:
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    batch_entered = Event()
    release_batch = Event()
    send_started = Event()
    send_finished = Event()
    producer_thread: list[int] = []
    delivery_thread: list[int] = []
    hub.messages.subscribe(lambda _: delivery_thread.append(get_ident()))

    def hold_batch() -> None:
        with hub.batch():
            batch_entered.set()
            release_batch.wait()

    def send() -> None:
        producer_thread.append(get_ident())
        send_started.set()
        hub.send(_make_msg("concurrent"))
        send_finished.set()

    batch_worker = Thread(target=hold_batch)
    batch_worker.start()
    assert batch_entered.wait(1)
    send_worker = Thread(target=send)
    send_worker.start()
    assert send_started.wait(1)
    try:
        assert not send_finished.wait(0.05)
    finally:
        release_batch.set()
        batch_worker.join(1)
        send_worker.join(1)

    assert send_finished.is_set()
    assert delivery_thread == producer_thread


def test_concurrent_producer_waits_for_active_drain_and_delivers_on_own_thread() -> None:
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    drain_entered = Event()
    release_drain = Event()
    send_started = Event()
    send_finished = Event()
    producer_thread: list[int] = []
    delivery_thread: list[int] = []

    def observe(message: PropertyChangedMessage[object]) -> None:
        if message.property_name == "blocker":
            drain_entered.set()
            assert release_drain.wait(1)
        elif message.property_name == "concurrent":
            delivery_thread.append(get_ident())

    hub.messages.subscribe(observe)
    drainer = Thread(target=lambda: hub.send(_make_msg("blocker")))
    drainer.start()
    assert drain_entered.wait(1)

    def send() -> None:
        producer_thread.append(get_ident())
        send_started.set()
        hub.send(_make_msg("concurrent"))
        send_finished.set()

    producer = Thread(target=send)
    producer.start()
    assert send_started.wait(1)
    try:
        assert not send_finished.wait(0.05)
    finally:
        release_drain.set()
        drainer.join(1)
        producer.join(1)

    assert send_finished.is_set()
    assert delivery_thread == producer_thread


def test_concurrent_dispose_waits_for_active_delivery_before_completion() -> None:
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    delivery_entered = Event()
    release_delivery = Event()
    dispose_started = Event()
    dispose_finished = Event()
    trace: list[str] = []

    def receive(_: object) -> None:
        trace.append("message:start")
        delivery_entered.set()
        assert release_delivery.wait(1)
        trace.append("message:end")

    hub.messages.subscribe(receive, on_completed=lambda: trace.append("completed"))
    sender = Thread(target=lambda: hub.send(_make_msg("blocking")))
    sender.start()
    assert delivery_entered.wait(1)

    def dispose() -> None:
        dispose_started.set()
        hub.dispose()
        dispose_finished.set()

    disposer = Thread(target=dispose)
    disposer.start()
    assert dispose_started.wait(1)
    try:
        assert not dispose_finished.wait(0.05)
        assert trace == ["message:start"]
    finally:
        release_delivery.set()
        sender.join(1)
        disposer.join(1)

    assert not sender.is_alive()
    assert not disposer.is_alive()
    assert trace == ["message:start", "message:end", "completed"]


def test_reentrant_dispose_completes_after_in_flight_message_reaches_subscribers() -> None:
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    trace: list[str] = []

    def first(_: object) -> None:
        trace.append("first:start")
        hub.dispose()
        trace.append("first:end")

    hub.messages.subscribe(first, on_completed=lambda: trace.append("first:completed"))
    hub.messages.subscribe(
        lambda _: trace.append("second:message"),
        on_completed=lambda: trace.append("second:completed"),
    )

    hub.send(_make_msg("dispose"))

    assert trace == [
        "first:start",
        "first:end",
        "second:message",
        "first:completed",
        "second:completed",
    ]


def test_development_drain_diagnostic_names_message_type() -> None:
    if not __debug__:
        pytest.skip("development diagnostics are compiled out under python -O")
    hub: MessageHub[PropertyChangedMessage[object]] = MessageHub()
    hub.messages.subscribe(lambda message: hub.send(message))

    with pytest.raises(RuntimeError, match="PropertyChangedMessage"):
        hub.send(_make_msg("cycle"))

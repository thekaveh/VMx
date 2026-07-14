"""Conformance tests for the message hub — HUB-001 through HUB-013.

HUB-006 is fixture-driven from spec/fixtures/message-ordering.json.
All other tests are implemented directly.
"""

from __future__ import annotations

from threading import Barrier, Thread
from typing import Any

import pytest

from tests.conformance.fixtures.loader import load
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(tag: str) -> PropertyChangedMessage[object]:
    sentinel = object()
    return PropertyChangedMessage.create(sentinel, "hub-test", tag)


def _fresh_hub() -> MessageHub[PropertyChangedMessage[object]]:
    return MessageHub()


# ---------------------------------------------------------------------------
# HUB-001 — Send delivers to current subscribers
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HUB-001")
def test_HUB_001_send_delivers_to_current_subscriber() -> None:
    hub = _fresh_hub()
    received: list[PropertyChangedMessage[object]] = []
    hub.messages.subscribe(received.append)

    msg = _make_msg("X")
    hub.send(msg)

    assert received == [msg]
    hub.dispose()


# ---------------------------------------------------------------------------
# HUB-002 — Late subscribers do not see prior messages
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HUB-002")
def test_HUB_002_late_subscriber_does_not_see_prior_messages() -> None:
    hub = _fresh_hub()
    msg_a = _make_msg("A")
    msg_b = _make_msg("B")

    hub.send(msg_a)  # before subscription

    received: list[PropertyChangedMessage[object]] = []
    hub.messages.subscribe(received.append)
    hub.send(msg_b)  # after subscription

    assert [m.property_name for m in received] == ["B"]
    hub.dispose()


# ---------------------------------------------------------------------------
# HUB-003 — Single-producer FIFO order
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HUB-003")
def test_HUB_003_single_producer_fifo_order() -> None:
    hub = _fresh_hub()
    received: list[str] = []
    hub.messages.subscribe(lambda m: received.append(m.property_name))  # type: ignore[union-attr]

    for tag in ["A", "B", "C"]:
        hub.send(_make_msg(tag))

    assert received == ["A", "B", "C"]
    hub.dispose()


# ---------------------------------------------------------------------------
# HUB-004 — Subscriber dispose during emit does not crash
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HUB-004")
def test_HUB_004_subscriber_dispose_during_emit_does_not_crash() -> None:
    hub = _fresh_hub()
    received: list[str] = []
    sub_holder: list[Any] = []

    def handler(m: Any) -> None:
        received.append(m.property_name)
        # Dispose our own subscription on the first message
        if sub_holder:
            sub_holder[0].dispose()

    sub = hub.messages.subscribe(handler)
    sub_holder.append(sub)

    hub.send(_make_msg("A"))
    hub.send(_make_msg("B"))  # should not be delivered to disposed subscriber

    assert received == ["A"]
    hub.dispose()


# ---------------------------------------------------------------------------
# HUB-005 — Multiple subscribers each observe every post-subscribe message
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HUB-005")
def test_HUB_005_multiple_subscribers_each_see_every_message() -> None:
    hub = _fresh_hub()
    buckets: list[list[str]] = [[], [], []]

    for bucket in buckets:
        hub.messages.subscribe(lambda m, b=bucket: b.append(m.property_name))  # type: ignore[union-attr]

    for tag in ["A", "B"]:
        hub.send(_make_msg(tag))

    for bucket in buckets:
        assert bucket == ["A", "B"], f"subscriber missed a message: {bucket}"

    hub.dispose()


# ---------------------------------------------------------------------------
# HUB-006 — Hub matches message-ordering fixture (parametrized)
# ---------------------------------------------------------------------------


def _fixture_scenarios() -> list[tuple[str, dict[str, Any]]]:
    data = load("message-ordering.json")
    return [(s["id"], s) for s in data["scenarios"]]


def _scenario_id(x: object) -> str:
    return x if isinstance(x, str) else ""


@pytest.mark.conformance("HUB-006")
@pytest.mark.parametrize("scenario_id,scenario", _fixture_scenarios(), ids=_scenario_id)
def test_HUB_006_fixture_scenarios(scenario_id: str, scenario: dict[str, Any]) -> None:
    """Exercise every scenario in message-ordering.json."""
    hub = _fresh_hub()

    if scenario_id == "single-producer-fifo":
        received: list[str] = []
        hub.messages.subscribe(lambda m: received.append(m.property_name))  # type: ignore[union-attr]
        for tag in scenario["producer_sends"]:
            hub.send(_make_msg(tag))
        assert received == scenario["expected_observed"]

    elif scenario_id == "late-subscribe-no-replay":
        for tag in scenario["producer_sends_before_subscribe"]:
            hub.send(_make_msg(tag))
        received2: list[str] = []
        hub.messages.subscribe(lambda m: received2.append(m.property_name))  # type: ignore[union-attr]
        for tag in scenario["producer_sends_after_subscribe"]:
            hub.send(_make_msg(tag))
        assert received2 == scenario["expected_observed"]

    elif scenario_id == "multiple-subscribers-same-message":
        count: int = scenario["subscriber_count"]
        buckets2: list[list[str]] = [[] for _ in range(count)]
        for bucket in buckets2:
            hub.messages.subscribe(lambda m, b=bucket: b.append(m.property_name))  # type: ignore[union-attr]
        for tag in scenario["producer_sends"]:
            hub.send(_make_msg(tag))
        expected = scenario["expected_observed_per_subscriber"]
        for i, bucket in enumerate(buckets2):
            assert bucket == expected, f"subscriber {i} got {bucket}, expected {expected}"

    elif scenario_id == "unsubscribe-during-emit":
        # One subscriber disposes after the first message; check it only sees the first.
        received3: list[str] = []
        sub_holder2: list[Any] = []

        def handler_u(m: Any) -> None:
            received3.append(m.property_name)
            if sub_holder2:
                sub_holder2[0].dispose()

        sub2 = hub.messages.subscribe(handler_u)
        sub_holder2.append(sub2)
        for tag in scenario["producer_sends"]:
            hub.send(_make_msg(tag))
        assert received3 == scenario["expected_observed"]

    else:
        pytest.fail(f"Unknown scenario id: {scenario_id!r}")

    hub.dispose()


# ---------------------------------------------------------------------------
# HUB-007 — Subscriber handler that raises does not break the hub
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HUB-007")
def test_HUB_007_raising_subscriber_does_not_break_hub() -> None:
    hub = _fresh_hub()

    def bad_handler(m: object) -> None:
        raise ValueError("subscriber explodes")

    good_received: list[str] = []
    hub.messages.subscribe(bad_handler)
    hub.messages.subscribe(lambda m: good_received.append(m.property_name))  # type: ignore[union-attr]

    hub.send(_make_msg("M1"))
    hub.send(_make_msg("M2"))

    assert good_received == ["M1", "M2"], (
        f"Good subscriber should receive both messages but got: {good_received}"
    )
    hub.dispose()


@pytest.mark.conformance("HUB-008")
def test_HUB_008_nested_batches_defer_and_preserve_fifo() -> None:
    hub = _fresh_hub()
    received: list[str] = []
    hub.messages.subscribe(lambda m: received.append(m.property_name))  # type: ignore[union-attr]

    with hub.batch():
        hub.send(_make_msg("A"))
        with hub.batch():
            hub.send(_make_msg("B"))
        hub.send(_make_msg("C"))
        assert received == []

    assert received == ["A", "B", "C"]


@pytest.mark.conformance("HUB-009")
def test_HUB_009_batch_error_drains_then_reraises_original() -> None:
    hub = _fresh_hub()
    received: list[str] = []
    hub.messages.subscribe(lambda m: received.append(m.property_name))  # type: ignore[union-attr]
    sentinel = RuntimeError("sentinel")

    with pytest.raises(RuntimeError) as raised:
        with hub.batch():
            hub.send(_make_msg("A"))
            raise sentinel

    assert raised.value is sentinel
    assert received == ["A"]


@pytest.mark.conformance("HUB-010")
def test_HUB_010_reentrant_send_joins_iterative_fifo_drain() -> None:
    hub = _fresh_hub()
    trace: list[str] = []

    def first(message: Any) -> None:
        trace.append(f"first:{message.property_name}")
        if message.property_name == "A":
            hub.send(_make_msg("B"))

    hub.messages.subscribe(first)
    hub.messages.subscribe(lambda m: trace.append(f"second:{m.property_name}"))  # type: ignore[union-attr]

    hub.send(_make_msg("A"))

    assert trace == ["first:A", "second:A", "first:B", "second:B"]


@pytest.mark.conformance("HUB-011")
def test_HUB_011_subscriber_failure_does_not_abort_batch_drain() -> None:
    hub = _fresh_hub()
    received: list[str] = []

    def bad_handler(message: object) -> None:
        raise ValueError("subscriber explodes")

    hub.messages.subscribe(bad_handler)
    hub.messages.subscribe(lambda m: received.append(m.property_name))  # type: ignore[union-attr]

    with hub.batch():
        hub.send(_make_msg("A"))
        hub.send(_make_msg("B"))

    assert received == ["A", "B"]


@pytest.mark.conformance("HUB-012")
def test_HUB_012_dispose_during_batch_drops_queued_messages() -> None:
    hub = _fresh_hub()
    received: list[str] = []
    completed: list[bool] = []
    hub.messages.subscribe(
        lambda m: received.append(m.property_name),  # type: ignore[union-attr]
        on_completed=lambda: completed.append(True),
    )

    with hub.batch():
        hub.send(_make_msg("A"))
        hub.dispose()
        hub.send(_make_msg("B"))
    hub.send(_make_msg("C"))

    assert received == []
    assert completed == [True]


def test_opposing_cross_hub_callbacks_do_not_deadlock() -> None:
    first = _fresh_hub()
    second = _fresh_hub()
    callbacks_ready = Barrier(2)
    trace: list[str] = []

    def from_first(message: Any) -> None:
        if message.property_name != "root":
            trace.append("first:reply")
            return
        callbacks_ready.wait(timeout=1)
        second.send(_make_msg("reply"))

    def from_second(message: Any) -> None:
        if message.property_name != "root":
            trace.append("second:reply")
            return
        callbacks_ready.wait(timeout=1)
        first.send(_make_msg("reply"))

    first.messages.subscribe(from_first)
    second.messages.subscribe(from_second)
    senders = [
        Thread(target=lambda: first.send(_make_msg("root")), daemon=True),
        Thread(target=lambda: second.send(_make_msg("root")), daemon=True),
    ]
    for sender in senders:
        sender.start()
    for sender in senders:
        sender.join(timeout=1)

    assert all(not sender.is_alive() for sender in senders)
    assert sorted(trace) == ["first:reply", "second:reply"]


@pytest.mark.conformance("HUB-013")
def test_HUB_013_ordinary_send_remains_synchronous() -> None:
    hub = _fresh_hub()
    delivered = False

    def record(message: object) -> None:
        nonlocal delivered
        delivered = True

    hub.messages.subscribe(record)
    hub.send(_make_msg("A"))

    assert delivered

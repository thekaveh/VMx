"""Conformance tests for the message hub — HUB-001 through HUB-013.

HUB-006 is fixture-driven from spec/fixtures/message-ordering.json.
All other tests are implemented directly.
"""

from __future__ import annotations

from threading import Barrier, Condition, Event, Lock, Thread, current_thread, get_ident
from typing import Any

import pytest

from tests.conformance.fixtures.loader import load
from tests.liveness import HANG_GUARD
from tests.wait_graph_seams import WaitDecisions, wait_until_waiting
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


def test_opposing_hub_callbacks_do_not_deadlock() -> None:
    left = _fresh_hub()
    right = _fresh_hub()
    callbacks_entered = Barrier(2)
    inner_deliveries = 0
    delivery_lock = Lock()

    def subscribe_crossing(
        source: MessageHub[PropertyChangedMessage[object]],
        target: MessageHub[PropertyChangedMessage[object]],
    ) -> None:
        def callback(message: PropertyChangedMessage[object]) -> None:
            nonlocal inner_deliveries
            if message.property_name == "outer":
                callbacks_entered.wait(HANG_GUARD)
                target.send(_make_msg("inner"))
            else:
                with delivery_lock:
                    inner_deliveries += 1

        source.messages.subscribe(callback)

    subscribe_crossing(left, right)
    subscribe_crossing(right, left)
    workers = [
        Thread(target=left.send, args=(_make_msg("outer"),), daemon=True),
        Thread(target=right.send, args=(_make_msg("outer"),), daemon=True),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2 * HANG_GUARD)

    assert not any(worker.is_alive() for worker in workers)
    assert inner_deliveries == 2
    left.dispose()
    right.dispose()


def test_opposing_hub_callback_batches_do_not_deadlock() -> None:
    left = _fresh_hub()
    right = _fresh_hub()
    callbacks_entered = Barrier(2)
    inner_deliveries = 0
    delivery_lock = Lock()

    def subscribe_crossing(
        source: MessageHub[PropertyChangedMessage[object]],
        target: MessageHub[PropertyChangedMessage[object]],
    ) -> None:
        def callback(message: PropertyChangedMessage[object]) -> None:
            nonlocal inner_deliveries
            if message.property_name == "outer":
                callbacks_entered.wait(HANG_GUARD)
                with target.batch():
                    target.send(_make_msg("inner"))
            else:
                with delivery_lock:
                    inner_deliveries += 1

        source.messages.subscribe(callback)

    subscribe_crossing(left, right)
    subscribe_crossing(right, left)
    workers = [
        Thread(target=left.send, args=(_make_msg("outer"),), daemon=True),
        Thread(target=right.send, args=(_make_msg("outer"),), daemon=True),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2 * HANG_GUARD)

    assert not any(worker.is_alive() for worker in workers)
    assert inner_deliveries == 2
    left.dispose()
    right.dispose()


def test_unrelated_hub_callback_send_waits_for_busy_target() -> None:
    source = _fresh_hub()
    target = _fresh_hub()
    batch_entered = Event()
    release_batch = Event()
    callback_returned = Event()
    deliveries: list[str] = []
    target.messages.subscribe(lambda message: deliveries.append(message.property_name))

    def hold_batch() -> None:
        with target.batch():
            batch_entered.set()
            assert release_batch.wait(HANG_GUARD)

    batch_worker = Thread(target=hold_batch)
    batch_worker.start()
    assert batch_entered.wait(HANG_GUARD)

    def cross_send(_: object) -> None:
        target.send(_make_msg("nested"))
        callback_returned.set()

    source.messages.subscribe(cross_send)
    source_worker = Thread(target=source.send, args=(_make_msg("outer"),))
    source_worker.start()
    try:
        assert not callback_returned.wait(0.05)
    finally:
        release_batch.set()
        batch_worker.join(HANG_GUARD)
        source_worker.join(HANG_GUARD)

    assert callback_returned.is_set()
    assert deliveries == ["nested"]
    source.dispose()
    target.dispose()


def test_cyclic_dispose_of_batched_hub_completes_on_batch_exit() -> None:
    batched = _fresh_hub()
    source = _fresh_hub()
    completed = Event()
    callback_entered = Event()
    about_to_send = Event()
    sender: list[int] = []
    errors: list[BaseException] = []
    batched.messages.subscribe(on_completed=completed.set)

    def dispose_batched(message: PropertyChangedMessage[object]) -> None:
        if message.property_name != "outer":
            return
        callback_entered.set()
        try:
            if not about_to_send.wait(HANG_GUARD):
                raise TimeoutError("batch owner did not reach its cross-hub send")
            # The batch owner's send waits for this drainer, with its edge in
            # the shared wait-for graph, so disposing its batched hub here
            # would close a cycle.
            wait_until_waiting(sender[0])
        except TimeoutError as error:
            errors.append(error)
            return
        batched.dispose()

    source.messages.subscribe(dispose_batched)

    def own_batch_then_cross_send() -> None:
        sender.append(get_ident())
        try:
            with batched.batch():
                if not callback_entered.wait(HANG_GUARD):
                    raise TimeoutError("source callback did not start")
                about_to_send.set()
                source.send(_make_msg("inner"))
        except BaseException as error:
            errors.append(error)

    batch_worker = Thread(target=own_batch_then_cross_send)
    source_worker = Thread(target=source.send, args=(_make_msg("outer"),))
    batch_worker.start()
    source_worker.start()
    batch_worker.join(3 * HANG_GUARD)
    source_worker.join(3 * HANG_GUARD)

    assert not batch_worker.is_alive()
    assert not source_worker.is_alive()
    assert errors == []
    assert completed.wait(HANG_GUARD)
    source.dispose()


# ---------------------------------------------------------------------------
# HUB-013 regressions — one wait-for graph and borrowed scopes (ADR-0172)
# ---------------------------------------------------------------------------


class _Threads:
    """Named worker threads whose idents are known before their peers look."""

    def __init__(self, errors: list[BaseException]) -> None:
        self._errors = errors
        self._threads: dict[str, Thread] = {}
        self._idents: dict[str, int] = {}
        self._registered = Condition()

    def start(self, name: str, action: Any) -> Thread:
        def run() -> None:
            with self._registered:
                self._idents[name] = get_ident()
                self._registered.notify_all()
            try:
                action()
            except BaseException as error:
                self._errors.append(error)

        thread = Thread(target=run, name=name, daemon=True)
        self._threads[name] = thread
        thread.start()
        return thread

    def ident(self, name: str) -> int:
        with self._registered:
            if not self._registered.wait_for(lambda: name in self._idents, HANG_GUARD):
                raise TimeoutError(f"thread {name} did not start")
            return self._idents[name]

    def join_all(self) -> None:
        _join_all(*self._threads.values())


def _recording(errors: list[BaseException], callback: Any) -> Any:
    """Record a subscriber's failure; the hub would only log it (HUB-007)."""

    def run(message: PropertyChangedMessage[object]) -> None:
        try:
            callback(message)
        except BaseException as error:
            errors.append(error)
            raise

    return run


def _join_all(*threads: Thread) -> None:
    for thread in threads:
        thread.join(3 * HANG_GUARD)
    hung = [thread.name for thread in threads if thread.is_alive()]
    assert hung == [], f"threads still waiting: {hung}"


def _thread_log(
    hub: MessageHub[PropertyChangedMessage[object]],
) -> list[tuple[str, str]]:
    log: list[tuple[str, str]] = []
    hub.messages.subscribe(
        lambda message: log.append((message.property_name, current_thread().name))
    )
    return log


@pytest.mark.conformance("HUB-013")
@pytest.mark.parametrize(
    ("target", "order"),
    [("h3", "borrow_exit_first"), ("h", "borrow_exit_first"), ("h3", "p_waits_first")],
)
def test_a_wait_for_a_borrowed_scope_records_an_edge(target: str, order: str) -> None:
    # #1179 reproduction 1. P borrows h, which Q drains. Q's drain then finds
    # an empty queue and releases the drain instead of waiting for P's borrow
    # with no edge, so P's later wait for Q cannot hang.
    h, h2, h3 = _fresh_hub(), _fresh_hub(), _fresh_hub()
    errors: list[BaseException] = []
    threads = _Threads(errors)
    borrow_open = Event()
    q_left_h3 = Event()
    early: list[str] = []
    h_log = _thread_log(h)
    h3_log = _thread_log(h3)
    p_draining = Event()

    def on_h(message: PropertyChangedMessage[object]) -> None:
        if borrow_open.is_set():
            early.append(message.property_name)
        if message.property_name == "q0":
            h2.send(_make_msg("q1"))
            if order == "p_waits_first":
                wait_until_waiting(threads.ident("P"))

    h.messages.subscribe(_recording(errors, on_h))

    def on_h2(message: PropertyChangedMessage[object]) -> None:
        if message.property_name != "p0":
            return
        p_draining.set()
        wait_until_waiting(threads.ident("Q"))
        with h.batch():
            borrow_open.set()
            h2.dispose()
            if order == "borrow_exit_first" and not q_left_h3.wait(HANG_GUARD):
                errors.append(TimeoutError("Q's h3 batch did not exit"))
            (h3 if target == "h3" else h).send(_make_msg("pm"))
            borrow_open.clear()

    h2.messages.subscribe(_recording(errors, on_h2))

    def q_body() -> None:
        with h3.batch():
            h.send(_make_msg("q0"))
        q_left_h3.set()

    threads.start("P", lambda: h2.send(_make_msg("p0")))
    assert p_draining.wait(HANG_GUARD)
    threads.start("Q", q_body)
    threads.join_all()

    assert errors == []
    assert early == []
    delivered = h3_log if target == "h3" else [entry for entry in h_log if entry[0] == "pm"]
    assert [tag for tag, _ in delivered] == ["pm"]


@pytest.mark.conformance("HUB-013")
@pytest.mark.parametrize("operation", ["send", "batch", "dispose"])
def test_a_wait_for_a_borrower_closes_a_visible_cycle(operation: str) -> None:
    # #1179 variant: after its own h batch exits, Q's h operation waits for
    # P's borrowed scope with an edge. P's h3 send, which waits for Q, then
    # closes a visible cycle and enqueues instead of hanging.
    h, h2, h3 = _fresh_hub(), _fresh_hub(), _fresh_hub()
    errors: list[BaseException] = []
    threads = _Threads(errors)
    borrow_open = Event()
    q_left_h = Event()
    early: list[str] = []
    h3_log = _thread_log(h3)
    h_log = _thread_log(h)
    h_completed: list[bool] = []
    h.messages.subscribe(on_completed=lambda: h_completed.append(True))
    p_draining = Event()
    h.messages.subscribe(
        lambda message: early.append(message.property_name) if borrow_open.is_set() else None
    )

    def on_h2(message: PropertyChangedMessage[object]) -> None:
        if message.property_name != "p0":
            return
        p_draining.set()
        wait_until_waiting(threads.ident("Q"))
        with h.batch():
            borrow_open.set()
            h2.dispose()
            if not q_left_h.wait(HANG_GUARD):
                errors.append(TimeoutError("Q's h batch did not exit"))
            try:
                wait_until_waiting(threads.ident("Q"))
            except TimeoutError as error:
                errors.append(error)
            h3.send(_make_msg("pm"))
            borrow_open.clear()

    h2.messages.subscribe(_recording(errors, on_h2))

    def q_body() -> None:
        with h3.batch():
            with h.batch():
                h2.send(_make_msg("q1"))
            q_left_h.set()
            if operation == "send":
                h.send(_make_msg("qx"))
            elif operation == "batch":
                with h.batch():
                    h.send(_make_msg("qx"))
            else:
                h.dispose()

    threads.start("P", lambda: h2.send(_make_msg("p0")))
    assert p_draining.wait(HANG_GUARD)
    threads.start("Q", q_body)
    threads.join_all()

    assert errors == []
    assert early == []
    assert [tag for tag, _ in h3_log] == ["pm"]
    if operation == "dispose":
        assert h_completed == [True]
    else:
        assert h_log == [("qx", "Q")]


@pytest.mark.conformance("HUB-013")
@pytest.mark.parametrize("operation", ["send", "batch", "dispose"])
def test_a_borrowers_own_hub_calls_do_not_wait_for_its_borrow(operation: str) -> None:
    # #1179 reproduction 2. With no other owner left, P's send, nested batch
    # and dispose on the hub it borrowed must not wait for its own borrow.
    h, h2 = _fresh_hub(), _fresh_hub()
    errors: list[BaseException] = []
    threads = _Threads(errors)
    borrow_open = Event()
    q_left_h = Event()
    early: list[str] = []
    h_log = _thread_log(h)
    h_completed: list[bool] = []
    h.messages.subscribe(on_completed=lambda: h_completed.append(True))
    h.messages.subscribe(
        lambda message: early.append(message.property_name) if borrow_open.is_set() else None
    )
    p_draining = Event()

    def on_h2(message: PropertyChangedMessage[object]) -> None:
        if message.property_name != "p0":
            return
        p_draining.set()
        wait_until_waiting(threads.ident("Q"))
        with h.batch():
            borrow_open.set()
            h2.dispose()
            if not q_left_h.wait(HANG_GUARD):
                errors.append(TimeoutError("Q's h batch did not exit"))
            if operation == "send":
                h.send(_make_msg("pm"))
            elif operation == "batch":
                with h.batch():
                    h.send(_make_msg("pm"))
            else:
                h.dispose()
            borrow_open.clear()

    h2.messages.subscribe(_recording(errors, on_h2))

    def q_body() -> None:
        with h.batch():
            h2.send(_make_msg("q1"))
        q_left_h.set()

    threads.start("P", lambda: h2.send(_make_msg("p0")))
    assert p_draining.wait(HANG_GUARD)
    threads.start("Q", q_body)
    threads.join_all()

    assert errors == []
    assert early == []
    if operation == "dispose":
        assert h_completed == [True]
        assert h_log == []
    else:
        assert h_log == [("pm", "P")]


@pytest.mark.conformance("HUB-013")
@pytest.mark.parametrize("form", ["drain", "batch"])
@pytest.mark.parametrize("operation", ["send", "dispose", "batch", "batch_send"])
def test_an_ended_hub_wait_does_not_cause_a_cycle_escape(
    monkeypatch: pytest.MonkeyPatch, form: str, operation: str
) -> None:
    # #1181. P releases h2, which Q waits for. Q is held after it wakes and
    # before its wait ends, until P's h operation decides whether to wait for
    # Q's h batch. P released h2 before it woke Q, so Q's edge is gone and P
    # waits, as HUB-013 requires, instead of taking a cycle escape.
    seam = WaitDecisions(monkeypatch)
    h, h2 = _fresh_hub(), _fresh_hub()
    errors: list[BaseException] = []
    threads = _Threads(errors)
    h_log = _thread_log(h)
    h_completed: list[bool] = []
    h.messages.subscribe(on_completed=lambda: h_completed.append(True))
    p_owns_h2 = Event()
    body_start_log: list[tuple[str, str]] = []
    after_send_log: list[tuple[str, str]] = []

    def hold_q_until_p_decides() -> None:
        wait_until_waiting(threads.ident("Q"))
        seam.hold_until_decided(threads.ident("Q"), threads.ident("P"))

    def on_h2(message: PropertyChangedMessage[object]) -> None:
        if message.property_name == "p0":
            p_owns_h2.set()
            hold_q_until_p_decides()

    h2.messages.subscribe(_recording(errors, on_h2))

    def p_body() -> None:
        if form == "drain":
            h2.send(_make_msg("p0"))
        else:
            with h2.batch():
                p_owns_h2.set()
                hold_q_until_p_decides()
        if operation == "send":
            h.send(_make_msg("p1"))
            after_send_log.extend(h_log)
        elif operation == "dispose":
            h.dispose()
        else:
            with h.batch():
                body_start_log.extend(h_log)
                if operation == "batch_send":
                    h.send(_make_msg("p1"))

    def q_body() -> None:
        with h.batch():
            h.send(_make_msg("q0"))
            h2.send(_make_msg("q1"))

    threads.start("P", p_body)
    assert p_owns_h2.wait(HANG_GUARD)
    threads.start("Q", q_body)
    threads.join_all()

    assert errors == []
    p_decisions = seam.decisions(threads.ident("P"))
    assert p_decisions and all(p_decisions), "P took a cycle escape for an ended wait"
    if operation == "send":
        assert after_send_log == [("q0", "Q"), ("p1", "P")]
    elif operation == "dispose":
        assert h_log == [("q0", "Q")]
        assert h_completed == [True]
    else:
        assert body_start_log == [("q0", "Q")]
        expected = [("q0", "Q"), ("p1", "P")] if operation == "batch_send" else [("q0", "Q")]
        assert h_log == expected


@pytest.mark.conformance("HUB-013")
def test_a_live_hub_cycle_still_takes_the_send_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    # #1181 real-cycle control: P still drains h2 while Q waits for it, so
    # P's send to Q's batched hub enqueues for Q's batch exit.
    seam = WaitDecisions(monkeypatch)
    h, h2 = _fresh_hub(), _fresh_hub()
    errors: list[BaseException] = []
    threads = _Threads(errors)
    h_log = _thread_log(h)
    p_draining = Event()

    def on_h2(message: PropertyChangedMessage[object]) -> None:
        if message.property_name == "p0":
            p_draining.set()
            wait_until_waiting(threads.ident("Q"))
            h.send(_make_msg("p1"))

    h2.messages.subscribe(_recording(errors, on_h2))

    def q_body() -> None:
        with h.batch():
            h.send(_make_msg("q0"))
            h2.send(_make_msg("q1"))

    threads.start("P", lambda: h2.send(_make_msg("p0")))
    assert p_draining.wait(HANG_GUARD)
    threads.start("Q", q_body)
    threads.join_all()

    assert errors == []
    assert seam.decisions(threads.ident("P")) == [False]
    assert h_log == [("q0", "Q"), ("p1", "Q")]


@pytest.mark.conformance("HUB-013")
def test_a_drainer_with_queued_messages_releases_the_drain_on_a_cycle() -> None:
    # spec/03 §4.2 rule 5. Drainer D has m2 queued and would wait for B's
    # borrowed scope, while B already waits for D. D releases the drain, and
    # B's borrow exit delivers m2 on B. D's outermost send returns first.
    h, h2, h4 = _fresh_hub(), _fresh_hub(), _fresh_hub()
    errors: list[BaseException] = []
    threads = _Threads(errors)
    h_log = _thread_log(h)
    borrow_open = Event()
    early: list[str] = []
    h.messages.subscribe(
        lambda message: early.append(message.property_name) if borrow_open.is_set() else None
    )
    b_owns_h2 = Event()
    log_when_d_send_returned: list[tuple[str, str]] = []

    def on_h(message: PropertyChangedMessage[object]) -> None:
        if message.property_name == "m1":
            h.send(_make_msg("m2"))
            h2.send(_make_msg("x"))
            wait_until_waiting(threads.ident("B"))

    h.messages.subscribe(_recording(errors, on_h))

    def d_body() -> None:
        with h4.batch():
            h.send(_make_msg("m1"))
            log_when_d_send_returned.extend(h_log)

    def b_body() -> None:
        with h2.batch():
            b_owns_h2.set()
            wait_until_waiting(threads.ident("D"))
            with h.batch():
                borrow_open.set()
                h2.dispose()
                h4.send(_make_msg("b4"))
                borrow_open.clear()

    threads.start("B", b_body)
    assert b_owns_h2.wait(HANG_GUARD)
    threads.start("D", d_body)
    threads.join_all()

    assert errors == []
    assert early == []
    assert log_when_d_send_returned == [("m1", "D")]
    assert h_log == [("m1", "D"), ("m2", "B")]

"""Lifecycle waits and hub waits share one wait-for graph (#1202).

A VM's lifecycle drain sends its status messages on the VM's hub. A hub
drainer whose subscriber disposes the VM waits for the VM's lifecycle drainer
to deliver ``Disposed``. When that lifecycle drainer waits in the hub for the
hub drainer, the two waits form a cycle through a hub edge and a lifecycle
edge. The one graph sees both edges, so the wait that closes the cycle is
refused and takes its escape (spec/02 §2.4, spec/03 §4.1, ADR-0172).
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from tests.liveness import HANG_GUARD, join_thread, wait_event
from tests.wait_graph_seams import wait_until_waiting
from vmx.components.builders import ComponentVMOfBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _Worker:
    def __init__(self, name: str, action: Any) -> None:
        self.error: BaseException | None = None
        self._started = threading.Event()

        def run() -> None:
            self._started.set()
            try:
                action()
            except BaseException as error:
                self.error = error

        self.thread = threading.Thread(target=run, name=name, daemon=True)

    def start(self) -> _Worker:
        self.thread.start()
        return self

    @property
    def ident(self) -> int:
        """The thread's ident, once a peer thread has started it."""
        if not wait_event(self._started):
            raise TimeoutError(f"{self.thread.name} did not start")
        return self.thread.ident or 0

    def join(self) -> None:
        join_thread(self.thread, 3 * HANG_GUARD)
        assert not self.thread.is_alive(), f"{self.thread.name} hung"


def _vm(name: str, hub: MessageHub[object]) -> Any:
    builder = ComponentVMOfBuilder().name(name).services(hub, RxDispatcher.immediate())
    return builder.model(name).build()


class _StatusLog:
    """Status deliveries per VM name, with the delivering thread."""

    def __init__(self, hub: MessageHub[object]) -> None:
        self.deliveries: list[tuple[str, ConstructionStatus, str]] = []
        hub.messages.subscribe(self._record)

    def _record(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            self.deliveries.append(
                (message.sender_name, message.status, threading.current_thread().name)
            )

    def threads(self, name: str, status: ConstructionStatus) -> list[str]:
        return [
            thread for sender, sent, thread in self.deliveries if (sender, sent) == (name, status)
        ]


def _trigger() -> PropertyChangedMessage[object]:
    return PropertyChangedMessage.create(object(), "hub-test", "trigger")


def _on_trigger(hub: MessageHub[object], action: Any, errors: list[BaseException]) -> None:
    def callback(message: object) -> None:
        if isinstance(message, PropertyChangedMessage) and message.property_name == "trigger":
            try:
                action()
            except BaseException as error:
                errors.append(error)

    hub.messages.subscribe(callback)


def test_a_hub_drainer_disposing_a_constructing_vm_does_not_hang() -> None:
    # #1202: A's construct() drains x's publications and waits in send for
    # hub drainer B. B's subscriber disposes x, which would wait for A to
    # deliver Disposed. That closes the cycle, so B's wait is refused: B
    # leaves Disposed queued for A's drain and returns (ADR-0117).
    hub: MessageHub[object] = MessageHub()
    log = _StatusLog(hub)
    x = _vm("x", hub)
    errors: list[BaseException] = []
    draining = threading.Event()
    constructor = _Worker("A", x.construct)

    def dispose_x_when_a_waits() -> None:
        draining.set()
        wait_until_waiting(constructor.ident)
        x.dispose()

    _on_trigger(hub, dispose_x_when_a_waits, errors)
    drainer = _Worker("B", lambda: hub.send(_trigger())).start()
    assert wait_event(draining)
    constructor.start()
    drainer.join()
    constructor.join()

    assert errors == []
    assert drainer.error is None
    assert x.status is S.DISPOSED
    assert log.threads("x", S.DISPOSED) == ["A"]


def test_a_lifecycle_drainer_sending_to_a_waiting_hub_drainer_does_not_hang() -> None:
    # Reverse order: B's dispose() waits for A to deliver x's Disposed first.
    # A's hub send of that Disposed would then wait for drainer B, which
    # closes the cycle, so A's message is enqueued for B's drain (spec/03 §4).
    hub: MessageHub[object] = MessageHub()
    log = _StatusLog(hub)
    x = _vm("x", hub)
    errors: list[BaseException] = []
    a_draining_x = threading.Event()
    statuses_seen = Counter[str]()
    disposer = _Worker("B", lambda: hub.send(_trigger()))

    def hold_until_b_waits(name: str) -> None:
        # The first "status" notification runs on A inside x's drain, after
        # A delivered Constructing on the hub.
        statuses_seen.update([name])
        if name == "status" and statuses_seen[name] == 1:
            a_draining_x.set()
            try:
                wait_until_waiting(disposer.ident)
            except BaseException as error:
                errors.append(error)

    x.property_changed.subscribe(hold_until_b_waits)
    _on_trigger(hub, x.dispose, errors)
    constructor = _Worker("A", x.construct).start()
    assert wait_event(a_draining_x)
    disposer.start()
    disposer.join()
    constructor.join()

    assert errors == []
    assert disposer.error is None
    assert constructor.error is None
    assert x.status is S.DISPOSED
    assert log.threads("x", S.DISPOSED) == ["B"]


def test_disposing_another_vm_keeps_the_construct_send_synchronous() -> None:
    # Control (HUB-013): no cycle, so A's send waits for drainer B, and x's
    # Constructing message is delivered on A before construct() returns.
    hub: MessageHub[object] = MessageHub()
    log = _StatusLog(hub)
    x = _vm("x", hub)
    other = _vm("other", hub)
    errors: list[BaseException] = []
    draining = threading.Event()
    seen_before_construct_returned: list[str] = []

    def construct_x() -> None:
        x.construct()
        seen_before_construct_returned.extend(log.threads("x", S.CONSTRUCTING))

    constructor = _Worker("A", construct_x)

    def dispose_other_when_a_waits() -> None:
        draining.set()
        wait_until_waiting(constructor.ident)
        other.dispose()

    _on_trigger(hub, dispose_other_when_a_waits, errors)
    drainer = _Worker("B", lambda: hub.send(_trigger())).start()
    assert wait_event(draining)
    constructor.start()
    drainer.join()
    constructor.join()

    assert errors == []
    assert drainer.error is None
    assert constructor.error is None
    assert other.status is S.DISPOSED
    assert x.status is S.CONSTRUCTED
    assert seen_before_construct_returned == ["A"]

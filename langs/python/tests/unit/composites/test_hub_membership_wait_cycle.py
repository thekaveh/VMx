"""Hub waits and container membership waits share one wait-for graph (#1157).

A container sends hub messages while its membership transaction is open. A
hub drainer that disposes the container, and a transaction owner that waits
for that drainer, form a cycle through a hub edge and a membership edge. The
shared graph sees both edges, so one wait takes its escape (spec/03 §4.1,
spec/06 §4.2, ADR-0172).
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from tests.wait_graph_seams import wait_until_waiting
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
_KINDS = ("composite", "group")


def _container(kind: str, name: str, hub: MessageHub[object], auto: bool) -> Any:
    builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
    container = (
        builder.name(name)
        .services(hub, RxDispatcher.immediate())
        .auto_construct_on_add(auto)
        .children(lambda: [])
        .build()
    )
    container.construct()
    return container


def _child(name: str, hub: MessageHub[object]) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, RxDispatcher.immediate()).build()


def _add(container: Any, child: ComponentVM) -> None:
    if hasattr(container, "append"):
        container.append(child)
    else:
        container.add(child)


class _Worker:
    def __init__(self, name: str, action: Any) -> None:
        self.error: BaseException | None = None
        self.returned = threading.Event()
        self._started = threading.Event()

        def run() -> None:
            self._started.set()
            try:
                action()
            except BaseException as error:
                self.error = error
            finally:
                self.returned.set()

        self.thread = threading.Thread(target=run, name=name, daemon=True)

    def start(self) -> _Worker:
        self.thread.start()
        return self

    @property
    def ident(self) -> int:
        """The thread's ident, once a peer thread has started it."""
        if not self._started.wait(HANG_GUARD):
            raise TimeoutError(f"{self.thread.name} did not start")
        return self.thread.ident or 0

    def join(self) -> None:
        self.thread.join(3 * HANG_GUARD)
        assert not self.thread.is_alive(), f"{self.thread.name} hung"


class _HubLog:
    """Hub deliveries that the tests check, with the delivering thread."""

    def __init__(self, hub: MessageHub[object]) -> None:
        self.collection_changes: list[str] = []
        self.disposals: Counter[str] = Counter()
        hub.messages.subscribe(self._record)

    def _record(self, message: object) -> None:
        if isinstance(message, CollectionChangedMessage):
            self.collection_changes.append(threading.current_thread().name)
        elif isinstance(message, ConstructionStatusChangedMessage) and message.status is S.DISPOSED:
            self.disposals.update([message.sender_name])


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


@pytest.mark.parametrize("auto", [False, True], ids=["auto-off", "auto-on"])
@pytest.mark.parametrize("kind", _KINDS)
def test_a_drainer_disposing_the_container_does_not_hang(kind: str, auto: bool) -> None:
    # A's add waits in send for drainer B. B's dispose() would wait for A's
    # transaction, which closes the cycle, so B records the disposal for A.
    hub: MessageHub[object] = MessageHub()
    log = _HubLog(hub)
    container = _container(kind, "container", hub, auto)
    x = _child("x", hub)
    errors: list[BaseException] = []
    seen_before_add_returned: list[str] = []
    draining = threading.Event()

    def add_x() -> None:
        _add(container, x)
        seen_before_add_returned.extend(log.collection_changes)

    adder = _Worker("A", add_x)

    def dispose_when_a_waits() -> None:
        draining.set()
        wait_until_waiting(adder.ident)
        container.dispose()

    _on_trigger(hub, dispose_when_a_waits, errors)
    drainer = _Worker("B", lambda: hub.send(_trigger())).start()
    assert draining.wait(HANG_GUARD)
    adder.start()
    drainer.join()
    adder.join()

    assert errors == []
    assert drainer.error is None
    assert container.status is S.DISPOSED
    if auto:
        assert type(adder.error) is RuntimeError, adder.error
        assert x not in container
        assert x.status is S.DESTRUCTED
    else:
        assert adder.error is None
        assert seen_before_add_returned == ["A"]
        assert log.disposals["x"] == 1


@pytest.mark.parametrize("kind", _KINDS)
def test_a_send_inside_the_transaction_does_not_hang_on_a_waiting_disposal(kind: str) -> None:
    # Reverse order: drainer B's dispose() waits for A's transaction first.
    # A's send would then wait for B, which closes the cycle, so A's message
    # is enqueued for B's drain (spec/03 §4).
    hub: MessageHub[object] = MessageHub()
    log = _HubLog(hub)
    container = _container(kind, "container", hub, auto=False)
    x = _child("x", hub)
    errors: list[BaseException] = []
    draining = threading.Event()
    local_subscriber_running = threading.Event()
    disposer: list[_Worker] = []

    def hold_until_b_waits(event: Any) -> None:
        if event.action == "add":
            local_subscriber_running.set()
            try:
                wait_until_waiting(disposer[0].ident)
            except TimeoutError as error:
                errors.append(error)

    container.on_collection_changed.subscribe(hold_until_b_waits)
    adder = _Worker("A", lambda: _add(container, x))

    def dispose_after_a_subscriber() -> None:
        draining.set()
        assert local_subscriber_running.wait(HANG_GUARD)
        container.dispose()

    _on_trigger(hub, dispose_after_a_subscriber, errors)
    disposer.append(_Worker("B", lambda: hub.send(_trigger())))
    disposer[0].start()
    assert draining.wait(HANG_GUARD)
    adder.start()
    disposer[0].join()
    adder.join()

    assert errors == []
    assert disposer[0].error is None
    assert adder.error is None
    assert container.status is S.DISPOSED
    assert log.disposals["x"] == 1


@pytest.mark.parametrize("kind", _KINDS)
def test_disposing_another_container_keeps_the_add_send_synchronous(kind: str) -> None:
    # Control (HUB-013): no cycle, so A's send waits for drainer B and is
    # delivered on A before add() returns.
    hub: MessageHub[object] = MessageHub()
    log = _HubLog(hub)
    container = _container(kind, "container", hub, auto=False)
    other = _container(kind, "other", hub, auto=False)
    x = _child("x", hub)
    errors: list[BaseException] = []
    seen_before_add_returned: list[str] = []
    draining = threading.Event()

    def add_x() -> None:
        _add(container, x)
        seen_before_add_returned.extend(log.collection_changes)

    adder = _Worker("A", add_x)

    def dispose_other_when_a_waits() -> None:
        draining.set()
        wait_until_waiting(adder.ident)
        other.dispose()

    _on_trigger(hub, dispose_other_when_a_waits, errors)
    drainer = _Worker("B", lambda: hub.send(_trigger())).start()
    assert draining.wait(HANG_GUARD)
    adder.start()
    drainer.join()
    adder.join()

    assert errors == []
    assert adder.error is None
    assert other.status is S.DISPOSED
    assert container.status is S.CONSTRUCTED
    assert seen_before_add_returned == ["A"]

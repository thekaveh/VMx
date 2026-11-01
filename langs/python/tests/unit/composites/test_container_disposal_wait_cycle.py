"""A cross-thread dispose() waits for the container's open membership
transaction (ADR-0122), unless that wait would close a wait-for cycle. Then it
records the intent, and the transaction owner disposes the container when its
transaction ends (ADR-0153, #1059).
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx._wait_for_graph import WAITS
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
_KINDS = ("composite", "group")


def _container(kind: str, name: str, hub: MessageHub[object]) -> Any:
    builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
    container = (
        builder.name(name).services(hub, RxDispatcher.immediate()).children(lambda: []).build()
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


def _disposals(hub: MessageHub[object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    hub.messages.subscribe(
        lambda message: (
            counts.update([message.sender_name])
            if isinstance(message, ConstructionStatusChangedMessage)
            and message.status is S.DISPOSED
            else None
        )
    )
    return counts


def _start(action: Any, errors: list[BaseException]) -> threading.Thread:
    def run() -> None:
        try:
            action()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("kind", _KINDS)
def test_opposing_disposals_inside_transactions_complete(kind: str) -> None:
    hub: MessageHub[object] = MessageHub()
    disposals = _disposals(hub)
    x = _container(kind, "x", hub)
    z = _container(kind, "z", hub)
    a, b = _child("a", hub), _child("b", hub)
    barrier = threading.Barrier(2)

    def dispose_other(other: Any) -> Any:
        def on_changed(event: Any) -> None:
            if event.action == "add":
                barrier.wait(HANG_GUARD)
                other.dispose()

        return on_changed

    x.on_collection_changed.subscribe(dispose_other(z))
    z.on_collection_changed.subscribe(dispose_other(x))
    errors: list[BaseException] = []
    first = _start(lambda: _add(x, a), errors)
    second = _start(lambda: _add(z, b), errors)
    first.join(HANG_GUARD)
    second.join(HANG_GUARD)

    assert not first.is_alive() and not second.is_alive(), "opposing disposals must not hang"
    assert errors == []
    assert x.status is S.DISPOSED
    assert z.status is S.DISPOSED
    assert disposals["a"] == 1
    assert disposals["b"] == 1


@pytest.mark.parametrize("kind", _KINDS)
def test_one_sided_disposal_still_waits_for_the_transaction(kind: str) -> None:
    # No wait cycle: z.dispose() waits until z's transaction on the other
    # thread ends, then disposes z.
    hub: MessageHub[object] = MessageHub()
    x = _container(kind, "x", hub)
    z = _container(kind, "z", hub)
    a, b = _child("a", hub), _child("b", hub)
    z_entered = threading.Event()
    release_z = threading.Event()
    order: list[str] = []
    status_after_dispose: list[ConstructionStatus] = []

    def hold_z(event: Any) -> None:
        if event.action == "add":
            z_entered.set()
            assert release_z.wait(2 * HANG_GUARD)
            order.append("z transaction ends")

    def dispose_z(event: Any) -> None:
        if event.action == "add":
            z.dispose()
            status_after_dispose.append(z.status)
            order.append("z.dispose() returned")

    z.on_collection_changed.subscribe(hold_z)
    x.on_collection_changed.subscribe(dispose_z)
    errors: list[BaseException] = []
    holder = _start(lambda: _add(z, b), errors)
    assert z_entered.wait(HANG_GUARD)
    disposer = _start(lambda: _add(x, a), errors)
    try:
        deadline = time.monotonic() + HANG_GUARD
        while not WAITS.is_waiting_for_testing(disposer.ident or 0):
            assert disposer.is_alive(), "z.dispose() returned without waiting"
            assert time.monotonic() < deadline, "z.dispose() never waited"
            time.sleep(0.001)
    finally:
        release_z.set()
    holder.join(3 * HANG_GUARD)
    disposer.join(3 * HANG_GUARD)

    assert not holder.is_alive() and not disposer.is_alive()
    assert errors == []
    assert order == ["z transaction ends", "z.dispose() returned"]
    assert status_after_dispose == [S.DISPOSED]
    assert z.status is S.DISPOSED
    assert x.status is S.CONSTRUCTED

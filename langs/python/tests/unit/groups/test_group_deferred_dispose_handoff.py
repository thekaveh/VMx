"""The GroupVM deferred-dispose handoff admits no other thread's add (#1153).

A ``dispose()`` inside the owner's own membership transaction is deferred.
When the transaction ends, the owner calls ``dispose()`` again (the handoff).
The deferral stays set until that call admits the disposal, as in
``CompositeVM`` (#1064), so an add that another thread starts in between is
refused as disposal in progress (spec/06 §4.2, spec/07).

The tests widen the gap with an instance ``dispose`` wrapper that acts on the
second main-thread call, which is the handoff.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from tests.liveness import HANG_GUARD, join_thread, wait_event
from vmx.collections import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
_DISPATCHER = RxDispatcher.immediate()


def _child(hub: MessageHub[Any], name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, _DISPATCHER).build()


def _group(hub: MessageHub[Any]) -> GroupVM[ComponentVM]:
    group: GroupVM[ComponentVM] = (
        GroupVMBuilder[ComponentVM]()
        .name("group")
        .services(hub, _DISPATCHER)
        .children(lambda: [])
        .build()
    )
    group.construct()
    return group


def _start(action: Callable[[], object], errors: list[BaseException]) -> threading.Thread:
    def run() -> None:
        try:
            action()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _wrap_handoff(group: GroupVM[ComponentVM], on_handoff: Callable[[], None]) -> None:
    """Run *on_handoff* on the second main-thread dispose() call, then dispose."""
    main = threading.get_ident()
    calls: list[int] = []
    original_dispose = group.dispose

    def dispose() -> None:
        if threading.get_ident() == main:
            calls.append(1)
            if len(calls) == 2:  # the handoff from the transaction end
                on_handoff()
        original_dispose()

    group.dispose = dispose  # type: ignore[method-assign]
    group.on_collection_changed.subscribe(
        lambda _event: group.dispose() if threading.get_ident() == main else None
    )


def test_handoff_refuses_a_foreign_add_that_starts_before_dispose_admits() -> None:
    # Variant A: the hook joins the worker inside the gap.
    hub: MessageHub[Any] = MessageHub()
    group = _group(hub)
    b, x = _child(hub, "b"), _child(hub, "x")
    x.construct()
    errors: list[BaseException] = []
    handoffs: list[int] = []

    def foreign_add() -> None:
        handoffs.append(1)
        worker = _start(lambda: group.add(x), errors)
        join_thread(worker)
        assert not worker.is_alive()

    _wrap_handoff(group, foreign_add)
    group.add(b)

    assert handoffs == [1]
    assert [type(error) for error in errors] == [RuntimeError]
    assert "disposing" in str(errors[0])
    assert not any(child is x for child in group.snapshot())
    assert x.status is S.CONSTRUCTED
    assert group.status is S.DISPOSED


def test_handoff_does_not_wait_for_a_foreign_add_that_waits_for_the_owner() -> None:
    # Variant C: the worker's handler waits for the owner's add to return. If
    # the worker were admitted, the handoff dispose would wait for its
    # transaction and each thread would wait for the other until HANG_GUARD.
    hub: MessageHub[Any] = MessageHub()
    group = _group(hub)
    b, x = _child(hub, "b"), _child(hub, "x")
    main = threading.get_ident()
    owner_returned = threading.Event()
    worker_saw_owner_return: list[bool] = []
    errors: list[BaseException] = []
    workers: list[threading.Thread] = []

    def worker_handler(_event: CollectionChangedEvent) -> None:
        if threading.get_ident() != main:
            worker_saw_owner_return.append(wait_event(owner_returned))

    group.on_collection_changed.subscribe(worker_handler)
    _wrap_handoff(group, lambda: workers.append(_start(lambda: group.add(x), errors)))

    try:
        group.add(b)
    finally:
        owner_returned.set()
    assert len(workers) == 1
    join_thread(workers[0], 3 * HANG_GUARD)
    assert not workers[0].is_alive()

    assert worker_saw_owner_return == []
    assert [type(error) for error in errors] == [RuntimeError]
    assert "disposing" in str(errors[0])
    assert not any(child is x for child in group.snapshot())
    assert x.status is not S.DISPOSED
    assert group.status is S.DISPOSED

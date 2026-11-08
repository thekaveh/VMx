"""A wait for another thread's child ownership lock records an edge (#1155).

The wait-for graph refuses the wait that would close a cycle, so the
structural operation raises ``RuntimeError`` before it mutates anything
instead of hanging (spec/03 §4.1, ADR-0172). A wait that closes no cycle
still blocks until the lock is released.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from tests.wait_graph_seams import wait_until_waiting
from vmx._wait_for_graph import WAITS
from vmx.components.base import _hold_ownership_identity, _release_ownership_identity
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
_KINDS = ("composite", "group")


def _container(kind: str, name: str, hub: MessageHub[object]) -> Any:
    builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
    container = (
        builder.name(name)
        .services(hub, RxDispatcher.immediate())
        .auto_construct_on_add(True)
        .children(lambda: [])
        .build()
    )
    container.construct()
    return container


def _child(name: str, hub: MessageHub[object], hook: Any) -> ComponentVM:
    acted = False

    def once() -> None:
        nonlocal acted
        if not acted:
            acted = True
            hook()

    return (
        ComponentVMBuilder()
        .name(name)
        .services(hub, RxDispatcher.immediate())
        .on_construct(once)
        .build()
    )


def _add(container: Any, child: ComponentVM) -> None:
    if hasattr(container, "append"):
        container.append(child)
    else:
        container.add(child)


class _Worker:
    def __init__(self, action: Any) -> None:
        self.error: BaseException | None = None
        self.started = threading.Event()

        def run() -> None:
            self.started.set()
            try:
                action()
            except BaseException as error:
                self.error = error

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert self.started.wait(HANG_GUARD)

    @property
    def ident(self) -> int:
        return self.thread.ident or 0

    def join(self) -> None:
        self.thread.join(3 * HANG_GUARD)
        assert not self.thread.is_alive(), "ownership wait hung"


def _memberships(child: ComponentVM, *containers: Any) -> int:
    return sum(child in container for container in containers)


@pytest.mark.parametrize("kind", _KINDS)
def test_crossed_ownership_lock_waits_raise_instead_of_hanging(kind: str) -> None:
    # Case 1: T1 holds aa's lock and waits for bb's; T2 holds bb's and waits
    # for aa's. The wait that closes the cycle raises RuntimeError.
    hub: MessageHub[object] = MessageHub()
    g1, g2, g3, g4 = (_container(kind, name, hub) for name in ("g1", "g2", "g3", "g4"))
    barrier = threading.Barrier(2)
    aa = _child("aa", hub, lambda: (barrier.wait(HANG_GUARD), _add(g3, bb)))
    bb = _child("bb", hub, lambda: (barrier.wait(HANG_GUARD), _add(g4, aa)))

    first = _Worker(lambda: _add(g1, aa))
    second = _Worker(lambda: _add(g2, bb))
    first.join()
    second.join()

    errors = [worker.error for worker in (first, second) if worker.error is not None]
    assert errors, "one crossed ownership wait must be refused"
    assert all(type(error) is RuntimeError for error in errors), errors
    assert _memberships(aa, g1, g2, g3, g4) == 1
    assert _memberships(bb, g1, g2, g3, g4) == 1


@pytest.mark.parametrize("kind", _KINDS)
def test_an_ownership_lock_wait_and_a_disposal_wait_do_not_hang(kind: str) -> None:
    # Case 2: T1 holds b's lock and its disposal of g2 waits for T2's g2
    # transaction. T2 then waits for b's lock, which closes the cycle, so T2's
    # add raises RuntimeError and T1's disposal completes (spec/06 §4.2).
    hub: MessageHub[object] = MessageHub()
    g1, g2, g3 = (_container(kind, name, hub) for name in ("g1", "g2", "g3"))
    b_entered = threading.Event()
    y_entered = threading.Event()
    disposer: list[_Worker] = []
    disposer_known = threading.Event()

    def b_hook() -> None:
        b_entered.set()
        assert y_entered.wait(HANG_GUARD)
        g2.dispose()

    def y_hook() -> None:
        y_entered.set()
        assert b_entered.wait(HANG_GUARD)
        assert disposer_known.wait(HANG_GUARD)
        wait_until_waiting(disposer[0].ident)
        _add(g3, b)

    b = _child("b", hub, b_hook)
    y = _child("y", hub, y_hook)

    second = _Worker(lambda: _add(g2, y))
    disposer.append(_Worker(lambda: _add(g1, b)))
    disposer_known.set()
    disposer[0].join()
    second.join()

    assert disposer[0].error is None
    assert type(second.error) is RuntimeError, second.error
    assert g2.status is S.DISPOSED
    assert _memberships(b, g1, g3) == 1


@pytest.mark.parametrize("kind", _KINDS)
def test_a_contested_ownership_wait_without_a_cycle_still_waits(kind: str) -> None:
    hub: MessageHub[object] = MessageHub()
    g1, g2 = _container(kind, "g1", hub), _container(kind, "g2", hub)
    hook_entered = threading.Event()
    release_hook = threading.Event()

    def hold() -> None:
        hook_entered.set()
        assert release_hook.wait(2 * HANG_GUARD)

    c = _child("c", hub, hold)
    first = _Worker(lambda: _add(g1, c))
    assert hook_entered.wait(HANG_GUARD)
    second_done = threading.Event()
    second = _Worker(lambda: (_add(g2, c), second_done.set()))
    try:
        wait_until_waiting(second.ident)
        assert not second_done.wait(0.05), "the contested wait returned while the lock was held"
    finally:
        release_hook.set()
    first.join()
    second.join()

    assert first.error is None
    assert second.error is None
    assert c not in g1
    assert c in g2


def test_a_recursive_hold_stays_recorded_until_its_last_release() -> None:
    # Factory population reserves a child and then takes its lock again, so
    # the holder must stay recorded until its last hold ends (#1155).
    hub: MessageHub[object] = MessageHub()
    child = _child("c", hub, lambda: None)
    lock = child._ownership_lock
    assert _hold_ownership_identity(child)
    assert _hold_ownership_identity(child)

    _release_ownership_identity(child)
    holder_after_one_release = WAITS._owners.get(lock)
    _release_ownership_identity(child)

    assert holder_after_one_release == threading.get_ident()
    assert lock not in WAITS._owners

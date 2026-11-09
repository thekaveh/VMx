"""A child walk that waited resumes on its owner's foreground dispatcher (#1326).

A composite on dispatcher ``D1`` waits on a background child on dispatcher
``D2``. The child settles on ``D2``'s foreground thread. The rest of the walk,
the ``current`` change, the consumer callbacks and the later sibling changes
then run on ``D1``'s foreground thread, not on ``D2``'s. A walk whose
children all settle at once still finishes on the caller (ADR-0218, spec/02
§6, spec/11 §4).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

import pytest
from reactivex.scheduler import EventLoopScheduler

from tests.liveness import wait_event
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


def _loop(name: str) -> EventLoopScheduler:
    def factory(target: Callable[[], None]) -> threading.Thread:
        return threading.Thread(target=target, name=name, daemon=True)

    return EventLoopScheduler(thread_factory=factory)


@pytest.fixture
def loops() -> Iterator[dict[str, EventLoopScheduler]]:
    schedulers = {name: _loop(name) for name in ("FG", "BG", "CHILD_FG", "CHILD_BG")}
    yield schedulers
    for scheduler in schedulers.values():
        scheduler.dispose()


class _Log:
    """Records ``label@thread`` entries from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: list[str] = []

    def add(self, label: str) -> None:
        with self._lock:
            self.entries.append(f"{label}@{threading.current_thread().name}")

    def threads_of(self, label: str) -> set[str]:
        with self._lock:
            return {entry.split("@")[1] for entry in self.entries if entry.split("@")[0] == label}


def _on_fg(loops: dict[str, EventLoopScheduler], action: Callable[[], None]) -> None:
    loops["FG"].schedule(lambda _s, _st: action())


def _wait_for_status(vm: ComponentVM | CompositeVM[ComponentVM], status: S) -> None:
    reached = threading.Event()
    subscription = vm.property_changed.subscribe(
        lambda name: reached.set() if name == "status" and vm.status is status else None
    )
    try:
        if vm.status is not status:
            assert wait_event(reached), f"{vm.name} reaches {status.name}"
    finally:
        subscription.dispose()


def test_walk_resumes_on_the_owner_foreground(loops: dict[str, EventLoopScheduler]) -> None:
    d1 = RxDispatcher(loops["FG"], loops["BG"])
    d2 = RxDispatcher(loops["CHILD_FG"], loops["CHILD_BG"])
    hub: MessageHub[object] = MessageHub()
    log = _Log()

    b = ComponentVMBuilder().name("B").services(hub, d2).background(True).build()
    x = (
        ComponentVMBuilder()
        .name("X")
        .services(hub, d1)
        .on_destruct(lambda: log.add("X.on_destruct"))
        .build()
    )
    c = (
        CompositeVMBuilder[ComponentVM]()
        .name("C")
        .services(hub, d1)
        .children(lambda: [b, x])
        .current(lambda _members: x)
        .on_current_changed(lambda _vm: log.add("on_current_changed"))
        .on_destruct(lambda: log.add("C.on_destruct"))
        .build()
    )
    x.property_changed.subscribe(lambda name: log.add(f"X.{name}"))
    b.property_changed.subscribe(
        lambda name: log.add(f"B.{b.status.name}") if name == "status" else None
    )
    c.property_changed.subscribe(lambda name: log.add(f"C.{name}"))

    _on_fg(loops, c.construct)
    _wait_for_status(c, S.CONSTRUCTED)
    assert c.current is x

    _on_fg(loops, c.destruct)
    _wait_for_status(c, S.DESTRUCTED)

    for label in (
        "X.status",
        "X.is_current",
        "C.current",
        "on_current_changed",
        "X.on_destruct",
        "C.on_destruct",
        "C.status",
    ):
        assert log.threads_of(label) == {"FG"}, f"{label}: {log.entries}"
    assert log.threads_of("B.CONSTRUCTED") == {"CHILD_FG"}
    assert log.threads_of("B.DESTRUCTED") == {"CHILD_FG"}


def test_walk_whose_children_settle_at_once_finishes_on_the_caller(
    loops: dict[str, EventLoopScheduler],
) -> None:
    d1 = RxDispatcher(loops["FG"], loops["BG"])
    hub: MessageHub[object] = MessageHub()
    log = _Log()
    x = ComponentVMBuilder().name("X").services(hub, d1).build()
    c = (
        CompositeVMBuilder[ComponentVM]()
        .name("C")
        .services(hub, d1)
        .children(lambda: [x])
        .current(lambda _members: x)
        .on_current_changed(lambda _vm: log.add("on_current_changed"))
        .build()
    )
    after_construct: list[S] = []
    done = threading.Event()

    def construct() -> None:
        c.construct()
        after_construct.append(c.status)
        done.set()

    _on_fg(loops, construct)
    assert wait_event(done)
    assert after_construct == [S.CONSTRUCTED], "construct() returns with the walk finished"
    assert log.threads_of("on_current_changed") == {"FG"}

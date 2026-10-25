"""Factory population joins background children; it never restarts them.

Population starts every factory child before the child walk runs. A later
background child that fails while the walk waits on an earlier one is final:
the walk joins it, rolls the container back, and never re-runs its hook
(spec/02 §6, LIFE-014).
"""

from __future__ import annotations

from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class _LifoScheduler:
    """Runs the newest background work first and collects its failures."""

    def __init__(self) -> None:
        self.actions: list[Any] = []
        self.errors: list[BaseException] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run_all(self) -> None:
        while self.actions:
            action = self.actions.pop()
            try:
                action(self, None)
            except Exception as error:
                self.errors.append(error)


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_later_failing_child_is_joined_and_rolls_the_container_back(kind: str) -> None:
    bg = _LifoScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    bad_hook_runs: list[None] = []

    def fail() -> None:
        bad_hook_runs.append(None)
        raise RuntimeError("bad failed")

    ok = ComponentVMBuilder().name("ok").services(hub, dispatcher).background(True).build()
    bad = (
        ComponentVMBuilder()
        .name("bad")
        .services(hub, dispatcher)
        .background(True)
        .on_construct(fail)
        .build()
    )
    builder = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    container = builder.name("root").services(hub, dispatcher).children(lambda: [ok, bad]).build()

    container.construct()
    assert ok.status is ConstructionStatus.CONSTRUCTING
    assert bad.status is ConstructionStatus.CONSTRUCTING
    bg.run_all()

    assert len(bad_hook_runs) == 1
    assert bad.status is ConstructionStatus.DESTRUCTED
    assert container.status is ConstructionStatus.DESTRUCTED
    assert container.can_construct()


class _SettleAfterJoinRead:
    """Wraps a child's lifecycle lock and settles the child inside a join.

    The first time the lock is released while `_join_transition_future` runs,
    the wrapper runs the child's pending background construct, which settles
    the child. A join that reads the status and registers its waiter in one
    lock scope has already registered by then, so the settle resolves the
    waiter. A join that releases the lock between the two steps registers on a
    settled child, and the container never settles.
    """

    def __init__(self, lock: Any, settle: Any) -> None:
        self._lock = lock
        self._settle = settle
        self.in_join = False
        self.injections = 0

    def __enter__(self) -> Any:
        return self._lock.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        result = self._lock.__exit__(*exc)
        if self.in_join and self.injections == 0:
            self.injections += 1
            self._settle()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._lock, name)


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_joined_child_that_settles_during_the_join_check_is_never_restarted(kind: str) -> None:
    """A joined child that settles right after the join reads its status stays final."""
    bg = _LifoScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    bad_hook_runs: list[None] = []

    def fail() -> None:
        bad_hook_runs.append(None)
        raise RuntimeError("bad failed")

    ok = ComponentVMBuilder().name("ok").services(hub, dispatcher).background(True).build()
    bad = (
        ComponentVMBuilder()
        .name("bad")
        .services(hub, dispatcher)
        .background(True)
        .on_construct(fail)
        .build()
    )
    builder = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    container = builder.name("root").services(hub, dispatcher).children(lambda: [ok, bad]).build()

    container.construct()
    ok_action, bad_action = bg.actions

    def settle_bad() -> None:
        bg.actions.remove(bad_action)
        try:
            bad_action(bg, None)
        except RuntimeError as error:
            bg.errors.append(error)

    lock = _SettleAfterJoinRead(bad._lifecycle_lock, settle_bad)
    bad._lifecycle_lock = lock  # type: ignore[assignment]
    join = bad._join_transition_future

    def joining(*, construct: bool) -> Any:
        lock.in_join = True
        try:
            return join(construct=construct)
        finally:
            lock.in_join = False

    bad._join_transition_future = joining  # type: ignore[method-assign]
    bg.actions.remove(ok_action)
    ok_action(bg, None)
    bg.run_all()

    assert lock.injections == 1
    assert len(bad_hook_runs) == 1
    assert bad.status is ConstructionStatus.DESTRUCTED
    assert container.status is ConstructionStatus.DESTRUCTED

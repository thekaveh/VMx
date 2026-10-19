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


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_joined_child_that_settles_during_the_join_check_is_never_restarted(kind: str) -> None:
    """A joined child that fails between the status check and the join stays final."""
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
    base = type(bad)
    armed = [False]
    bad_action: list[Any] = []

    def racy_status(self: ComponentVM) -> ConstructionStatus:
        # Settle the child to Destructed right after a reader observes Constructing.
        status = base.status.fget(self)  # type: ignore[attr-defined]
        if armed[0] and status is ConstructionStatus.CONSTRUCTING:
            armed[0] = False
            bg.actions.remove(bad_action[0])
            try:
                bad_action[0](bg, None)
            except RuntimeError as error:
                bg.errors.append(error)
        return status  # type: ignore[no-any-return]

    bad.__class__ = type("RacyComponentVM", (base,), {"status": property(racy_status)})
    builder = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    container = builder.name("root").services(hub, dispatcher).children(lambda: [ok, bad]).build()

    container.construct()
    ok_action, bad_work = bg.actions
    bad_action.append(bad_work)
    armed[0] = True
    bg.actions.remove(ok_action)
    ok_action(bg, None)
    bg.run_all()

    assert len(bad_hook_runs) == 1
    assert bad.status is ConstructionStatus.DESTRUCTED
    assert container.status is ConstructionStatus.DESTRUCTED

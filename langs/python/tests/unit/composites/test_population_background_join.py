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

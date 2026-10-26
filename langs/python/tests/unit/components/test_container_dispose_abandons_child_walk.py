"""Disposing a container abandons its pending child walk first.

A container disposed while its child walk waits for a background child
abandons that walk before it disposes the children. The walk then fails
because its child was disposed, but the container publishes no rollback
status: only its transient status and ``DISPOSED`` (spec/02 §6, LIFE-013,
#755). The foreground runs work inline, so a rollback would otherwise be
published before ``DISPOSED``.
"""

from __future__ import annotations

from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.aggregates.builders import AggregateVM1Builder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
KINDS = ["composite", "group", "aggregate"]


class _QueueScheduler:
    """Queues background work so the test decides when it runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run_all(self) -> None:
        while self.actions:
            self.actions.pop(0)(self, None)


class _Setup:
    def __init__(self, kind: str) -> None:
        self.background = _QueueScheduler()
        dispatcher = RxDispatcher(ImmediateScheduler(), self.background)  # type: ignore[arg-type]
        hub: MessageHub[object] = MessageHub()
        self.statuses: list[ConstructionStatus] = []
        hub.messages.subscribe(self._record)
        child = ComponentVM(name="B", hint="", hub=hub, dispatcher=dispatcher, background=True)
        self.container: Any
        if kind == "composite":
            self.container = (
                CompositeVMBuilder[ComponentVM]()
                .name("P")
                .services(hub, dispatcher)
                .children(lambda: [child])
                .build()
            )
        elif kind == "group":
            self.container = (
                GroupVMBuilder[ComponentVM]()
                .name("P")
                .services(hub, dispatcher)
                .children(lambda: [child])
                .build()
            )
        else:
            self.container = (
                AggregateVM1Builder[ComponentVM]()
                .name("P")
                .services(hub, dispatcher)
                .component_1(lambda: child)
                .build()
            )

    def _record(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage) and message.sender_name == "P":
            self.statuses.append(message.status)

    def constructed(self) -> _Setup:
        self.container.construct()
        self.background.run_all()
        assert self.container.status is S.CONSTRUCTED
        self.statuses.clear()
        return self


@pytest.mark.parametrize("kind", KINDS)
def test_dispose_during_background_construct_publishes_no_rollback(kind: str) -> None:
    setup = _Setup(kind)

    setup.container.construct()
    setup.container.dispose()
    setup.background.run_all()

    assert setup.statuses == [S.CONSTRUCTING, S.DISPOSED]
    assert setup.container.status is S.DISPOSED


@pytest.mark.parametrize("kind", KINDS)
def test_dispose_during_background_destruct_publishes_no_rollback(kind: str) -> None:
    setup = _Setup(kind).constructed()

    setup.container.destruct()
    setup.container.dispose()
    setup.background.run_all()

    assert setup.statuses == [S.DESTRUCTING, S.DISPOSED]
    assert setup.container.status is S.DISPOSED


@pytest.mark.parametrize("kind", KINDS)
def test_dispose_during_background_reconstruct_publishes_no_rollback(kind: str) -> None:
    setup = _Setup(kind).constructed()

    setup.container.reconstruct()
    setup.container.dispose()
    setup.background.run_all()

    assert setup.statuses == [S.DESTRUCTING, S.DISPOSED]
    assert setup.container.status is S.DISPOSED

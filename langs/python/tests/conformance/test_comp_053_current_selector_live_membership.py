"""Conformance test: COMP-053 — the ``current`` selector reads the live membership.

The selector runs after every child reached Constructed. It receives the
composite's membership when it runs, so it can pick a child that an add
attached while the walk waited (ADR-0218, spec/06 §3.2).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _Queue:
    """Queues background work so the test decides when it runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run_all(self) -> None:
        while self.actions:
            self.actions.pop(0)(self, None)


@pytest.mark.conformance("COMP-053")
def test_COMP_053_selector_receives_the_live_membership() -> None:
    bg = _Queue()
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]

    def child(name: str, *, background: bool = False) -> ComponentVM:
        return (
            ComponentVMBuilder().name(name).services(hub, dispatcher).background(background).build()
        )

    a = child("a", background=True)
    late = child("l")
    inputs: list[list[ComponentVM]] = []

    def select(members: Iterable[ComponentVM]) -> ComponentVM | None:
        seen = list(members)
        inputs.append(seen)
        return late if any(member is late for member in seen) else None

    composite = (
        CompositeVMBuilder[ComponentVM]()
        .name("p")
        .services(hub, dispatcher)
        .children(lambda: [a])
        .auto_construct_on_add(True)
        .current(select)
        .build()
    )

    composite.construct()
    assert composite.status is S.CONSTRUCTING, "the walk waits on the background member"
    composite.add(late)
    bg.run_all()

    assert composite.status is S.CONSTRUCTED
    assert len(inputs) == 1, "the selector ran once"
    assert any(member is a for member in inputs[0])
    assert any(member is late for member in inputs[0])
    assert composite.current is late
    assert late.is_current

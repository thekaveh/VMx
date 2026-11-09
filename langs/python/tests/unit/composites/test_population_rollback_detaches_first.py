"""A population rollback detaches a child before it compensates it (#1372).

The deferred compensation of ADR-0218 rule 7 destructs a background child
only when the child has no parent. So the rollback clears the parent first.
Here the background child settles while compensation joins it, so the
settle callback runs at once. The child must still end ``Destructed``
(spec/06 §4.2).
"""

from __future__ import annotations

from concurrent.futures import Future
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


def _failing_hook() -> None:
    raise RuntimeError("population failed")


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_population_rollback_destructs_a_child_that_settles_during_compensation(
    kind: str,
) -> None:
    bg = _Queue()
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    child = ComponentVMBuilder().name("c").services(hub, dispatcher).background(True).build()
    blocker = (
        ComponentVMBuilder()
        .name("blocker")
        .services(hub, dispatcher)
        .on_construct(_failing_hook)
        .build()
    )
    join = child._join_transition_future

    def settle_then_join(*, construct: bool) -> Future[None]:
        # The background construct settles between the status read and the
        # join, so the returned future is already done.
        bg.run_all()
        return join(construct=construct)

    child._join_transition_future = settle_then_join  # type: ignore[method-assign]
    builder: Any = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    root = builder.name("root").services(hub, dispatcher).children(lambda: [child, blocker]).build()

    with pytest.raises(RuntimeError, match="population failed"):
        root.construct()

    bg.run_all()
    assert child._parent is None
    assert child.status is S.DESTRUCTED

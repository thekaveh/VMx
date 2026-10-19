"""Auto-construct-on-add while the container is still Constructing.

A container's construct() completes only when every child has reached
Constructed (spec/02 §6). With ``auto_construct_on_add(True)``, a child added
while the container waits on a background child is constructed at add time
and joined by the child walk, so the container never reports Constructed with
an unconstructed added child. Mirrors the C# and TypeScript tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

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


class _QueueScheduler:
    """Queues background work so a test decides when each item runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run_first(self) -> None:
        self.actions.pop(0)(self, None)

    def run_last(self) -> None:
        self.actions.pop()(self, None)

    def run_all(self) -> None:
        while self.actions:
            self.run_first()


class _Container(Protocol):
    @property
    def status(self) -> ConstructionStatus: ...

    def construct(self) -> None: ...

    def add(self, item: ComponentVM) -> None: ...


ChildFactory = Callable[..., ComponentVM]


def _setup(
    kind: str, *, auto_construct: bool = True
) -> tuple[_QueueScheduler, ChildFactory, ComponentVM, _Container]:
    bg = _QueueScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()

    def child(
        name: str, *, background: bool = False, on_construct: Callable[[], None] | None = None
    ) -> ComponentVM:
        builder = ComponentVMBuilder().name(name).services(hub, dispatcher).background(background)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        return builder.build()

    first = child("first", background=True)
    builder = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    root = (
        builder.name("root")
        .services(hub, dispatcher)
        .children(lambda: [first])
        .auto_construct_on_add(auto_construct)
        .build()
    )
    return bg, child, first, root


KINDS = pytest.mark.parametrize("kind", ["composite", "group"])


@KINDS
def test_foreground_child_added_during_background_wait_is_constructed(kind: str) -> None:
    bg, child, _first, root = _setup(kind)
    root.construct()
    assert root.status is S.CONSTRUCTING

    late = child("late")
    root.add(late)
    assert late.status is S.CONSTRUCTED

    bg.run_all()
    assert root.status is S.CONSTRUCTED
    assert late.status is S.CONSTRUCTED


@KINDS
def test_container_waits_for_late_background_child(kind: str) -> None:
    bg, child, first, root = _setup(kind)
    root.construct()
    late = child("late", background=True)
    root.add(late)
    assert late.status is S.CONSTRUCTING

    bg.run_first()  # only the original child settles
    assert first.status is S.CONSTRUCTED
    assert late.status is S.CONSTRUCTING
    assert root.status is S.CONSTRUCTING

    bg.run_all()
    assert late.status is S.CONSTRUCTED
    assert root.status is S.CONSTRUCTED


@KINDS
def test_late_background_child_settling_first_is_joined(kind: str) -> None:
    bg, child, first, root = _setup(kind)
    root.construct()
    late = child("late", background=True)
    root.add(late)

    bg.run_last()  # the late child settles before the original one
    assert late.status is S.CONSTRUCTED
    assert root.status is S.CONSTRUCTING

    bg.run_all()
    assert first.status is S.CONSTRUCTED
    assert root.status is S.CONSTRUCTED


@KINDS
def test_failed_late_child_rolls_back_without_rerunning(kind: str) -> None:
    bg, child, _first, root = _setup(kind)
    root.construct()
    runs: list[None] = []

    def fail() -> None:
        runs.append(None)
        raise RuntimeError("late failed")

    late = child("late", background=True, on_construct=fail)
    root.add(late)
    with pytest.raises(RuntimeError, match="late failed"):
        bg.run_last()
    assert late.status is S.DESTRUCTED

    bg.run_all()
    assert len(runs) == 1
    assert root.status is S.DESTRUCTED


@KINDS
def test_without_auto_construct_late_child_is_left_alone(kind: str) -> None:
    bg, child, _first, root = _setup(kind, auto_construct=False)
    root.construct()
    late = child("late")
    root.add(late)

    bg.run_all()
    assert root.status is S.CONSTRUCTED
    assert late.status is S.DESTRUCTED

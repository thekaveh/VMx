"""Conformance tests: GRP-014 and COMP-046 — opt-in reverse destruct order.

With ``destruct_order(ChildOrder.REVERSE)`` a group or composite destructs and
disposes its children from the last index to the first. Construct order stays
in child order, and every child is disposed before the container publishes
Disposed (LIFE-013). The default keeps child order (ADR-0161).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import ChildOrder
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

NAMES = ("a", "b", "c")


class _Recorder:
    """Records child hook calls and the Disposed messages on the hub."""

    def __init__(self) -> None:
        self.hub: MessageHub[object] = MessageHub()
        self.dispatcher = RxDispatcher.immediate()
        self.events: list[str] = []
        self.disposed: list[str] = []
        self.hub.messages.subscribe(self._on_message)

    def _on_message(self, message: object) -> None:
        if (
            isinstance(message, ConstructionStatusChangedMessage)
            and message.status is ConstructionStatus.DISPOSED
        ):
            self.disposed.append(message.sender_name)

    def child(self, name: str) -> ComponentVM:
        return (
            ComponentVMBuilder()
            .name(name)
            .services(self.hub, self.dispatcher)
            .on_construct(lambda: self.events.append(f"construct:{name}"))
            .on_destruct(lambda: self.events.append(f"destruct:{name}"))
            .build()
        )

    def children(self) -> list[ComponentVM]:
        return [self.child(name) for name in NAMES]

    def take(self) -> list[str]:
        events = list(self.events)
        self.events.clear()
        return events


def _construct(names: tuple[str, ...]) -> list[str]:
    return [f"construct:{name}" for name in names]


def _destruct(names: tuple[str, ...]) -> list[str]:
    return [f"destruct:{name}" for name in names]


REVERSED = tuple(reversed(NAMES))

Factory = Callable[[_Recorder, ChildOrder | None], Any]


def _group(rec: _Recorder, order: ChildOrder | None) -> GroupVM[ComponentVM]:
    children = rec.children()
    builder = GroupVMBuilder[ComponentVM]().name("root").services(rec.hub, rec.dispatcher)
    if order is not None:
        builder = builder.destruct_order(order)
    return builder.children(lambda: children).build()


def _group_create(rec: _Recorder, order: ChildOrder | None) -> GroupVM[ComponentVM]:
    children = rec.children()
    if order is None:
        return GroupVM.create(
            name="root", hub=rec.hub, dispatcher=rec.dispatcher, children=lambda: children
        )
    return GroupVM.create(
        name="root",
        hub=rec.hub,
        dispatcher=rec.dispatcher,
        children=lambda: children,
        destruct_order=order,
    )


def _composite(rec: _Recorder, order: ChildOrder | None) -> CompositeVM[ComponentVM]:
    children = rec.children()
    builder = CompositeVMBuilder[ComponentVM]().name("root").services(rec.hub, rec.dispatcher)
    if order is not None:
        builder = builder.destruct_order(order)
    # A selector makes `current` non-null, so destruct also clears it first.
    builder = builder.current(lambda xs: next(iter(xs), None))
    return builder.children(lambda: children).build()


def _composite_create(rec: _Recorder, order: ChildOrder | None) -> CompositeVM[ComponentVM]:
    children = rec.children()
    if order is None:
        return CompositeVM.create(
            name="root", hub=rec.hub, dispatcher=rec.dispatcher, children=lambda: children
        )
    return CompositeVM.create(
        name="root",
        hub=rec.hub,
        dispatcher=rec.dispatcher,
        children=lambda: children,
        destruct_order=order,
    )


def _modeled_composite(rec: _Recorder, order: ChildOrder | None) -> Any:
    builder = (
        CompositeVMOfBuilder[str, ComponentVM]()
        .name("root")
        .services(rec.hub, rec.dispatcher)
        .children_models(lambda: NAMES)
        .child_model_to_child_view_model(rec.child)
    )
    if order is not None:
        builder = builder.destruct_order(order)
    return builder.build()


def _assert_reverse_order(factory: Factory) -> None:
    rec = _Recorder()
    container = factory(rec, ChildOrder.REVERSE)

    container.construct()
    assert rec.take() == _construct(NAMES)

    container.destruct()
    assert rec.take() == _destruct(REVERSED)
    assert container.status is ConstructionStatus.DESTRUCTED

    container.construct()
    assert rec.take() == _construct(NAMES)

    container.reconstruct()
    assert rec.take() == _destruct(REVERSED) + _construct(NAMES)
    assert container.status is ConstructionStatus.CONSTRUCTED

    container.dispose()
    # Every child is disposed, last first, before the container (LIFE-013).
    assert rec.disposed == [*REVERSED, "root"]
    assert all(child.status is ConstructionStatus.DISPOSED for child in container.snapshot())


def _assert_default_order(factory: Factory) -> None:
    rec = _Recorder()
    container = factory(rec, None)

    container.construct()
    assert rec.take() == _construct(NAMES)
    container.destruct()
    assert rec.take() == _destruct(NAMES)
    container.construct()
    rec.take()
    container.dispose()
    assert rec.disposed == [*NAMES, "root"]


@pytest.mark.conformance("GRP-014")
@pytest.mark.parametrize("factory", [_group, _group_create], ids=["builder", "create"])
def test_GRP_014_reverse_order_destructs_and_disposes_last_child_first(factory: Factory) -> None:
    _assert_reverse_order(factory)


@pytest.mark.conformance("GRP-014")
@pytest.mark.parametrize("factory", [_group, _group_create], ids=["builder", "create"])
def test_GRP_014_default_order_is_child_order(factory: Factory) -> None:
    _assert_default_order(factory)


@pytest.mark.conformance("COMP-046")
@pytest.mark.parametrize(
    "factory",
    [_composite, _composite_create, _modeled_composite],
    ids=["builder", "create", "modeled"],
)
def test_COMP_046_reverse_order_destructs_and_disposes_last_child_first(
    factory: Factory,
) -> None:
    _assert_reverse_order(factory)


@pytest.mark.conformance("COMP-046")
@pytest.mark.parametrize(
    "factory",
    [_composite, _composite_create, _modeled_composite],
    ids=["builder", "create", "modeled"],
)
def test_COMP_046_default_order_is_child_order(factory: Factory) -> None:
    _assert_default_order(factory)


# ---------------------------------------------------------------------------
# Background children: the walk waits on each child in the destruct order.
# ---------------------------------------------------------------------------


class _FifoScheduler:
    """Queues background work until the test runs it, oldest first."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run_all(self) -> None:
        while self.actions:
            self.actions.pop(0)(self, None)


@pytest.mark.parametrize(
    ("marker", "kind"),
    [
        pytest.param("GRP-014", "group", marks=pytest.mark.conformance("GRP-014")),
        pytest.param("COMP-046", "composite", marks=pytest.mark.conformance("COMP-046")),
    ],
)
def test_reverse_order_waits_on_background_children_last_first(marker: str, kind: str) -> None:
    bg = _FifoScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    events: list[str] = []

    def child(name: str) -> ComponentVM:
        return (
            ComponentVMBuilder()
            .name(name)
            .services(hub, dispatcher)
            .background(True)
            .on_destruct(lambda: events.append(name))
            .build()
        )

    children = [child(name) for name in NAMES]
    builder: Any = (
        GroupVMBuilder[ComponentVM]() if kind == "group" else CompositeVMBuilder[ComponentVM]()
    )
    container = (
        builder.name("root")
        .services(hub, dispatcher)
        .destruct_order(ChildOrder.REVERSE)
        .children(lambda: children)
        .build()
    )
    container.construct()
    bg.run_all()
    assert container.status is ConstructionStatus.CONSTRUCTED

    container.destruct()
    # Only the last child has started; the walk waits on it before the next.
    assert [c.status for c in children] == [
        ConstructionStatus.CONSTRUCTED,
        ConstructionStatus.CONSTRUCTED,
        ConstructionStatus.DESTRUCTING,
    ]
    bg.run_all()
    assert events == list(REVERSED), marker
    assert container.status is ConstructionStatus.DESTRUCTED

"""Containers wait for every background child, including the last one.

A container stays transient until each child settles. It publishes its own
terminal status only after the last child's terminal status, and it rolls back
when any child fails, wherever that child sits (spec/02 §6, §2.5, LIFE-014;
spec/11 §4).
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.aggregates.builders import AggregateVM2Builder, AggregateVM3Builder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

KINDS = ["composite", "group", "aggregate"]
LAYOUTS = ["sb", "bb", "ssb"]


class _Queue:
    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)


class _Env:
    def __init__(self) -> None:
        self.fg = _Queue()
        self.bg = _Queue()
        self.dispatcher = RxDispatcher(self.fg, self.bg)  # type: ignore[arg-type]
        self.hub: MessageHub[object] = MessageHub()
        self.log: list[str] = []
        self.errors: list[BaseException] = []
        self.hub.messages.subscribe(self._record)

    def _record(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            self.log.append(f"{message.sender_name}:{message.status.name}")

    def flush(self) -> None:
        while self.fg.actions or self.bg.actions:
            queue = self.fg if self.fg.actions else self.bg
            action = queue.actions.pop(0)
            try:
                action(queue, None)
            except Exception as error:
                self.errors.append(error)


def _leaf(
    env: _Env,
    name: str,
    background: bool,
    *,
    fail_construct: bool = False,
    fail_destruct: bool = False,
) -> ComponentVM:
    def on_construct() -> None:
        if fail_construct:
            raise RuntimeError(f"{name} construct failed")

    def on_destruct() -> None:
        if fail_destruct:
            raise RuntimeError(f"{name} destruct failed")

    return ComponentVM(
        name=name,
        hint="",
        hub=env.hub,
        dispatcher=env.dispatcher,
        on_construct=on_construct,
        on_destruct=on_destruct,
        background=background,
    )


def _container(env: _Env, kind: str, children: list[ComponentVM]) -> Any:
    if kind == "composite":
        return (
            CompositeVMBuilder[ComponentVM]()
            .name("P")
            .services(env.hub, env.dispatcher)
            .children(lambda: children)
            .build()
        )
    if kind == "group":
        return (
            GroupVMBuilder[ComponentVM]()
            .name("P")
            .services(env.hub, env.dispatcher)
            .children(lambda: children)
            .build()
        )
    if len(children) == 2:
        first, second = children
        return (
            AggregateVM2Builder[ComponentVM, ComponentVM]()
            .name("P")
            .services(env.hub, env.dispatcher)
            .component_1(lambda: first)
            .component_2(lambda: second)
            .build()
        )
    first, second, third = children
    return (
        AggregateVM3Builder[ComponentVM, ComponentVM, ComponentVM]()
        .name("P")
        .services(env.hub, env.dispatcher)
        .component_1(lambda: first)
        .component_2(lambda: second)
        .component_3(lambda: third)
        .build()
    )


def _children(env: _Env, layout: str, **last: bool) -> list[ComponentVM]:
    names = "ABC"
    return [
        _leaf(env, names[i], mode == "b", **(last if i == len(layout) - 1 else {}))
        for i, mode in enumerate(layout)
    ]


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("kind", KINDS)
def test_container_waits_for_last_background_child(kind: str, layout: str) -> None:
    env = _Env()
    children = _children(env, layout)
    last = children[-1]
    container = _container(env, kind, children)

    container.construct()
    assert container.status is ConstructionStatus.CONSTRUCTING
    env.flush()
    assert container.status is ConstructionStatus.CONSTRUCTED
    assert env.log.index("P:CONSTRUCTED") > env.log.index(f"{last.name}:CONSTRUCTED")

    env.log.clear()
    container.destruct()
    assert container.status is ConstructionStatus.DESTRUCTING
    env.flush()
    assert container.status is ConstructionStatus.DESTRUCTED
    assert env.log.index("P:DESTRUCTED") > env.log.index(f"{last.name}:DESTRUCTED")
    assert env.errors == []


@pytest.mark.parametrize("layout", ["sb", "bb"])
@pytest.mark.parametrize("kind", KINDS)
def test_failing_last_background_child_construct_rolls_container_back(
    kind: str, layout: str
) -> None:
    env = _Env()
    children = _children(env, layout, fail_construct=True)
    container = _container(env, kind, children)

    container.construct()
    env.flush()

    assert children[-1].status is ConstructionStatus.DESTRUCTED
    assert container.status is ConstructionStatus.DESTRUCTED
    assert "P:CONSTRUCTED" not in env.log
    assert container.can_construct()


@pytest.mark.parametrize("layout", ["sb", "bb"])
@pytest.mark.parametrize("kind", KINDS)
def test_failing_last_background_child_destruct_rolls_container_back(
    kind: str, layout: str
) -> None:
    env = _Env()
    children = _children(env, layout, fail_destruct=True)
    container = _container(env, kind, children)
    container.construct()
    env.flush()
    assert container.status is ConstructionStatus.CONSTRUCTED

    env.log.clear()
    container.destruct()
    env.flush()

    assert children[-1].status is ConstructionStatus.CONSTRUCTED
    assert container.status is ConstructionStatus.CONSTRUCTED
    assert "P:DESTRUCTED" not in env.log

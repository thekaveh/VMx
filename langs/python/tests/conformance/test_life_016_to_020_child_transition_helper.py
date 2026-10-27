"""Conformance tests: LIFE-016..LIFE-020 — the child-transition helper and members.

A leaf VM that keeps child VMs in fields drives them through the supported
child-transition helper (``_transition_children`` handed to
``_complete_lifecycle_hook_after``) and registers them for depth-first
disposal with ``_own_member`` (spec/02 §6.1 and §7.1, ADR-0162). The leaf
subclasses the public ``vmx.ComponentVM``, as a consumer does.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

from vmx import (
    ComponentVM,
    ConstructionStatus,
    ConstructionStatusChangedMessage,
    GroupVMBuilder,
    MessageHub,
    RxDispatcher,
)


class _Queue:
    """A scheduler that runs nothing until the test drains it."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)


class _Env:
    """Manual foreground and background queues plus a status-message log."""

    def __init__(self, *, manual: bool = True) -> None:
        self.fg = _Queue()
        self.bg = _Queue()
        self.dispatcher = (
            RxDispatcher(self.fg, self.bg)  # type: ignore[arg-type]
            if manual
            else RxDispatcher.immediate()
        )
        self.hub: MessageHub[Any] = MessageHub()
        self.log: list[str] = []
        self.hub.messages.subscribe(self._record)

    def _record(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            self.log.append(f"{message.sender_name}:{message.status.name}")

    def drain(self) -> None:
        while self.fg.actions or self.bg.actions:
            queue = self.fg if self.fg.actions else self.bg
            queue.actions.pop(0)(queue, None)

    def leaf(
        self,
        name: str,
        *,
        background: bool = False,
        on_construct: Callable[[], None] | None = None,
    ) -> ComponentVM:
        return ComponentVM(
            name=name,
            hub=self.hub,
            dispatcher=self.dispatcher,
            on_construct=on_construct,
            background=background,
        )


class _PanelVM(ComponentVM):
    """A consumer leaf VM that keeps its children in fields."""

    def __init__(
        self,
        env: _Env,
        *,
        construct_children: Iterable[ComponentVM] = (),
        destruct_children: Iterable[ComponentVM] = (),
        after: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(name="parent", hub=env.hub, dispatcher=env.dispatcher)
        self.construct_children = list(construct_children)
        self.destruct_children = list(destruct_children)
        self.after = after

    def _on_construct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.construct_children, construct=True, after=self.after)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.destruct_children, construct=False)
        )

    def register(self, member: Any) -> Any:
        return self._own_member(member)


@pytest.mark.conformance("LIFE-016")
def test_LIFE_016_helper_waits_for_a_background_child() -> None:
    env = _Env()
    a = env.leaf("a", background=True)
    b = env.leaf("b")
    seen_by_after: list[tuple[ConstructionStatus, ...]] = []
    parent = _PanelVM(
        env,
        construct_children=[a, b],
        after=lambda: seen_by_after.append((parent.status, a.status, b.status)),
    )

    parent.construct()

    assert parent.status is ConstructionStatus.CONSTRUCTING
    assert a.status is ConstructionStatus.CONSTRUCTING
    assert b.status is ConstructionStatus.DESTRUCTED
    assert seen_by_after == []

    env.drain()

    assert seen_by_after == [
        (
            ConstructionStatus.CONSTRUCTING,
            ConstructionStatus.CONSTRUCTED,
            ConstructionStatus.CONSTRUCTED,
        )
    ]
    assert parent.status is ConstructionStatus.CONSTRUCTED
    terminal = [entry for entry in env.log if entry.endswith(":CONSTRUCTED")]
    assert terminal == ["a:CONSTRUCTED", "b:CONSTRUCTED", "parent:CONSTRUCTED"]


@pytest.mark.conformance("LIFE-017")
def test_LIFE_017_child_failure_rolls_the_parent_back() -> None:
    env = _Env(manual=False)
    c_hook_calls: list[str] = []

    def fail() -> None:
        raise ValueError("b construct failed")

    a = env.leaf("a")
    b = env.leaf("b", on_construct=fail)
    c = env.leaf("c", on_construct=lambda: c_hook_calls.append("c"))
    parent = _PanelVM(env, construct_children=[a, b, c])

    with pytest.raises(ValueError, match="b construct failed"):
        parent.construct()

    assert parent.status is ConstructionStatus.DESTRUCTED
    assert a.status is ConstructionStatus.CONSTRUCTED
    assert b.status is ConstructionStatus.DESTRUCTED
    assert c.status is ConstructionStatus.DESTRUCTED
    assert c_hook_calls == []
    assert "c:CONSTRUCTING" not in env.log


class _FailingDisposeVM(ComponentVM):
    def _on_dispose(self) -> None:
        raise ValueError(f"{self.name} dispose failed")


@pytest.mark.conformance("LIFE-018")
def test_LIFE_018_members_are_disposed_depth_first_before_the_parent() -> None:
    env = _Env(manual=False)
    disposed: list[str] = []
    env.hub.messages.subscribe(
        lambda message: (
            disposed.append(message.sender_name)
            if isinstance(message, ConstructionStatusChangedMessage)
            and message.status is ConstructionStatus.DISPOSED
            else None
        )
    )
    grandchild = env.leaf("member-1-child")
    first = (
        GroupVMBuilder[ComponentVM]()
        .name("member-1")
        .services(env.hub, env.dispatcher)
        .children(lambda: [grandchild])
        .build()
    )
    parent = _PanelVM(env)
    parent.register(first)
    second = parent.register(env.leaf("member-2"))
    first.construct()
    second.construct()
    parent.construct()
    assert grandchild.status is ConstructionStatus.CONSTRUCTED

    parent.dispose()

    assert disposed == ["member-1-child", "member-1", "member-2", "parent"]


@pytest.mark.conformance("LIFE-018")
def test_LIFE_018_member_failure_still_disposes_the_rest_then_surfaces() -> None:
    env = _Env(manual=False)
    parent = _PanelVM(env)
    first = parent.register(
        _FailingDisposeVM(name="member-1", hub=env.hub, dispatcher=env.dispatcher)
    )
    second = parent.register(env.leaf("member-2"))
    parent.construct()

    with pytest.raises(ValueError, match="member-1 dispose failed"):
        parent.dispose()

    assert first.status is ConstructionStatus.DISPOSED
    assert second.status is ConstructionStatus.DISPOSED
    assert parent.status is ConstructionStatus.DISPOSED
    disposed = [entry for entry in env.log if entry.endswith(":DISPOSED")]
    assert disposed == ["member-1:DISPOSED", "member-2:DISPOSED", "parent:DISPOSED"]


@pytest.mark.conformance("LIFE-018")
def test_LIFE_018_member_registered_after_disposed_is_disposed_at_once() -> None:
    env = _Env(manual=False)
    parent = _PanelVM(env)
    parent.dispose()
    late = env.leaf("late")

    assert parent.register(late) is late

    assert late.status is ConstructionStatus.DISPOSED


@pytest.mark.conformance("LIFE-019")
def test_LIFE_019_helper_destructs_in_the_order_the_caller_passes() -> None:
    env = _Env()
    a = env.leaf("a", background=True)
    b = env.leaf("b", background=True)
    c = env.leaf("c", background=True)
    parent = _PanelVM(env, construct_children=[a, b, c], destruct_children=[c, b, a])
    parent.construct()
    env.drain()
    assert parent.status is ConstructionStatus.CONSTRUCTED
    env.log.clear()

    parent.destruct()

    # Only the first child of the caller's list has started.
    assert c.status is ConstructionStatus.DESTRUCTING
    assert b.status is ConstructionStatus.CONSTRUCTED
    assert a.status is ConstructionStatus.CONSTRUCTED

    env.drain()

    assert env.log == [
        "parent:DESTRUCTING",
        "c:DESTRUCTING",
        "c:DESTRUCTED",
        "b:DESTRUCTING",
        "b:DESTRUCTED",
        "a:DESTRUCTING",
        "a:DESTRUCTED",
        "parent:DESTRUCTED",
    ]


@pytest.mark.conformance("LIFE-020")
def test_LIFE_020_helper_joins_a_child_already_in_transit() -> None:
    env = _Env()
    hook_calls: list[str] = []
    a = env.leaf("a", background=True, on_construct=lambda: hook_calls.append("a"))
    parent = _PanelVM(env, construct_children=[a])
    a.construct()
    assert a.status is ConstructionStatus.CONSTRUCTING

    parent.construct()  # no concurrent-operation error

    assert parent.status is ConstructionStatus.CONSTRUCTING
    env.drain()

    assert hook_calls == ["a"]
    assert a.status is ConstructionStatus.CONSTRUCTED
    assert parent.status is ConstructionStatus.CONSTRUCTED
    terminal = [entry for entry in env.log if entry.endswith(":CONSTRUCTED")]
    assert terminal == ["a:CONSTRUCTED", "parent:CONSTRUCTED"]

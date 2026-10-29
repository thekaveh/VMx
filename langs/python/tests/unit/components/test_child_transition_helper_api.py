"""The supported child-transition helper and ``_own_member`` (spec/02 §6.1, §7.1).

A consumer subclasses the public ``vmx.ComponentVM`` and drives the members it
keeps in fields through ``_transition_children`` and
``_complete_lifecycle_hook_after``; it registers them for depth-first
disposal with ``_own_member`` (ADR-0162). These tests cover the usage guard,
background and reconstruct paths, and the registration edge cases.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future
from threading import Event, Thread
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx import (
    AggregateVM1Builder,
    ComponentVM,
    ComponentVMOfBuilder,
    CompositeVMBuilder,
    ConstructionStatus,
    ConstructionStatusChangedMessage,
    ForwardingComponentVM,
    GroupVMBuilder,
    MessageHub,
    RxDispatcher,
)


class _Queue:
    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)


class _Env:
    def __init__(self, *, manual: bool = False) -> None:
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
        on_destruct: Callable[[], None] | None = None,
    ) -> ComponentVM:
        return ComponentVM(
            name=name,
            hub=self.hub,
            dispatcher=self.dispatcher,
            on_construct=on_construct,
            on_destruct=on_destruct,
            background=background,
        )


class _PanelVM(ComponentVM):
    """A consumer leaf VM that keeps its children in fields."""

    def __init__(
        self,
        env: _Env,
        children: Iterable[ComponentVM] = (),
        *,
        background: bool = False,
        after: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            name="parent", hub=env.hub, dispatcher=env.dispatcher, background=background
        )
        self.children = list(children)
        self.after = after

    def _on_construct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.children, construct=True, after=self.after)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(reversed(self.children), construct=False)
        )

    def register(self, member: Any) -> Any:
        return self._own_member(member)


# ── Usage guard ───────────────────────────────────────────────────────────────


def test_helper_outside_a_hook_raises_and_starts_no_child() -> None:
    env = _Env()
    child = env.leaf("child")
    parent = _PanelVM(env, [child])

    with pytest.raises(RuntimeError, match="construct or destruct hook"):
        parent._transition_children([child], construct=True)

    assert child.status is ConstructionStatus.DESTRUCTED
    assert env.log == []


def test_complete_after_outside_the_own_hook_raises() -> None:
    env = _Env()
    parent = _PanelVM(env)
    done: Future[None] = Future()
    done.set_result(None)

    with pytest.raises(RuntimeError, match="own construct or destruct hook"):
        parent._complete_lifecycle_hook_after(done)


def test_complete_after_from_another_vms_hook_raises_and_rolls_back() -> None:
    env = _Env()
    other = _PanelVM(env)
    done: Future[None] = Future()
    done.set_result(None)
    vm = env.leaf("vm", on_construct=lambda: other._complete_lifecycle_hook_after(done))

    with pytest.raises(RuntimeError, match="own construct or destruct hook"):
        vm.construct()

    assert vm.status is ConstructionStatus.DESTRUCTED


# ── Walk behavior ─────────────────────────────────────────────────────────────


def test_background_parent_hook_drives_the_walk() -> None:
    env = _Env(manual=True)
    a = env.leaf("a", background=True)
    b = env.leaf("b")
    parent = _PanelVM(env, [a, b], background=True)

    parent.construct()
    env.drain()

    assert [a.status, b.status, parent.status] == [ConstructionStatus.CONSTRUCTED] * 3
    terminal = [entry for entry in env.log if entry.endswith(":CONSTRUCTED")]
    assert terminal == ["a:CONSTRUCTED", "b:CONSTRUCTED", "parent:CONSTRUCTED"]


def test_raising_after_rolls_the_parent_back() -> None:
    env = _Env()
    child = env.leaf("child")

    def after() -> None:
        raise ValueError("after failed")

    parent = _PanelVM(env, [child], after=after)

    with pytest.raises(ValueError, match="after failed"):
        parent.construct()

    assert parent.status is ConstructionStatus.DESTRUCTED
    assert child.status is ConstructionStatus.CONSTRUCTED


def test_background_child_failure_rolls_the_parent_back() -> None:
    env = _Env(manual=True)

    def fail() -> None:
        raise ValueError("a failed")

    a = env.leaf("a", background=True, on_construct=fail)
    b = env.leaf("b")
    parent = _PanelVM(env, [a, b])

    parent.construct()
    with pytest.raises(ValueError, match="a failed"):
        env.drain()
    env.drain()

    assert parent.status is ConstructionStatus.DESTRUCTED
    assert a.status is ConstructionStatus.DESTRUCTED
    assert b.status is ConstructionStatus.DESTRUCTED


def test_destruct_joins_a_child_already_destructing() -> None:
    env = _Env(manual=True)
    hook_calls: list[str] = []
    a = env.leaf("a", background=True, on_destruct=lambda: hook_calls.append("a"))
    parent = _PanelVM(env, [a])
    parent.construct()
    env.drain()
    a.destruct()
    assert a.status is ConstructionStatus.DESTRUCTING

    parent.destruct()

    assert parent.status is ConstructionStatus.DESTRUCTING
    env.drain()
    assert hook_calls == ["a"]
    assert parent.status is ConstructionStatus.DESTRUCTED


@pytest.mark.parametrize("background", [False, True])
def test_reconstruct_runs_both_phases_through_the_helper(background: bool) -> None:
    env = _Env(manual=True)
    a = env.leaf("a", background=background)
    b = env.leaf("b", background=background)
    parent = _PanelVM(env, [a, b])
    parent.construct()
    env.drain()
    env.log.clear()

    parent.reconstruct()
    env.drain()

    assert env.log == [
        "parent:DESTRUCTING",
        "b:DESTRUCTING",
        "b:DESTRUCTED",
        "a:DESTRUCTING",
        "a:DESTRUCTED",
        "parent:DESTRUCTED",
        "parent:CONSTRUCTING",
        "a:CONSTRUCTING",
        "a:CONSTRUCTED",
        "b:CONSTRUCTING",
        "b:CONSTRUCTED",
        "parent:CONSTRUCTED",
    ]


# ── _own_member ───────────────────────────────────────────────────────────────


def test_own_member_returns_the_member_and_registers_it() -> None:
    env = _Env()
    parent = _PanelVM(env)
    member = env.leaf("member")

    assert parent.register(member) is member
    parent.dispose()

    assert member.status is ConstructionStatus.DISPOSED


def test_own_member_after_disposed_disposes_at_once_and_propagates_failure() -> None:
    env = _Env()
    parent = _PanelVM(env)
    parent.dispose()

    class _Failing(ComponentVM):
        def _on_dispose(self) -> None:
            raise ValueError("late dispose failed")

    late = _Failing(name="late", hub=env.hub, dispatcher=env.dispatcher)
    with pytest.raises(ValueError, match="late dispose failed"):
        parent.register(late)

    assert late.status is ConstructionStatus.DISPOSED


def test_own_member_rejects_the_vm_itself() -> None:
    env = _Env()
    parent = _PanelVM(env)

    with pytest.raises(RuntimeError, match="its own member"):
        parent.register(parent)

    parent.dispose()
    assert parent.status is ConstructionStatus.DISPOSED


def test_reentrant_dispose_during_the_member_cascade_is_a_noop() -> None:
    env = _Env()
    parent = _PanelVM(env)

    class _Reentrant(ComponentVM):
        def _on_dispose(self) -> None:
            parent.dispose()

    parent.register(_Reentrant(name="member-1", hub=env.hub, dispatcher=env.dispatcher))
    parent.register(env.leaf("member-2"))

    parent.dispose()

    disposed = [entry for entry in env.log if entry.endswith(":DISPOSED")]
    assert disposed == ["member-1:DISPOSED", "member-2:DISPOSED", "parent:DISPOSED"]


def test_first_member_failure_wins_and_teardown_finishes() -> None:
    env = _Env()
    released: list[str] = []

    class _Failing(ComponentVM):
        def _on_dispose(self) -> None:
            raise ValueError(f"{self.name} failed")

    parent = _PanelVM(env)
    parent._own(lambda: released.append("resource"))
    parent.register(_Failing(name="m1", hub=env.hub, dispatcher=env.dispatcher))
    parent.register(_Failing(name="m2", hub=env.hub, dispatcher=env.dispatcher))

    with pytest.raises(ValueError, match="m1 failed"):
        parent.dispose()

    assert parent.status is ConstructionStatus.DISPOSED
    assert released == ["resource"]
    disposed = [entry for entry in env.log if entry.endswith(":DISPOSED")]
    assert disposed == ["m1:DISPOSED", "m2:DISPOSED", "parent:DISPOSED"]


def test_members_dispose_before_on_dispose_and_owned_resources() -> None:
    env = _Env()
    order: list[str] = []

    class _Panel(_PanelVM):
        def _on_dispose(self) -> None:
            order.append("on_dispose")

    parent = _Panel(env)
    parent._own(lambda: order.append("resource"))
    member = parent.register(env.leaf("member"))
    env.hub.messages.subscribe(
        lambda message: (
            order.append(f"{message.sender_name}:disposed")
            if isinstance(message, ConstructionStatusChangedMessage)
            and message.status is ConstructionStatus.DISPOSED
            else None
        )
    )

    parent.dispose()

    assert member.status is ConstructionStatus.DISPOSED
    assert order == ["member:disposed", "parent:disposed", "on_dispose", "resource"]


def test_member_cascade_waits_for_an_admitted_foreign_hook() -> None:
    # LIFE-015: a foreign dispose disposes no member while the parent's
    # admitted hook runs; the member is disposed once after the hook returns.
    env = _Env()
    entered = Event()
    release = Event()
    member_disposed_during_hook: list[bool] = []

    class _Blocking(_PanelVM):
        def _on_construct(self) -> None:
            entered.set()
            assert release.wait(HANG_GUARD)
            member_disposed_during_hook.append(member.status is ConstructionStatus.DISPOSED)

    parent = _Blocking(env)
    member = parent.register(env.leaf("member"))
    errors: list[BaseException] = []

    def run(action: Callable[[], None]) -> None:
        try:
            action()
        except BaseException as error:
            errors.append(error)

    constructor = Thread(target=run, args=(parent.construct,), daemon=True)
    constructor.start()
    assert entered.wait(HANG_GUARD)
    disposer = Thread(target=run, args=(parent.dispose,), daemon=True)
    disposer.start()
    disposer.join(0.1)
    assert member.status is not ConstructionStatus.DISPOSED

    release.set()
    constructor.join(HANG_GUARD)
    disposer.join(HANG_GUARD)

    assert not constructor.is_alive() and not disposer.is_alive()
    assert errors == []
    assert member_disposed_during_hook == [False]
    assert member.status is ConstructionStatus.DISPOSED
    assert parent.status is ConstructionStatus.DISPOSED
    assert env.log.count("member:DISPOSED") == 1


def test_dispose_from_another_thread_during_the_member_cascade_returns_at_once() -> None:
    env = _Env()
    parent = _PanelVM(env)
    other_returned = Event()
    parent_status_when_other_returned: list[ConstructionStatus] = []
    other_errors: list[BaseException] = []

    def other_dispose() -> None:
        try:
            parent.dispose()
        except BaseException as error:
            other_errors.append(error)
        parent_status_when_other_returned.append(parent.status)
        other_returned.set()

    class _BlocksUntilOtherReturns(ComponentVM):
        def _on_dispose(self) -> None:
            Thread(target=other_dispose, daemon=True).start()
            # Thread B must return without waiting for this cascade.
            assert other_returned.wait(HANG_GUARD)

    parent.register(_BlocksUntilOtherReturns(name="m1", hub=env.hub, dispatcher=env.dispatcher))
    parent.register(env.leaf("m2"))

    parent.dispose()

    assert other_returned.is_set()
    assert other_errors == []
    # B returned before the first call published Disposed.
    assert parent_status_when_other_returned == [ConstructionStatus.DESTRUCTED]
    assert parent.status is ConstructionStatus.DISPOSED
    disposed = [entry for entry in env.log if entry.endswith(":DISPOSED")]
    assert disposed == ["m1:DISPOSED", "m2:DISPOSED", "parent:DISPOSED"]


def _registering_container(env: _Env, kind: str, child: ComponentVM) -> Any:
    if kind == "group":
        return (
            GroupVMBuilder[ComponentVM]()
            .name("parent")
            .services(env.hub, env.dispatcher)
            .children(lambda: [child])
            .build()
        )
    if kind == "composite":
        return (
            CompositeVMBuilder[ComponentVM]()
            .name("parent")
            .services(env.hub, env.dispatcher)
            .children(lambda: [child])
            .build()
        )
    return (
        AggregateVM1Builder[ComponentVM]()
        .name("parent")
        .services(env.hub, env.dispatcher)
        .component_1(lambda: child)
        .build()
    )


@pytest.mark.parametrize("kind", ["group", "composite", "aggregate"])
def test_member_registered_during_the_child_cascade_is_disposed_at_once(kind: str) -> None:
    env = _Env()
    late = env.leaf("late")
    late_status_after_registration: list[ConstructionStatus] = []
    container: list[Any] = []

    class _RegistersOnDispose(ComponentVM):
        def _on_dispose(self) -> None:
            container[0]._own_member(late)
            late_status_after_registration.append(late.status)

    child = _RegistersOnDispose(name="child", hub=env.hub, dispatcher=env.dispatcher)
    container.append(_registering_container(env, kind, child))
    container[0].construct()

    container[0].dispose()

    assert late_status_after_registration == [ConstructionStatus.DISPOSED]
    disposed = [entry for entry in env.log if entry.endswith(":DISPOSED")]
    assert disposed == ["child:DISPOSED", "late:DISPOSED", "parent:DISPOSED"]


class _MemberDecorator(ForwardingComponentVM[str]):
    def register(self, member: Any) -> Any:
        return self._own_member(member)


def test_forwarding_decorator_registers_on_the_wrapped_component() -> None:
    env = _Env()
    inner = ComponentVMOfBuilder[str]().name("inner").model("m").services(env.hub, env.dispatcher)
    wrapped = inner.build()
    decorator = _MemberDecorator(wrapped)
    member = decorator.register(env.leaf("member"))

    with pytest.raises(RuntimeError, match="its own member"):
        decorator.register(wrapped)

    wrapped.dispose()

    assert member.status is ConstructionStatus.DISPOSED
    disposed = [entry for entry in env.log if entry.endswith(":DISPOSED")]
    assert disposed == ["member:DISPOSED", "inner:DISPOSED"]

"""Conformance test: LIFE-015 — a disposed container begins no new child work.

spec/02 §2.4: a foreign ``dispose()`` publishes ``DISPOSED`` while a hook of
the container runs on another thread, then waits for that hook. The child walk
the hook drives must stop once its owner is ``DISPOSED``: it starts no further
child, runs no ``after`` callback and commits nothing. A child whose transition
started before the dispose may finish it (#1163, matching C#, Swift and Rust).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event, Thread
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx import (
    AggregateVM3Builder,
    ComponentVM,
    CompositeVMBuilder,
    ConstructionStatus,
    ConstructionStatusChangedMessage,
    GroupVMBuilder,
    MessageHub,
    RxDispatcher,
)


class _Blocker:
    """Blocks the first hook that runs while armed, until released."""

    def __init__(self) -> None:
        self.armed = False
        self.entered = Event()
        self.release = Event()
        self.hooks: list[str] = []

    def hook(self, label: str) -> Callable[[], None]:
        def run() -> None:
            self.hooks.append(label)
            if self.armed and not self.entered.is_set():
                self.entered.set()
                assert self.release.wait(HANG_GUARD)

        return run


class _Log:
    def __init__(self, hub: MessageHub[Any]) -> None:
        self.entries: list[tuple[str, ConstructionStatus]] = []
        hub.messages.subscribe(self._record)

    def _record(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            self.entries.append((message.sender_name, message.status))

    def after_disposed(self, name: str) -> list[tuple[str, ConstructionStatus]]:
        index = self.entries.index((name, ConstructionStatus.DISPOSED))
        return self.entries[index + 1 :]


def _leaf(name: str, hub: MessageHub[Any], blocker: _Blocker) -> ComponentVM:
    return ComponentVM(
        name=name,
        hub=hub,
        dispatcher=RxDispatcher.immediate(),
        on_construct=blocker.hook(f"{name}:construct"),
        on_destruct=blocker.hook(f"{name}:destruct"),
    )


def _wait_disposed(vm: Any) -> None:
    deadline = time.monotonic() + HANG_GUARD
    while vm.status is not ConstructionStatus.DISPOSED:
        assert time.monotonic() < deadline, "the foreign dispose did not publish DISPOSED"
        time.sleep(0.001)


def _run_with_foreign_dispose(box: Any, operation: Callable[[], None], blocker: _Blocker) -> None:
    """Run ``operation`` on T, dispose on D while the hook blocks, release."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            operation()
        except BaseException as error:
            errors.append(error)

    caller = Thread(target=run, daemon=True)
    caller.start()
    assert blocker.entered.wait(HANG_GUARD)
    disposer = Thread(target=box.dispose, daemon=True)
    disposer.start()
    _wait_disposed(box)
    blocker.release.set()
    caller.join(HANG_GUARD)
    disposer.join(HANG_GUARD)
    assert not caller.is_alive()
    assert not disposer.is_alive()
    assert errors == []
    assert box.status is ConstructionStatus.DISPOSED


def _container(kind: str, hub: MessageHub[Any], blocker: _Blocker) -> tuple[Any, list[Any]]:
    dispatcher = RxDispatcher.immediate()
    if kind == "aggregate3":
        slots: list[Any] = []

        def factory(name: str) -> Callable[[], ComponentVM]:
            def create() -> ComponentVM:
                child = _leaf(name, hub, blocker)
                slots.append(child)
                return child

            return create

        box: Any = (
            AggregateVM3Builder()
            .name("box")
            .services(hub, dispatcher)
            .component_1(factory("c1"))
            .component_2(factory("c2"))
            .component_3(factory("c3"))
            .build()
        )
        return box, slots
    builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
    box = builder.name("box").services(hub, dispatcher).children(lambda: ()).build()
    children = [_leaf(name, hub, blocker) for name in ("c1", "c2", "c3")]
    for child in children:
        box.add(child)
    return box, children


@pytest.mark.conformance("LIFE-015")
@pytest.mark.parametrize("kind", ("composite", "group", "aggregate3"))
@pytest.mark.parametrize("operation", ("construct", "destruct"))
def test_LIFE_015_walk_starts_no_child_after_foreign_dispose(kind: str, operation: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    blocker = _Blocker()
    box, children = _container(kind, hub, blocker)
    if operation == "destruct":
        box.construct()
    elif kind != "aggregate3":
        # Populate once, so the walk itself constructs the children.
        box.construct()
        box.destruct()
    log = _Log(hub)
    blocker.hooks.clear()
    blocker.armed = True

    _run_with_foreign_dispose(box, getattr(box, operation), blocker)

    # The first walked child finishes the transition it started; no other
    # child starts one after the container's DISPOSED.
    first = blocker.hooks[0].split(":")[0]
    assert blocker.hooks == [f"{first}:{operation}"]
    later = log.after_disposed("box")
    others = [child.name for child in children if child.name != first]
    assert sorted(entry for entry in later if entry[0] in others) == sorted(
        (name, ConstructionStatus.DISPOSED) for name in others
    )
    for child in children:
        assert child.status is ConstructionStatus.DISPOSED
        assert log.entries.count((child.name, ConstructionStatus.DISPOSED)) == 1
    assert ("box", ConstructionStatus.CONSTRUCTED) not in later
    assert ("box", ConstructionStatus.DESTRUCTED) not in later


@pytest.mark.conformance("LIFE-015")
@pytest.mark.parametrize("kind", ("composite", "group"))
def test_LIFE_015_container_hook_disposed_before_its_walk_starts_no_child(kind: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    blocker = _Blocker()
    dispatcher = RxDispatcher.immediate()
    builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
    box: Any = (
        builder.name("box")
        .services(hub, dispatcher)
        .children(lambda: ())
        .on_construct(blocker.hook("box"))
        .build()
    )
    children = [_leaf(name, hub, blocker) for name in ("c1", "c2", "c3")]
    for child in children:
        box.add(child)
    # Populate once, so the construct after the dispose reaches the walk.
    box.construct()
    box.destruct()
    blocker.hooks.clear()
    log = _Log(hub)
    blocker.armed = True

    _run_with_foreign_dispose(box, box.construct, blocker)

    assert blocker.hooks == ["box"]
    assert [status for _, status in log.after_disposed("box")] == [ConstructionStatus.DISPOSED] * 3
    for child in children:
        assert child.status is ConstructionStatus.DISPOSED


@pytest.mark.conformance("LIFE-015")
@pytest.mark.parametrize("operation", ("construct", "destruct"))
def test_LIFE_015_walk_runs_no_selector_or_destruct_callback_after_foreign_dispose(
    operation: str,
) -> None:
    hub: MessageHub[Any] = MessageHub()
    blocker = _Blocker()
    calls: list[str] = []
    child = _leaf("c1", hub, blocker)

    def select(children: Any) -> Any:
        calls.append("selector")
        return next(iter(children))

    box: Any = (
        CompositeVMBuilder()
        .name("box")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: ())
        .current(select)
        .on_destruct(lambda: calls.append("on_destruct"))
        .build()
    )
    box.add(child)
    if operation == "destruct":
        box.construct()
        assert box.current is child
    calls.clear()
    blocker.armed = True

    _run_with_foreign_dispose(box, getattr(box, operation), blocker)

    assert calls == []
    assert box.current is None
    assert child.status is ConstructionStatus.DISPOSED


class _Panel(ComponentVM):
    """A consumer leaf that walks its ``_own_member`` members."""

    def __init__(self, hub: MessageHub[Any], blocker: _Blocker, after: Callable[[], None]) -> None:
        super().__init__(name="panel", hub=hub, dispatcher=RxDispatcher.immediate())
        self.members = [self._own_member(_leaf(f"m{i}", hub, blocker)) for i in (1, 2, 3)]
        self.after = after

    def _on_construct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.members, construct=True, after=self.after)
        )


@pytest.mark.conformance("LIFE-015")
def test_LIFE_015_member_walk_stops_after_foreign_dispose() -> None:
    hub: MessageHub[Any] = MessageHub()
    blocker = _Blocker()
    after_calls: list[str] = []
    panel = _Panel(hub, blocker, lambda: after_calls.append("after"))
    log = _Log(hub)
    blocker.armed = True

    _run_with_foreign_dispose(panel, panel.construct, blocker)

    assert blocker.hooks == ["m1:construct"]
    assert after_calls == []
    assert ("m2", ConstructionStatus.CONSTRUCTING) not in log.entries
    assert ("m3", ConstructionStatus.CONSTRUCTING) not in log.entries
    for member in panel.members:
        assert member.status is ConstructionStatus.DISPOSED
        assert log.entries.count((member.name, ConstructionStatus.DISPOSED)) == 1

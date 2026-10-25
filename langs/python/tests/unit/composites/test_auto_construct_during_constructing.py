"""Auto-construct-on-add while the container is still Constructing.

A container's construct() completes only when every child has reached
Constructed (spec/02 §6). With ``auto_construct_on_add(True)``, a child added
while the container waits on a background child is constructed at add time
and joined by the child walk, so the container never reports Constructed with
an unconstructed added child. Mirrors the C# and TypeScript tests.
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Callable
from typing import Any, Protocol

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.components._late_child_starts import _LateChildStage, _LateChildStarts
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
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

    def snapshot(self) -> tuple[ComponentVM, ...]: ...

    _late_starts: _LateChildStarts


ChildFactory = Callable[..., ComponentVM]


def _setup(
    kind: str, *, auto_construct: bool = True
) -> tuple[_QueueScheduler, ChildFactory, ComponentVM, _Container]:
    bg, child, first, root, _statuses = _setup_recorded(kind, auto_construct=auto_construct)
    return bg, child, first, root


def _setup_recorded(
    kind: str, *, auto_construct: bool = True
) -> tuple[_QueueScheduler, ChildFactory, ComponentVM, _Container, list[str]]:
    """Like ``_setup``, plus each ``name:STATUS`` the hub carries, in order."""
    bg = _QueueScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    statuses: list[str] = []
    statuses_lock = threading.Lock()

    def record(message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            with statuses_lock:
                statuses.append(f"{message.sender_name}:{message.status.name}")

    hub.messages.subscribe(record)

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
    return bg, child, first, root, statuses


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


_BOUND = 5.0


class _Pause:
    """A bounded one-shot pause of the adder thread, driven by the test."""

    def __init__(self) -> None:
        self.paused = threading.Event()
        self.resume = threading.Event()

    def hold(self) -> None:
        self.paused.set()
        self.resume.wait(_BOUND)


def _pause_add_after_attach(root: _Container, late: ComponentVM, pause: _Pause) -> None:
    """Pause the add of *late* after it attached the child, before it starts it."""

    def probe(child: object, stage: _LateChildStage) -> None:
        if child is late and stage is _LateChildStage.ATTACHED:
            assert root.status is S.CONSTRUCTING
            assert late.status is S.DESTRUCTED
            pause.hold()

    root._late_starts.probe_for_testing = probe


def _add_while_walk_pulls(
    bg: _QueueScheduler,
    root: _Container,
    late: ComponentVM,
    pause: _Pause,
    *,
    while_paused: Callable[[], None] = lambda: None,
) -> list[BaseException]:
    """Add *late* from another thread; the walk pulls it while the add pauses.

    The add (or the late child's construct, which runs on the adder thread)
    pauses through *pause*. Meanwhile the original background child settles
    on this thread, and the construct walk resumes inline and pulls *late*.
    Every wait is bounded, so a regression fails instead of hanging.
    """
    errors: list[BaseException] = []

    def add() -> None:
        try:
            root.add(late)
        except BaseException as error:
            errors.append(error)

    adder = threading.Thread(target=add, daemon=True)
    adder.start()
    try:
        assert pause.paused.wait(_BOUND), "the add pauses before the late child settles"
        bg.run_first()  # the original child settles; the walk pulls ``late``
        while_paused()
    finally:
        pause.resume.set()
        adder.join(_BOUND)
    assert not adder.is_alive(), "the paused add resumes and completes"
    bg.run_all()
    return errors


def _record_walk_waiting(root: _Container, late: ComponentVM) -> list[ConstructionStatus]:
    """Record the root's status each time the walk waits for *late*'s add."""
    waiting: list[ConstructionStatus] = []
    previous = root._late_starts.probe_for_testing

    def probe(child: object, stage: _LateChildStage) -> None:
        if previous is not None:
            previous(child, stage)
        if child is late and stage is _LateChildStage.WALK_WAITING_ON_ADD:
            waiting.append(root.status)

    root._late_starts.probe_for_testing = probe
    return waiting


def _assert_constructed_after_late(
    root: _Container, late: ComponentVM, statuses: list[str]
) -> None:
    assert root.status is S.CONSTRUCTED
    assert late.status is S.CONSTRUCTED
    assert statuses.count("late:CONSTRUCTING") == 1
    assert statuses.index("root:CONSTRUCTED") > statuses.index("late:CONSTRUCTED")


@KINDS
def test_walk_waits_for_the_adds_start_attempt_then_joins(kind: str) -> None:
    bg, child, _first, root, statuses = _setup_recorded(kind)
    root.construct()
    runs: list[None] = []
    late = child("late", on_construct=lambda: runs.append(None))
    pause = _Pause()
    _pause_add_after_attach(root, late, pause)
    waiting = _record_walk_waiting(root, late)
    held: list[ConstructionStatus] = []

    errors = _add_while_walk_pulls(
        bg, root, late, pause, while_paused=lambda: held.append(root.status)
    )

    assert errors == []
    _assert_constructed_after_late(root, late, statuses)
    assert waiting == [S.CONSTRUCTING], "the walk waited for the add's start attempt"
    assert held == [S.CONSTRUCTING], "the walk holds the root until the add started the child"
    assert len(runs) == 1, "only the add starts the child"


@KINDS
def test_walk_joins_a_late_child_its_add_is_starting(kind: str) -> None:
    bg, child, _first, root, statuses = _setup_recorded(kind)
    root.construct()
    runs: list[None] = []
    pause = _Pause()

    def construct_late() -> None:
        runs.append(None)
        pause.hold()  # the add started the child; its construct holds here

    late = child("late", on_construct=construct_late)
    held: list[ConstructionStatus] = []

    errors = _add_while_walk_pulls(
        bg, root, late, pause, while_paused=lambda: held.append(root.status)
    )

    assert errors == []
    _assert_constructed_after_late(root, late, statuses)
    assert held == [S.CONSTRUCTING], "the walk holds the root while the add's construct runs"
    assert len(runs) == 1, "only the add starts the child"


@KINDS
def test_failed_add_started_late_child_undoes_the_add_and_rolls_back(kind: str) -> None:
    bg, child, _first, root = _setup(kind)
    root.construct()
    runs: list[None] = []

    def fail() -> None:
        runs.append(None)
        raise RuntimeError("late failed")

    late = child("late", on_construct=fail)
    pause = _Pause()
    _pause_add_after_attach(root, late, pause)
    waiting = _record_walk_waiting(root, late)

    errors = _add_while_walk_pulls(bg, root, late, pause)

    assert [str(error) for error in errors] == ["late failed"], "the add's own construct failed"
    assert all(member is not late for member in root.snapshot()), "the failed add is undone"
    assert root.status is S.DESTRUCTED, "the walk waited on the failing child"
    assert late.status is S.DESTRUCTED
    assert waiting == [S.CONSTRUCTING]
    assert len(runs) == 1


@KINDS
def test_failed_walk_never_clears_the_next_walks_records(kind: str) -> None:
    bg = _QueueScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    fail_once = [True]

    def flaky() -> None:
        if fail_once:
            fail_once.clear()
            raise RuntimeError("walk 1 fails")

    def child(name: str, on_construct: Callable[[], None] | None = None) -> ComponentVM:
        builder = ComponentVMBuilder().name(name).services(hub, dispatcher).background(True)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        return builder.build()

    first = child("first")
    second = child("second", flaky)
    builder = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    root: _Container = (
        builder.name("root")
        .services(hub, dispatcher)
        .children(lambda: [first, second])
        .auto_construct_on_add(True)
        .build()
    )

    # Walk 1 fails on ``second``; the root rolls back.
    root.construct()
    while bg.actions:
        try:
            bg.run_first()
        except RuntimeError:
            pass
    assert root.status is S.DESTRUCTED

    # Walk 2 runs; a late child registers its start record in walk 2's scope.
    root.construct()
    assert root.status is S.CONSTRUCTING
    late = child("late")
    root.add(late)
    assert late.status is S.CONSTRUCTING
    late_work = bg.actions.pop()  # hold the late child Constructing

    # Collect now: a failed walk's leftovers must not touch walk 2's records.
    gc.collect()

    bg.run_all()  # every child but ``late`` settles; walk 2 reaches ``late``
    assert root.status is S.CONSTRUCTING, "walk 2 waits for the late child"
    late_work(bg, None)
    bg.run_all()
    assert late.status is S.CONSTRUCTED
    assert root.status is S.CONSTRUCTED

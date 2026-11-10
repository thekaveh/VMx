"""Conformance test: LIFE-021 — a lifecycle call during the inline dispose cascade.

spec/02 §7.2 and ADR-0175. The *inline cascade* of a view-model is the part
of its first ``dispose()`` call that disposes its children (§7) and its
registered members (§7.1) while no construct or destruct hook of the VM is
admitted on another thread. It starts when ``dispose()`` closes hook admission
and ends when the VM publishes ``DISPOSED``.

- A ``construct()``, ``destruct()`` or ``reconstruct()`` call that starts
  during the cascade raises ``StatusTransitionError(DISPOSED, op)``. It
  publishes nothing, admits no hook and calls no slot factory (Rule 1). The
  refusal runs before the idempotent no-op (Rule 2).
- Once the cascade has started, the VM commits no status other than
  ``DISPOSED``: a transition that started earlier drops its commit and returns
  as a call that ``DISPOSED`` superseded (Rules 3 and 4, #1167).
- A leaf's member cascade follows the same rules (Rule 5).
"""

from __future__ import annotations

import types
from collections.abc import Callable
from threading import Event, Thread
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from tests.liveness import join_thread, wait_event
from vmx import (
    AggregateVM1Builder,
    ComponentVM,
    CompositeVMBuilder,
    ConstructionStatus,
    ConstructionStatusChangedMessage,
    GroupVMBuilder,
    MessageHub,
    RxDispatcher,
)
from vmx.lifecycle.exceptions import StatusTransitionError

_CONTAINERS = ("composite", "group", "aggregate1")

# (operation, the start state of the VM under test)
_REFUSED_CALLS = (
    ("construct", ConstructionStatus.DESTRUCTED),
    ("destruct", ConstructionStatus.CONSTRUCTED),
    ("construct", ConstructionStatus.CONSTRUCTED),
    ("reconstruct", ConstructionStatus.CONSTRUCTED),
)


class _Queue:
    """A manual scheduler: actions run only when the test drains it."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def drain(self) -> None:
        while self.actions:
            self.actions.pop(0)(self, None)


class _Child(ComponentVM):
    """A leaf whose dispose hook runs a test callback."""

    def __init__(self, name: str, hub: MessageHub[Any], dispatcher: RxDispatcher) -> None:
        super().__init__(name=name, hub=hub, dispatcher=dispatcher)
        self.on_dispose: Callable[[], None] | None = None

    def _on_dispose(self) -> None:
        if self.on_dispose is not None:
            self.on_dispose()


class _Leaf(ComponentVM):
    """A leaf VM that registers members with the member-disposal helper."""

    def register(self, member: Any) -> Any:
        return self._own_member(member)


class _Recorder:
    """Records each status message with the senders' statuses at that time."""

    def __init__(self, hub: MessageHub[Any]) -> None:
        self.messages: list[tuple[object, ConstructionStatus]] = []
        hub.messages.subscribe(self._record)

    def _record(self, message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            self.messages.append((message.sender, message.status))

    def of(self, vm: object) -> list[ConstructionStatus]:
        return [status for sender, status in self.messages if sender is vm]


def _count_hooks(vm: Any, calls: list[str]) -> None:
    """Record every construct or destruct hook that the VM admits."""
    for hook in ("_on_construct", "_on_destruct"):
        original = getattr(vm, hook)

        def counted(original: Callable[[], None] = original, hook: str = hook) -> None:
            calls.append(hook)
            original()

        setattr(vm, hook, counted)


class _Box:
    """The container under test, its current child ``c1`` and its factory calls."""

    def __init__(self, kind: str, hub: MessageHub[Any], dispatcher: RxDispatcher) -> None:
        self.factory_calls = 0
        self.vm: Any
        if kind == "aggregate1":

            def factory() -> _Child:
                self.factory_calls += 1
                return _Child(f"c{self.factory_calls}", hub, dispatcher)

            self.vm = (
                AggregateVM1Builder()
                .name("box")
                .services(hub, dispatcher)
                .component_1(factory)
                .build()
            )
            # Construct once first, so that c1 exists.
            self.vm.construct()
            self.vm.destruct()
            return
        builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
        self.vm = builder.name("box").services(hub, dispatcher).children(lambda: ()).build()
        self.vm.add(_Child("c1", hub, dispatcher))

    @property
    def c1(self) -> _Child:
        children = self.vm.components() if hasattr(self.vm, "components") else self.vm.snapshot()
        child = children[0]
        assert isinstance(child, _Child)
        return child


def _call(vm: Any, operation: str) -> None:
    getattr(vm, operation)()


def _put_in(vm: Any, status: ConstructionStatus) -> None:
    if status is ConstructionStatus.CONSTRUCTED:
        vm.construct()
    assert vm.status is status


# ── Part 1: the container case ───────────────────────────────────────────────


@pytest.mark.conformance("LIFE-021")
@pytest.mark.parametrize("kind", _CONTAINERS)
@pytest.mark.parametrize(("operation", "start"), _REFUSED_CALLS)
def test_LIFE_021_call_from_child_dispose_hook_fails_and_publishes_nothing(
    kind: str, operation: str, start: ConstructionStatus
) -> None:
    hub: MessageHub[Any] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    holder = _Box(kind, hub, dispatcher)
    box = holder.vm
    _put_in(box, start)
    c1 = holder.c1
    factory_before = holder.factory_calls
    hook_calls: list[str] = []
    _count_hooks(box, hook_calls)
    recorder = _Recorder(hub)
    errors: list[BaseException] = []

    def call_box() -> None:
        try:
            _call(box, operation)
        except BaseException as error:
            errors.append(error)

    c1.on_dispose = call_box

    box.dispose()

    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, StatusTransitionError)
    assert error.current_status is ConstructionStatus.DISPOSED
    assert error.attempted_operation == operation
    assert hook_calls == []
    assert holder.factory_calls == factory_before
    assert recorder.of(box) == [ConstructionStatus.DISPOSED]
    assert box.status is ConstructionStatus.DISPOSED
    assert c1.status is ConstructionStatus.DISPOSED
    assert recorder.of(c1) == [ConstructionStatus.DISPOSED]
    if kind == "aggregate1":
        assert box.component_1 is c1


@pytest.mark.conformance("LIFE-021")
@pytest.mark.parametrize("kind", _CONTAINERS)
def test_LIFE_021_call_from_subscriber_during_cascade_fails(kind: str) -> None:
    """Rule 1 covers every source of the call, here a hub subscriber."""
    hub: MessageHub[Any] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    holder = _Box(kind, hub, dispatcher)
    box, c1 = holder.vm, holder.c1
    recorder = _Recorder(hub)
    errors: list[BaseException] = []

    def on_message(message: object) -> None:
        if (
            isinstance(message, ConstructionStatusChangedMessage)
            and message.sender is c1
            and message.status is ConstructionStatus.DISPOSED
        ):
            try:
                box.construct()
            except BaseException as error:
                errors.append(error)

    hub.messages.subscribe(on_message)

    box.dispose()

    assert [type(error) for error in errors] == [StatusTransitionError]
    assert isinstance(errors[0], StatusTransitionError)
    assert errors[0].current_status is ConstructionStatus.DISPOSED
    assert recorder.of(box) == [ConstructionStatus.DISPOSED]


# ── Part 2: the leaf cases ───────────────────────────────────────────────────


@pytest.mark.conformance("LIFE-021")
@pytest.mark.parametrize(("operation", "start"), _REFUSED_CALLS)
def test_LIFE_021_call_from_member_dispose_hook_fails(
    operation: str, start: ConstructionStatus
) -> None:
    hub: MessageHub[Any] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    leaf = _Leaf(name="leaf", hub=hub, dispatcher=dispatcher)
    member = leaf.register(_Child("m1", hub, dispatcher))
    _put_in(leaf, start)
    hook_calls: list[str] = []
    _count_hooks(leaf, hook_calls)
    recorder = _Recorder(hub)
    errors: list[BaseException] = []

    def call_leaf() -> None:
        try:
            _call(leaf, operation)
        except BaseException as error:
            errors.append(error)

    member.on_dispose = call_leaf

    leaf.dispose()

    assert len(errors) == 1
    assert isinstance(errors[0], StatusTransitionError)
    assert errors[0].current_status is ConstructionStatus.DISPOSED
    assert errors[0].attempted_operation == operation
    assert hook_calls == []
    assert recorder.of(leaf) == [ConstructionStatus.DISPOSED]
    assert member.status is ConstructionStatus.DISPOSED
    assert leaf.status is ConstructionStatus.DISPOSED


@pytest.mark.conformance("LIFE-021")
def test_LIFE_021_queued_background_commit_drained_in_member_cascade_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    foreground = _Queue()
    dispatcher = RxDispatcher(foreground, ImmediateScheduler())  # type: ignore[arg-type]
    hook_calls: list[str] = []
    leaf = _Leaf(
        name="leaf",
        hub=hub,
        dispatcher=dispatcher,
        background=True,
        on_construct=lambda: hook_calls.append("construct"),
    )
    member = leaf.register(_Child("m1", hub, RxDispatcher.immediate()))
    recorder = _Recorder(hub)

    leaf.construct()
    # The construct hook ran on the background; the Constructed commit waits
    # on the manual foreground.
    assert hook_calls == ["construct"]
    assert len(foreground.actions) == 1
    member.on_dispose = foreground.drain

    leaf.dispose()

    assert foreground.actions == []
    assert recorder.of(leaf) == [ConstructionStatus.CONSTRUCTING, ConstructionStatus.DISPOSED]
    assert leaf.status is ConstructionStatus.DISPOSED
    assert member.status is ConstructionStatus.DISPOSED
    assert recorder.of(member) == [ConstructionStatus.DISPOSED]


@pytest.mark.conformance("LIFE-021")
def test_LIFE_021_reconstruct_disposed_after_its_destruct_phase_starts_no_construct_phase() -> None:
    """Decision (b): a Destructed subscriber disposes the VM, so the construct
    phase does not start: no Constructing, no hook, and no error."""
    hub: MessageHub[Any] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    holder = _Box("composite", hub, dispatcher)
    box, c1 = holder.vm, holder.c1
    box.construct()
    hook_calls: list[str] = []
    _count_hooks(box, hook_calls)
    recorder = _Recorder(hub)

    def on_message(message: object) -> None:
        if (
            isinstance(message, ConstructionStatusChangedMessage)
            and message.sender is box
            and message.status is ConstructionStatus.DESTRUCTED
        ):
            box.dispose()

    hub.messages.subscribe(on_message)

    box.reconstruct()

    assert hook_calls == ["_on_destruct"]
    assert recorder.of(box) == [
        ConstructionStatus.DESTRUCTING,
        ConstructionStatus.DESTRUCTED,
        ConstructionStatus.DISPOSED,
    ]
    assert c1.status is ConstructionStatus.DISPOSED


# ── #1167: a transition that started before the cascade commits nothing ──────


def _pause_after_hook(vm: Any, expected: ConstructionStatus, paused: Event, resume: Event) -> None:
    """Pause the calling thread after ``vm``'s hook released its lease.

    The pause sits between the hook's return and the commit, which is the
    window in which a concurrent dispose() runs the inline cascade.
    """
    original = vm._invoke_lifecycle_hook

    def paused_hook(self: object, hook: Callable[[], None], status: ConstructionStatus) -> bool:
        admitted: bool = original(hook, status)
        if status is expected:
            paused.set()
            assert wait_event(resume)
        return admitted

    vm._invoke_lifecycle_hook = types.MethodType(paused_hook, vm)


def _held_box(kind: str, hub: MessageHub[Any], c1: _Child) -> Any:
    dispatcher = RxDispatcher.immediate()
    if kind == "leaf":
        leaf = _Leaf(name="box", hub=hub, dispatcher=dispatcher)
        leaf.register(c1)
        return leaf
    if kind == "aggregate1":
        return (
            AggregateVM1Builder()
            .name("box")
            .services(hub, dispatcher)
            .component_1(lambda: c1)
            .build()
        )
    builder: Any = CompositeVMBuilder() if kind == "composite" else GroupVMBuilder()
    box = builder.name("box").services(hub, dispatcher).children(lambda: ()).build()
    box.add(c1)
    return box


@pytest.mark.conformance("LIFE-021")
@pytest.mark.parametrize("kind", ("composite", "group", "aggregate1", "leaf"))
@pytest.mark.parametrize("operation", ("construct", "destruct", "reconstruct"))
def test_LIFE_021_transition_whose_hook_returned_before_the_cascade_commits_nothing(
    kind: str, operation: str
) -> None:
    hub: MessageHub[Any] = MessageHub()
    c1 = _Child("c1", hub, RxDispatcher.immediate())
    box = _held_box(kind, hub, c1)
    if operation != "construct":
        box.construct()
    expected = (
        ConstructionStatus.CONSTRUCTING
        if operation == "construct"
        else ConstructionStatus.DESTRUCTING
    )
    paused = Event()
    resume = Event()
    call_done = Event()
    errors: list[BaseException] = []
    seen: list[tuple[ConstructionStatus, ConstructionStatus]] = []

    def on_message(message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage) and message.sender is box:
            seen.append((message.status, c1.status))

    hub.messages.subscribe(on_message)
    _pause_after_hook(box, expected, paused, resume)

    def hold_child_dispose() -> None:
        # T resumes once the cascade disposes c1; c1's dispose hook holds
        # until T's call returned, so a commit T makes lands mid-cascade.
        resume.set()
        assert wait_event(call_done)

    c1.on_dispose = hold_child_dispose

    def run_call() -> None:
        try:
            _call(box, operation)
        except BaseException as error:
            errors.append(error)
        finally:
            call_done.set()

    caller = Thread(target=run_call, daemon=True)
    caller.start()
    assert wait_event(paused)
    disposer = Thread(target=box.dispose, daemon=True)
    disposer.start()
    join_thread(caller)
    join_thread(disposer)
    assert not caller.is_alive()
    assert not disposer.is_alive()

    assert errors == []
    # The box publishes its transient status and then only DISPOSED: no
    # settled status, and nothing while c1 is already DISPOSED but box is not.
    assert [status for status, _ in seen] == [expected, ConstructionStatus.DISPOSED]
    assert seen[0][1] is not ConstructionStatus.DISPOSED
    assert box.status is ConstructionStatus.DISPOSED
    assert c1.status is ConstructionStatus.DISPOSED
    assert box._in_flight is False


@pytest.mark.conformance("LIFE-021")
def test_LIFE_021_queued_background_commit_run_on_another_thread_publishes_nothing() -> None:
    """#1167: thread F runs the queued Constructed commit while thread D
    disposes the background leaf's member."""
    hub: MessageHub[Any] = MessageHub()
    foreground = _Queue()
    dispatcher = RxDispatcher(foreground, ImmediateScheduler())  # type: ignore[arg-type]
    leaf = _Leaf(name="leaf", hub=hub, dispatcher=dispatcher, background=True)
    member = leaf.register(_Child("m1", hub, RxDispatcher.immediate()))
    seen: list[tuple[ConstructionStatus, ConstructionStatus]] = []

    def on_message(message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage) and message.sender is leaf:
            seen.append((message.status, member.status))

    hub.messages.subscribe(on_message)
    leaf.construct()
    assert len(foreground.actions) == 1
    member_disposing = Event()
    drained = Event()

    def hold_member_dispose() -> None:
        member_disposing.set()
        assert wait_event(drained)

    member.on_dispose = hold_member_dispose

    def run_foreground() -> None:
        try:
            assert wait_event(member_disposing)
            foreground.drain()
        finally:
            drained.set()

    runner = Thread(target=run_foreground, daemon=True)
    runner.start()
    disposer = Thread(target=leaf.dispose, daemon=True)
    disposer.start()
    join_thread(runner)
    join_thread(disposer)
    assert not runner.is_alive()
    assert not disposer.is_alive()

    assert seen == [
        (ConstructionStatus.CONSTRUCTING, ConstructionStatus.DESTRUCTED),
        (ConstructionStatus.DISPOSED, ConstructionStatus.DISPOSED),
    ]
    assert leaf.status is ConstructionStatus.DISPOSED

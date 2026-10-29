"""An add after the construct walk's last scan, before the Constructed commit.

An add that reads ``CONSTRUCTING`` after the walk's last late scan, but before
the container commits ``CONSTRUCTED``, starts its child. The container must then
reach ``CONSTRUCTED`` only after that child (spec/02 §6, spec/06 §5.1, #744).
Both the foreground and the background queue their work, so each test decides
when the commit runs. Every wait is bounded.
"""

from __future__ import annotations

import gc
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx.components._late_child_starts import _LateChildStage
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _Queue:
    """Queues scheduled work until the test runs it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        with self._lock:
            self._actions.append(action)

    def run_one(self) -> bool:
        with self._lock:
            if not self._actions:
                return False
            action = self._actions.pop(0)
        action(self, None)
        return True

    def run_all(self) -> None:
        while self.run_one():
            pass


@dataclass
class _Harness:
    fg: _Queue
    bg: _Queue
    hub: MessageHub[object]
    dispatcher: RxDispatcher
    root: Any
    statuses: list[str] = field(default_factory=list)
    late: ComponentVM | None = None
    late_when_root_constructed: ConstructionStatus | None = None
    late_runs: int = 0
    selector_runs: int = 0


def _create(kind: str, select: Callable[[_Harness], None] | None = None) -> _Harness:
    fg, bg = _Queue(), _Queue()
    dispatcher = RxDispatcher(fg, bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    anchor = ComponentVMBuilder().name("anchor").services(hub, dispatcher).background(True).build()
    holder: list[_Harness] = []

    def selector(_children: Any) -> None:
        harness = holder[0]
        harness.selector_runs += 1
        if select is not None:
            select(harness)
        return None

    builder: Any = (
        CompositeVMBuilder[ComponentVM]() if kind == "composite" else GroupVMBuilder[ComponentVM]()
    )
    builder = (
        builder.name("root")
        .services(hub, dispatcher)
        .children(lambda: [anchor])
        .auto_construct_on_add(True)
    )
    if select is not None:
        builder = builder.current(selector)
    root = builder.build()
    harness = _Harness(fg=fg, bg=bg, hub=hub, dispatcher=dispatcher, root=root)
    holder.append(harness)

    def record(message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            harness.statuses.append(f"{message.sender_name}:{message.status.name}")
            if message.sender_name == "root" and message.status is S.CONSTRUCTED:
                late = harness.late
                harness.late_when_root_constructed = late.status if late is not None else None

    hub.messages.subscribe(record)
    return harness


def _add_late(harness: _Harness, *, other_thread: bool) -> ConstructionStatus:
    """Add a background late child on this thread or another one."""

    def count() -> None:
        harness.late_runs += 1

    late = (
        ComponentVMBuilder()
        .name("late")
        .services(harness.hub, harness.dispatcher)
        .background(True)
        .on_construct(count)
        .build()
    )
    harness.late = late
    seen: list[ConstructionStatus] = []
    errors: list[BaseException] = []

    def add() -> None:
        seen.append(harness.root.status)
        try:
            harness.root.add(late)
        except BaseException as error:
            errors.append(error)

    if other_thread:
        adder = threading.Thread(target=add, daemon=True)
        adder.start()
        adder.join(HANG_GUARD)
        assert not adder.is_alive(), "the add completes"
    else:
        add()
    assert errors == []
    return seen[0]


def _run_walk_to_its_tail(harness: _Harness) -> None:
    """Settle the anchor, then run foreground work one item at a time.

    Stops once the item that ran the walk's tail returns: its last scan, the
    selector (if any) and the commit step ran. A walk that ended has queued
    the container's Constructed commit on the foreground, not yet run.
    """
    ended: list[None] = []
    previous = harness.root._late_starts.probe_for_testing

    def probe(child: object, stage: _LateChildStage) -> None:
        if previous is not None:
            previous(child, stage)
        if stage is _LateChildStage.WALK_ENDED:
            ended.append(None)

    harness.root._late_starts.probe_for_testing = probe
    harness.root.construct()
    assert harness.root.status is S.CONSTRUCTING
    harness.bg.run_all()  # the anchor's hook; its Constructed goes to the foreground
    for _ in range(1000):
        if ended or harness.selector_runs:
            break
        assert harness.fg.run_one(), "the construct walk reaches its tail"
    assert ended or harness.selector_runs
    harness.root._late_starts.probe_for_testing = previous


def _settle(harness: _Harness) -> None:
    for _ in range(1000):
        harness.fg.run_all()
        harness.bg.run_all()
        late = harness.late
        if (
            harness.root.status is not S.CONSTRUCTING
            and not harness.root._in_flight
            and (late is None or late.status is not S.CONSTRUCTING)
        ):
            return
    raise AssertionError("the root and the late child settle")


@pytest.mark.parametrize("kind", ["composite", "group"])
@pytest.mark.parametrize("other_thread", [True, False])
def test_add_before_the_queued_commit_is_joined_or_follows_add_after_constructed(
    kind: str, other_thread: bool
) -> None:
    harness = _create(kind)
    _run_walk_to_its_tail(harness)

    seen = _add_late(harness, other_thread=other_thread)
    late = harness.late
    assert late is not None
    assert late.status is not S.DESTRUCTED, "auto-construct started the child"
    harness.fg.run_all()  # the queued commit runs; the late child is still Constructing
    _settle(harness)

    assert harness.root.status is S.CONSTRUCTED
    assert late.status is S.CONSTRUCTED
    assert harness.late_runs == 1
    if seen is S.CONSTRUCTING:
        assert harness.late_when_root_constructed is S.CONSTRUCTED, (
            "an add that read CONSTRUCTING makes the root wait for its child"
        )
    else:
        assert seen is S.CONSTRUCTED, "the add followed add-after-Constructed"


@pytest.mark.parametrize("other_thread", [True, False])
def test_composite_waits_for_a_child_its_selector_adds(other_thread: bool) -> None:
    seen: list[ConstructionStatus] = []

    def select(harness: _Harness) -> None:
        if not seen:
            seen.append(_add_late(harness, other_thread=other_thread))

    harness = _create("composite", select)
    _run_walk_to_its_tail(harness)
    assert seen == [S.CONSTRUCTING], "the selector runs while the root is Constructing"

    harness.fg.run_all()
    assert harness.root.status is S.CONSTRUCTING, "the root waits for the late child"
    _settle(harness)

    assert harness.root.status is S.CONSTRUCTED
    assert harness.late_when_root_constructed is S.CONSTRUCTED
    assert harness.statuses.index("root:CONSTRUCTED") > harness.statuses.index("late:CONSTRUCTED")
    assert harness.late_runs == 1
    assert harness.selector_runs == 1, "the selector runs once"


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_add_after_the_published_constructed_constructs_before_the_change(kind: str) -> None:
    harness = _create(kind)
    _run_walk_to_its_tail(harness)
    _settle(harness)
    assert harness.root.status is S.CONSTRUCTED

    late = ComponentVMBuilder().name("late").services(harness.hub, harness.dispatcher).build()
    at_change: list[ConstructionStatus] = []
    harness.root.on_collection_changed.subscribe(lambda _event: at_change.append(late.status))
    harness.root.add(late)

    assert at_change[:1] == [S.CONSTRUCTED]


def _in_commit_window(harness: _Harness, in_window: Callable[[], None]) -> None:
    """Run *in_window* after the commit step committed CONSTRUCTED, before it is published."""
    ran: list[None] = []

    def probe(_child: object, stage: _LateChildStage) -> None:
        if stage is not _LateChildStage.WALK_ENDED or ran:
            return
        ran.append(None)
        assert "root:CONSTRUCTED" not in harness.statuses, "the commit is not yet published"
        in_window()

    harness.root._late_starts.probe_for_testing = probe
    harness.root.construct()
    harness.bg.run_all()
    for _ in range(1000):
        if ran:
            break
        assert harness.fg.run_one(), "the walk reaches its commit step"
    assert ran
    _settle(harness)


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_construct_while_the_commit_is_unpublished_raises_like_an_in_flight_construct(
    kind: str,
) -> None:
    harness = _create(kind)
    errors: list[BaseException] = []

    def construct() -> None:
        try:
            harness.root.construct()
        except BaseException as error:
            errors.append(error)

    _in_commit_window(harness, construct)

    assert [type(error).__name__ for error in errors] == ["StatusTransitionError"]
    assert harness.root.status is S.CONSTRUCTED
    assert harness.statuses.count("root:CONSTRUCTED") == 1
    harness.root.construct()  # a published CONSTRUCTED stays idempotent
    assert harness.statuses.count("root:CONSTRUCTED") == 1


@pytest.mark.parametrize("kind", ["composite", "group"])
def test_lifecycle_predicates_are_false_while_the_commit_is_unpublished(kind: str) -> None:
    harness = _create(kind)
    seen: list[bool] = []
    errors: list[str] = []

    def probe_predicates() -> None:
        root = harness.root
        seen.extend([root.can_construct(), root.can_destruct(), root.can_reconstruct()])
        for operation in (root.destruct, root.reconstruct):
            try:
                operation()
            except BaseException as error:
                errors.append(type(error).__name__)

    _in_commit_window(harness, probe_predicates)

    assert seen == [False, False, False], "each predicate agrees with its operation"
    assert errors == ["StatusTransitionError", "StatusTransitionError"]
    assert harness.root.status is S.CONSTRUCTED
    assert harness.root.can_destruct() and harness.root.can_reconstruct()


@pytest.mark.parametrize("kind", ["component", "composite", "group"])
def test_a_constructed_subscriber_sees_a_completed_construct(kind: str) -> None:
    hub: MessageHub[object] = MessageHub()
    fg, bg = _Queue(), _Queue()
    dispatcher = RxDispatcher(fg, bg)  # type: ignore[arg-type]

    def member() -> ComponentVM:
        return ComponentVMBuilder().name("member").services(hub, dispatcher).build()

    vm: Any
    if kind == "component":
        vm = ComponentVMBuilder().name("vm").services(hub, dispatcher).build()
    else:
        builder: Any = (
            CompositeVMBuilder[ComponentVM]()
            if kind == "composite"
            else GroupVMBuilder[ComponentVM]()
        )
        vm = (
            builder.name("vm")
            .services(hub, dispatcher)
            .children(lambda: [member()])
            .auto_construct_on_add(True)
            .build()
        )
    done: list[bool] = []

    def record(message: object) -> None:
        if (
            isinstance(message, ConstructionStatusChangedMessage)
            and message.sender is vm
            and message.status is S.CONSTRUCTED
            and not done
        ):
            done.append(vm._construct_future().done())

    hub.messages.subscribe(record)
    vm.construct()
    fg.run_all()
    bg.run_all()
    fg.run_all()

    assert done == [True], "a CONSTRUCTED subscriber sees a completed transition"


def test_walk_holds_each_visited_child_until_it_ends() -> None:
    """A visited child stays referenced, so its id cannot be reused mid-walk."""
    holder: list[ComponentVM] = []
    alive: list[bool] = []

    def drop_a_visited_child(harness: _Harness) -> None:
        visited_child = holder.pop()
        harness.root.remove(visited_child)
        child_ref = weakref.ref(visited_child)
        del visited_child
        gc.collect()
        alive.append(child_ref() is not None)

    harness = _create("composite", drop_a_visited_child)
    extra = ComponentVMBuilder().name("extra").services(harness.hub, harness.dispatcher).build()
    holder.append(extra)
    harness.root.add(extra)  # a snapshot member the walk visits
    del extra
    _run_walk_to_its_tail(harness)
    _settle(harness)

    assert alive == [True], "the walk keeps a visited child alive while it runs"

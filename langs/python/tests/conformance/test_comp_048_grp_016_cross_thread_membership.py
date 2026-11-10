"""Conformance tests: COMP-048 and GRP-016 — a membership change fails at once.

While another thread holds a container's membership transaction, an add, an
insert, an index replacement, a population, a transfer out, a remove, a
remove_at and a clear each raise the "membership transaction in progress"
error at once. They change nothing, and they succeed once the transaction
ends. Only disposal waits for the transaction (ADR-0187, spec/06 §4.2,
spec/07 §1.1).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from tests.liveness import HANG_GUARD, join_thread, wait_event
from vmx.collections.collection_changed import CollectionChangedEvent
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
IN_PROGRESS = "membership transaction is already in progress"


class _Hold:
    """Holds an add inside its membership transaction on another thread."""

    def __init__(self) -> None:
        self.opened = threading.Event()
        self.release = threading.Event()
        self.armed = True
        self.errors: list[BaseException] = []
        self.thread: threading.Thread | None = None

    def hold(self) -> None:
        if not self.armed:
            return
        self.armed = False
        self.opened.set()
        # Outlives the main thread's positive waits, so a regression fails there.
        wait_event(self.release, 3 * HANG_GUARD)

    def start(self, add: Callable[[], None]) -> None:
        def run() -> None:
            try:
                add()
            except BaseException as error:
                self.errors.append(error)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert wait_event(self.opened, HANG_GUARD), "the add holds its transaction"

    def finish(self) -> None:
        self.release.set()
        assert self.thread is not None
        join_thread(self.thread, HANG_GUARD)
        assert not self.thread.is_alive(), "the held add completes"
        assert self.errors == []


class _Scene:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.hub: MessageHub[object] = MessageHub()
        self.dispatcher = RxDispatcher.immediate()
        self.hold = _Hold()
        self.events: list[tuple[str, str]] = []

    def child(self, name: str, on_construct: Callable[[], None] | None = None) -> ComponentVM:
        builder = ComponentVMBuilder().name(name).services(self.hub, self.dispatcher)
        if on_construct is not None:
            builder = builder.on_construct(on_construct)
        return builder.build()

    def container(self, name: str, children: list[ComponentVM]) -> Any:
        builder: Any = (
            CompositeVMBuilder[ComponentVM]()
            if self.kind == "composite"
            else GroupVMBuilder[ComponentVM]()
        )
        container = (
            builder.name(name)
            .services(self.hub, self.dispatcher)
            .children(lambda: list(children))
            .auto_construct_on_add(True)
            .build()
        )

        def record(event: CollectionChangedEvent) -> None:
            self.events.append((name, event.action))

        container.on_collection_changed.subscribe(record)
        return container


def _refused_in_another_thread(calls: list[tuple[str, Callable[[], None]]]) -> list[str]:
    """Run *calls* on a fresh thread; each must raise at once. Return the failures."""
    failures: list[str] = []

    def run() -> None:
        for name, call in calls:
            try:
                call()
            except RuntimeError as error:
                if IN_PROGRESS not in str(error):
                    failures.append(f"{name}: {error}")
            else:
                failures.append(f"{name}: did not raise")

    other = threading.Thread(target=run, daemon=True)
    other.start()
    join_thread(other, HANG_GUARD)
    assert not other.is_alive(), "no refused call waits for the open transaction"
    return failures


def _membership_changes_fail_at_once(kind: str) -> None:
    scene = _Scene(kind)
    m1, m2 = scene.child("m1"), scene.child("m2")
    p = scene.container("p", [m1, m2])
    q = scene.container("q", [])
    p.construct()
    q.construct()
    if kind == "composite":
        p.current = m1
    held = scene.child("held", scene.hold.hold)
    y = scene.child("y")

    # The add's construct hook holds p's transaction on another thread.
    scene.hold.start(lambda: p.add(held))
    members = p.snapshot()
    parents = [member._parent for member in members]
    scene.events.clear()

    def replace() -> None:
        p[0] = y

    failures = _refused_in_another_thread(
        [
            ("add", lambda: p.add(y)),
            ("insert", lambda: p.insert(0, y)),
            ("replace", replace),
            ("transfer out", lambda: q.add(m2)),
            ("remove", lambda: p.remove(m2)),
            ("remove_at", lambda: p.remove_at(0)),
            ("clear", p.clear),
        ]
    )

    assert failures == []
    assert p.snapshot() == members, "the refused calls leave p's membership unchanged"
    assert [member._parent for member in members] == parents
    assert y._parent is None
    assert q.snapshot() == ()
    assert scene.events == [], "the refused calls publish no collection change"
    if kind == "composite":
        assert p.current is m1

    scene.hold.finish()
    assert p.snapshot() == (m1, m2, held)

    # Once the transaction ended, the same calls succeed.
    p.add(y)
    assert p.snapshot()[-1] is y
    z = scene.child("z")
    p.insert(0, z)
    w = scene.child("w")
    p[0] = w
    assert p.snapshot()[0] is w
    q.add(m2)
    assert q.snapshot() == (m2,)
    assert p.remove(y) is True
    p.remove_at(0)
    p.clear()
    assert p.snapshot() == ()


def _population_fails_at_once(kind: str) -> None:
    scene = _Scene(kind)
    factory_child = scene.child("factory")
    p = scene.container("p", [factory_child])
    adding = scene.child("adding")

    def hold_on_add(event: CollectionChangedEvent) -> None:
        # The add publishes inside its membership transaction.
        if event.action == "add":
            scene.hold.hold()

    p.on_collection_changed.subscribe(hold_on_add)
    scene.hold.start(lambda: p.add(adding))
    scene.events.clear()

    # p has not populated; its construct runs the factory population.
    failures = _refused_in_another_thread([("population", p.construct)])

    assert failures == []
    assert p.status is S.DESTRUCTED
    assert p.snapshot() == (adding,)
    assert factory_child._parent is None
    assert scene.events == []

    scene.hold.finish()
    p.construct()
    assert p.status is S.CONSTRUCTED
    assert factory_child in p.snapshot()


CASES = [
    pytest.param(_membership_changes_fail_at_once, id="membership-changes"),
    pytest.param(_population_fails_at_once, id="population"),
]


@pytest.mark.conformance("COMP-048")
@pytest.mark.parametrize("case", CASES)
def test_comp_048_composite_membership_change_fails_at_once(
    case: Callable[[str], None],
) -> None:
    case("composite")


@pytest.mark.conformance("GRP-016")
@pytest.mark.parametrize("case", CASES)
def test_grp_016_group_membership_change_fails_at_once(case: Callable[[str], None]) -> None:
    case("group")

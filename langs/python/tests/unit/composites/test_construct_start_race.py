"""One starter for each child transition (#1370, ADR-0218).

A child that an auto-construct add attaches while the container is
Constructing, before the construct walk's snapshot, has two starters: the add
and the walk. Each reads the child status and then calls ``construct()``.
When the other side starts the child between those two steps, the walk joins
that construct and the add leaves it to the walk. Neither fails. The same
holds for a destruct walk and a destruct that another thread starts
(spec/02 §6, spec/06 §5.1).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from tests.liveness import join_thread, wait_event
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
KINDS = pytest.mark.parametrize("kind", ["composite", "group"])


class _Race:
    """A container whose second construct hook adds a child from another thread."""

    def __init__(self, kind: str) -> None:
        self.hub: MessageHub[object] = MessageHub()
        self.dispatcher = RxDispatcher.immediate()
        self.add_calling = threading.Event()
        self.add_errors: list[BaseException] = []
        self.adder: threading.Thread | None = None
        self.child_runs = 0
        self.hook: Callable[[], None] = lambda: None
        builder: Any = (
            CompositeVMBuilder[ComponentVM]()
            if kind == "composite"
            else GroupVMBuilder[ComponentVM]()
        )
        self.root: Any = (
            builder.name("root")
            .services(self.hub, self.dispatcher)
            .children(list)
            .auto_construct_on_add(True)
            .on_construct(lambda: self.hook())
            .build()
        )
        # Construct and destruct once, so the next construct skips population.
        self.root.construct()
        self.root.destruct()

    def child(self, on_construct: Callable[[], None]) -> ComponentVM:
        def hook() -> None:
            self.child_runs += 1
            on_construct()

        return (
            ComponentVMBuilder()
            .name("child")
            .services(self.hub, self.dispatcher)
            .on_construct(hook)
            .build()
        )

    def construct_while_adding(self, child: ComponentVM) -> list[BaseException]:
        """Construct the root; its hook adds *child* on another thread.

        The hook returns once the add read the child status and calls
        ``construct()``. The walk's snapshot then holds the child.
        """

        def add() -> None:
            try:
                self.root.add(child)
            except BaseException as error:
                self.add_errors.append(error)

        def hook() -> None:
            self.adder = threading.Thread(target=add, daemon=True)
            self.adder.start()
            assert wait_event(self.add_calling), "the add calls construct()"

        self.hook = hook
        errors: list[BaseException] = []
        try:
            self.root.construct()
        except BaseException as error:
            errors.append(error)
        return errors

    def join_adder(self) -> None:
        assert self.adder is not None
        join_thread(self.adder)
        assert not self.adder.is_alive()

    def assert_member_constructed(self, child: ComponentVM) -> None:
        assert self.add_errors == []
        assert self.root.status is S.CONSTRUCTED
        assert child.status is S.CONSTRUCTED
        assert any(member is child for member in self.root.snapshot())
        assert self.child_runs == 1, "the child's construct hook ran once"


def _on_thread(thread: threading.Thread) -> bool:
    return threading.current_thread() is thread


@KINDS
def test_add_leaves_a_construct_the_walk_started(kind: str) -> None:
    """The add reads Destructed, then the walk starts the child first."""
    race = _Race(kind)
    walk_started = threading.Event()
    add_attempted = threading.Event()

    def child_hook() -> None:
        walk_started.set()
        # Stay in flight until the add made its own construct call.
        assert wait_event(add_attempted)

    child = race.child(child_hook)
    original = child.construct
    main = threading.current_thread()

    def seam() -> None:
        if _on_thread(main):
            original()
            return
        race.add_calling.set()
        assert wait_event(walk_started), "the walk starts the child"
        try:
            original()
        finally:
            add_attempted.set()

    child.construct = seam  # type: ignore[method-assign]
    errors = race.construct_while_adding(child)
    race.join_adder()

    assert errors == []
    race.assert_member_constructed(child)


@KINDS
def test_walk_joins_a_construct_the_add_started(kind: str) -> None:
    """The walk reads Destructed, then the add starts the child first."""
    race = _Race(kind)
    add_go = threading.Event()
    child_entered = threading.Event()
    child_release = threading.Event()

    def child_hook() -> None:
        child_entered.set()
        assert wait_event(child_release)

    child = race.child(child_hook)
    original = child.construct
    main = threading.current_thread()

    def seam() -> None:
        if _on_thread(main):
            add_go.set()
            assert wait_event(child_entered), "the add starts the child"
            original()
            return
        race.add_calling.set()
        assert wait_event(add_go)
        original()

    child.construct = seam  # type: ignore[method-assign]
    errors = race.construct_while_adding(child)
    assert errors == []
    assert race.root.status is S.CONSTRUCTING, "the walk joined the add's construct"
    child_release.set()
    race.join_adder()

    race.assert_member_constructed(child)


def test_destruct_walk_joins_a_destruct_another_thread_started() -> None:
    """The walk reads Constructed, then another thread starts the child's destruct."""
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    entered = threading.Event()
    release = threading.Event()
    runs: list[str] = []

    def on_destruct() -> None:
        runs.append(threading.current_thread().name)
        entered.set()
        assert wait_event(release)

    child = (
        ComponentVMBuilder()
        .name("child")
        .services(hub, dispatcher)
        .on_destruct(on_destruct)
        .build()
    )
    root: Any = (
        CompositeVMBuilder[ComponentVM]()
        .name("root")
        .services(hub, dispatcher)
        .children(lambda: [child])
        .build()
    )
    root.construct()
    original = child.destruct
    go = threading.Event()
    errors: list[BaseException] = []

    def other() -> None:
        assert wait_event(go)
        try:
            original()
        except BaseException as error:
            errors.append(error)

    other_thread = threading.Thread(target=other, daemon=True)
    other_thread.start()

    def seam() -> None:
        if _on_thread(other_thread):
            original()
            return
        go.set()
        assert wait_event(entered), "the other thread starts the destruct"
        original()

    child.destruct = seam  # type: ignore[method-assign]
    root.destruct()
    assert root.status is S.DESTRUCTING, "the walk joined the other destruct"
    release.set()
    join_thread(other_thread)
    assert not other_thread.is_alive()

    assert errors == []
    assert root.status is S.DESTRUCTED
    assert child.status is S.DESTRUCTED
    assert len(runs) == 1, "the child's destruct hook ran once"

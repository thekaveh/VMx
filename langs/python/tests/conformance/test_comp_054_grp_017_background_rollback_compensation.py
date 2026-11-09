"""Conformance tests: COMP-054 and GRP-017 — a failed add returns a background child.

A failed add, insert or index replacement that started a ``Destructed``
background child detaches it while its construct is still in flight. VMx
does not wait for the child. When the construct settles at Constructed and
the child has no parent, VMx destructs it, so it ends ``Destructed``
(ADR-0218, spec/06 §4.2, spec/07 §1.1).
"""

from __future__ import annotations

from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus
DISPOSING = "disposing"


class _Queue:
    """Queues background work so the test decides when it runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run_all(self) -> None:
        while self.actions:
            self.actions.pop(0)(self, None)


class _Scene:
    """A container with auto-construct-on-add and a queued background scheduler."""

    def __init__(self, kind: str, *, constructing: bool) -> None:
        self.bg = _Queue()
        self.hub: MessageHub[object] = MessageHub()
        self.dispatcher = RxDispatcher(ImmediateScheduler(), self.bg)  # type: ignore[arg-type]
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
            .build()
        )
        # The member a replacement replaces. It is a synchronous child.
        self.member = self.child("member")
        self.root.add(self.member)
        if constructing:
            # The walk waits on this background member, so the root stays
            # Constructing.
            self.root.add(self.child("anchor", background=True))
        self.root.construct()
        expected = S.CONSTRUCTING if constructing else S.CONSTRUCTED
        assert self.root.status is expected

    def child(self, name: str, *, background: bool = False) -> ComponentVM:
        return (
            ComponentVMBuilder()
            .name(name)
            .services(self.hub, self.dispatcher)
            .background(background)
            .build()
        )

    def dispose_root_when_constructing(self, child: ComponentVM) -> None:
        """A subscriber that disposes the root when *child* publishes Constructing."""

        def on_message(message: object) -> None:
            if (
                isinstance(message, ConstructionStatusChangedMessage)
                and message.sender is child
                and message.status is S.CONSTRUCTING
            ):
                self.root.dispose()

        self.hub.messages.subscribe(on_message)


def _change(scene: _Scene, operation: str, child: ComponentVM) -> None:
    if operation == "add":
        scene.root.add(child)
    elif operation == "insert":
        scene.root.insert(0, child)
    else:
        index = next(i for i, m in enumerate(scene.root.snapshot()) if m is scene.member)
        scene.root[index] = child


def _failed_change_returns_background_child(
    kind: str, operation: str, *, constructing: bool
) -> None:
    scene = _Scene(kind, constructing=constructing)
    child = scene.child("c", background=True)
    scene.dispose_root_when_constructing(child)

    with pytest.raises(RuntimeError, match=DISPOSING):
        _change(scene, operation, child)

    assert child._parent is None
    assert child.status is S.CONSTRUCTING, "the rollback does not wait for the child"
    scene.bg.run_all()
    assert child.status is S.DESTRUCTED
    assert child._parent is None
    assert scene.root.status is S.DISPOSED


def _failed_change_returns_synchronous_child(
    kind: str, operation: str, *, constructing: bool
) -> None:
    scene = _Scene(kind, constructing=constructing)
    child = scene.child("c")
    scene.dispose_root_when_constructing(child)

    with pytest.raises(RuntimeError, match=DISPOSING):
        _change(scene, operation, child)

    scene.bg.run_all()
    assert child.status is S.DESTRUCTED
    assert child._parent is None


OPERATIONS = pytest.mark.parametrize("operation", ["add", "insert", "replace"])
STATES = pytest.mark.parametrize("constructing", [False, True], ids=["constructed", "constructing"])


@pytest.mark.conformance("COMP-054")
@OPERATIONS
@STATES
def test_COMP_054_failed_change_returns_background_child(
    operation: str, constructing: bool
) -> None:
    _failed_change_returns_background_child("composite", operation, constructing=constructing)


@pytest.mark.conformance("COMP-054")
@OPERATIONS
@STATES
def test_COMP_054_failed_change_returns_synchronous_child(
    operation: str, constructing: bool
) -> None:
    _failed_change_returns_synchronous_child("composite", operation, constructing=constructing)


@pytest.mark.conformance("GRP-017")
@OPERATIONS
@STATES
def test_GRP_017_failed_change_returns_background_child(operation: str, constructing: bool) -> None:
    _failed_change_returns_background_child("group", operation, constructing=constructing)


@pytest.mark.conformance("GRP-017")
@OPERATIONS
@STATES
def test_GRP_017_failed_change_returns_synchronous_child(
    operation: str, constructing: bool
) -> None:
    _failed_change_returns_synchronous_child("group", operation, constructing=constructing)

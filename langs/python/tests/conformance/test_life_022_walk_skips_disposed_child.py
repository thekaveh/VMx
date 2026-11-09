"""Conformance test: LIFE-022 — a container walk skips a child disposed directly.

Container walks and the child-transition helper skip a child that is
``Disposed`` (spec/02 §6 and §6.1, ADR-0189). A composite or group keeps the
disposed child as a member; an aggregate replaces the slot at its next
construct. Every call runs on an inline dispatcher, so a lifecycle call on a
disposed child would raise ``StatusTransitionError`` from the walk.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

from vmx import (
    AggregateVM2Builder,
    ComponentVM,
    CompositeVMBuilder,
    ConstructionStatus,
    GroupVMBuilder,
    MessageHub,
    RxDispatcher,
)

S = ConstructionStatus


class _Box:
    """One container under test, with its two children (or slots)."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.hub: MessageHub[Any] = MessageHub()
        self.dispatcher = RxDispatcher.immediate()
        self.created: list[ComponentVM] = []
        a = self._leaf("a")
        b = self._leaf("b")
        if kind == "composite":
            self.vm: Any = (
                CompositeVMBuilder()
                .name("box")
                .services(self.hub, self.dispatcher)
                .children(lambda: [a, b])
                .build()
            )
        elif kind == "group":
            self.vm = (
                GroupVMBuilder()
                .name("box")
                .services(self.hub, self.dispatcher)
                .children(lambda: [a, b])
                .build()
            )
        else:
            self.vm = (
                AggregateVM2Builder()
                .name("box")
                .services(self.hub, self.dispatcher)
                .component_1(lambda: self._leaf("a"))
                .component_2(lambda: self._leaf("b"))
                .build()
            )

    def _leaf(self, name: str) -> ComponentVM:
        leaf = ComponentVM(name=name, hub=self.hub, dispatcher=self.dispatcher)
        self.created.append(leaf)
        return leaf

    def children(self) -> tuple[ComponentVM, ComponentVM]:
        if self.kind == "aggregate":
            return (self.vm.component_1, self.vm.component_2)
        first, second = self.vm.snapshot()
        return (first, second)


@pytest.mark.conformance("LIFE-022")
@pytest.mark.parametrize("kind", ["composite", "group", "aggregate"])
def test_LIFE_022_container_walks_skip_a_disposed_child(kind: str) -> None:
    box = _Box(kind)
    box.vm.construct()
    a, b = box.children()

    b.dispose()
    box.vm.destruct()

    assert box.vm.status is S.DESTRUCTED
    assert a.status is S.DESTRUCTED
    assert b.status is S.DISPOSED

    box.vm.construct()

    assert box.vm.status is S.CONSTRUCTED
    if kind == "aggregate":
        new_a, new_b = box.children()
        assert new_a is not a and new_b is not b
        assert (new_a.status, new_b.status) == (S.CONSTRUCTED, S.CONSTRUCTED)
    else:
        assert box.children() == (a, b)
        assert (a.status, b.status) == (S.CONSTRUCTED, S.DISPOSED)

    box.children()[1].dispose()
    box.vm.reconstruct()

    assert box.vm.status is S.CONSTRUCTED


@pytest.mark.conformance("LIFE-022")
@pytest.mark.parametrize("kind", ["composite", "group"])
def test_LIFE_022_child_disposed_while_the_container_is_destructed(kind: str) -> None:
    box = _Box(kind)
    box.vm.construct()
    box.vm.destruct()
    a, b = box.children()

    b.dispose()
    box.vm.construct()

    assert box.vm.status is S.CONSTRUCTED
    assert box.children() == (a, b)
    assert (a.status, b.status) == (S.CONSTRUCTED, S.DISPOSED)


class _LeafWithMembers(ComponentVM):
    """A leaf VM whose hooks walk its members with the child-transition helper."""

    def __init__(self, hub: MessageHub[Any], members: Iterable[ComponentVM]) -> None:
        super().__init__(name="leaf", hub=hub, dispatcher=RxDispatcher.immediate())
        self.members = list(members)

    def _walk(self, construct: bool) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(self.members, construct=construct)
        )

    def _on_construct(self) -> None:
        self._walk(True)

    def _on_destruct(self) -> None:
        self._walk(False)


@pytest.mark.conformance("LIFE-022")
def test_LIFE_022_child_transition_helper_skips_a_disposed_member() -> None:
    hub: MessageHub[Any] = MessageHub()

    def member(name: str) -> ComponentVM:
        return ComponentVM(name=name, hub=hub, dispatcher=RxDispatcher.immediate())

    m1 = member("m1")
    m2 = member("m2")
    leaf = _LeafWithMembers(hub, [m1, m2])
    m2.dispose()

    steps: list[Callable[[], None]] = [leaf.construct, leaf.destruct]
    targets = [S.CONSTRUCTED, S.DESTRUCTED]
    for step, target in zip(steps, targets, strict=True):
        step()
        assert leaf.status is target
        assert m1.status is target
        assert m2.status is S.DISPOSED

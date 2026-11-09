"""Conformance tests: COMP-047 and GRP-015 — the construct walk counts members only.

A composite or group construct walk checks membership before it starts or
joins a child, and again after the child settles. A child that a removal or a
failed add takes out during the walk does not change the container: the
container still reaches Constructed. A removal never cancels, destructs or
disposes the child (ADR-0186, spec/06 §5.1, spec/07 §4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


class _Queue:
    """Queues background work so the test decides when each item runs."""

    def __init__(self) -> None:
        self.actions: list[Any] = []

    def schedule(self, action: Any, state: Any = None) -> None:
        self.actions.append(action)

    def run(self, index: int) -> None:
        """Run one queued item; a failing child hook re-raises here."""
        action = self.actions.pop(index)
        try:
            action(self, None)
        except RuntimeError as error:
            assert "hook failed" in str(error)

    def run_all(self) -> None:
        while self.actions:
            self.run(0)


class _Scene:
    """A container with a background anchor and children whose hook fails."""

    def __init__(self, kind: str, extra: Callable[[_Scene], list[ComponentVM]]) -> None:
        self.bg = _Queue()
        self.hub: MessageHub[object] = MessageHub()
        self.dispatcher = RxDispatcher(ImmediateScheduler(), self.bg)  # type: ignore[arg-type]
        self.runs: dict[str, int] = {}
        self.anchor = self.child("anchor", background=True)
        self.extra = extra(self)
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
        # Added before construct(): the walk, not a population, starts them.
        for member in (self.anchor, *self.extra):
            self.root.add(member)

    def child(self, name: str, *, background: bool = False, fails: bool = False) -> ComponentVM:
        self.runs[name] = 0

        def hook() -> None:
            self.runs[name] += 1
            if fails:
                raise RuntimeError(f"{name} hook failed")

        return (
            ComponentVMBuilder()
            .name(name)
            .services(self.hub, self.dispatcher)
            .background(background)
            .on_construct(hook)
            .build()
        )

    def construct(self) -> None:
        self.root.construct()
        assert self.root.status is S.CONSTRUCTING, "the walk waits on the anchor"

    def assert_constructed_without(self, removed: ComponentVM) -> None:
        assert self.root.status is S.CONSTRUCTED, "the removal does not roll the container back"
        assert removed.status is S.DESTRUCTED
        assert all(member is not removed for member in self.root.snapshot())
        assert removed._parent is None
        assert self.anchor.status is S.CONSTRUCTED


def _snapshot_child_removed_before_the_walk_reaches_it(kind: str) -> None:
    scene = _Scene(kind, lambda s: [s.child("s", fails=True)])
    skipped = scene.extra[0]
    scene.construct()

    scene.root.remove(skipped)
    scene.bg.run_all()  # the anchor settles; the walk moves past the removed child

    scene.assert_constructed_without(skipped)
    assert scene.runs["s"] == 0, "the walk never starts a removed snapshot child"


def _snapshot_child_removed_while_the_walk_waits_on_it(kind: str) -> None:
    scene = _Scene(kind, lambda s: [s.child("a2", background=True, fails=True)])
    failing = scene.extra[0]
    scene.construct()
    scene.bg.run(0)  # the anchor settles; the walk starts ``a2`` and waits on it
    assert failing.status is S.CONSTRUCTING

    scene.root.remove(failing)
    assert failing.status is S.CONSTRUCTING, "a removal never cancels the child"
    scene.bg.run_all()  # ``a2`` fails and rolls back; the walk ignores the result

    scene.assert_constructed_without(failing)
    assert scene.runs["a2"] == 1


def _late_child_removed_while_the_walk_waits_on_it(kind: str) -> None:
    scene = _Scene(kind, lambda _s: [])
    scene.construct()
    late = scene.child("l", background=True, fails=True)
    scene.root.add(late)  # the add starts the late child
    assert late.status is S.CONSTRUCTING
    scene.bg.run(0)  # the anchor settles; the walk joins ``l``
    assert scene.root.status is S.CONSTRUCTING, "the walk waits on the late child"

    scene.root.remove(late)
    scene.bg.run_all()  # ``l`` fails; the walk ignores the result

    scene.assert_constructed_without(late)
    assert scene.runs["l"] == 1


def _late_child_removed_before_the_walk_reaches_it(kind: str) -> None:
    scene = _Scene(kind, lambda _s: [])
    scene.construct()
    late = scene.child("l", background=True, fails=True)
    scene.root.add(late)
    scene.root.remove(late)
    scene.bg.run(1)  # ``l`` fails while the walk still waits on the anchor
    scene.bg.run_all()  # the anchor settles; the walk skips the removed child

    scene.assert_constructed_without(late)
    assert scene.runs["l"] == 1


def _late_child_whose_add_fails_is_undone(kind: str) -> None:
    scene = _Scene(kind, lambda _s: [])
    scene.construct()
    late = scene.child("l", fails=True)

    with pytest.raises(RuntimeError, match="l hook failed"):
        scene.root.add(late)  # the add's own construct fails; the add is undone
    scene.bg.run_all()

    scene.assert_constructed_without(late)
    assert scene.runs["l"] == 1


CASES = [
    pytest.param(_snapshot_child_removed_before_the_walk_reaches_it, id="snapshot-before"),
    pytest.param(_snapshot_child_removed_while_the_walk_waits_on_it, id="snapshot-waiting"),
    pytest.param(_late_child_removed_while_the_walk_waits_on_it, id="late-waiting"),
    pytest.param(_late_child_removed_before_the_walk_reaches_it, id="late-before"),
    pytest.param(_late_child_whose_add_fails_is_undone, id="late-add-fails"),
]


@pytest.mark.conformance("COMP-047")
@pytest.mark.parametrize("case", CASES)
def test_comp_047_composite_construct_walk_counts_members_only(
    case: Callable[[str], None],
) -> None:
    case("composite")


@pytest.mark.conformance("GRP-015")
@pytest.mark.parametrize("case", CASES)
def test_grp_015_group_construct_walk_counts_members_only(case: Callable[[str], None]) -> None:
    case("group")

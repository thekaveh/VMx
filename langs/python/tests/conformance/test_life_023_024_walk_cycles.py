"""Conformance tests: LIFE-023 and LIFE-024 — a child-transition walk that closes a cycle.

A walk that lists its own view-model, or that would join a view-model whose
walk waits back on the walking one, fails with the flavor's usage error and
starts no child, so no view-model is left ``Constructing`` (spec/02 §6.1,
ADR-0255). The diamond case is the control: two walks that share a child
still construct all three view-models (LIFE-020).
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx import ComponentVM, ConstructionStatus, GroupVM, MessageHub, RxDispatcher


class _Walker(ComponentVM):
    """A leaf VM whose construct and destruct hooks walk ``walk_list``."""

    def __init__(self, name: str, hub: MessageHub[Any], dispatcher: RxDispatcher) -> None:
        super().__init__(name=name, hub=hub, dispatcher=dispatcher)
        self.walk_list: list[ComponentVM] = []
        self.hook_runs = 0

    def _on_construct(self) -> None:
        self.hook_runs += 1
        self._complete_lifecycle_hook_after(
            self._transition_children(list(self.walk_list), construct=True)
        )

    def _on_destruct(self) -> None:
        self._complete_lifecycle_hook_after(
            self._transition_children(list(self.walk_list), construct=False)
        )


def _env() -> tuple[MessageHub[Any], RxDispatcher]:
    return MessageHub(), RxDispatcher.immediate()


@pytest.mark.conformance("LIFE-023")
def test_LIFE_023_walk_listing_its_own_view_model_fails_and_starts_no_child() -> None:
    hub, dispatcher = _env()
    walker = _Walker("walker", hub, dispatcher)
    sibling = _Walker("sibling", hub, dispatcher)
    walker.walk_list = [walker, sibling]

    with pytest.raises(RuntimeError):
        walker.construct()

    assert walker.status is ConstructionStatus.DESTRUCTED
    assert sibling.status is ConstructionStatus.DESTRUCTED
    assert sibling.hook_runs == 0


@pytest.mark.conformance("LIFE-024")
def test_LIFE_024_two_walks_that_list_each_other_both_settle() -> None:
    hub, dispatcher = _env()
    p = _Walker("p", hub, dispatcher)
    q = _Walker("q", hub, dispatcher)
    p.walk_list = [q]
    q.walk_list = [p]

    with pytest.raises(RuntimeError):
        p.construct()

    assert p.status is ConstructionStatus.DESTRUCTED
    assert q.status is ConstructionStatus.DESTRUCTED


@pytest.mark.conformance("LIFE-024")
def test_LIFE_024_leaf_walking_its_own_group_fails_the_group_and_rolls_it_back() -> None:
    hub, dispatcher = _env()
    leaf = _Walker("leaf", hub, dispatcher)
    group = GroupVM(name="group", hub=hub, dispatcher=dispatcher, children_factory=lambda: [leaf])
    leaf.walk_list = [group]

    with pytest.raises(RuntimeError):
        group.construct()

    assert group.status is ConstructionStatus.DESTRUCTED
    assert leaf.status is ConstructionStatus.DESTRUCTED


@pytest.mark.conformance("LIFE-020")
def test_LIFE_020_diamond_walks_construct_all_three_view_models() -> None:
    hub, dispatcher = _env()
    a = _Walker("a", hub, dispatcher)
    b = _Walker("b", hub, dispatcher)
    c = _Walker("c", hub, dispatcher)
    a.walk_list = [c]
    b.walk_list = [c]

    a.construct()
    b.construct()

    assert a.status is ConstructionStatus.CONSTRUCTED
    assert b.status is ConstructionStatus.CONSTRUCTED
    assert c.status is ConstructionStatus.CONSTRUCTED
    assert c.hook_runs == 1

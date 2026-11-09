"""HIER-042..044 — attach_many indexes the materialized subtree of a candidate.

See spec/18-hierarchical-vm.md §6 and ADR-0212.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pytest

from vmx.hierarchical import (
    BatchAttachRejection,
    BatchAttachRejectionReason,
    BatchAttachResult,
    HierarchicalVM,
    MissingParentPolicy,
)
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


@dataclass(frozen=True)
class Model:
    key: str
    parent_key: str | None


class Node(HierarchicalVM[Model, "Node"]):
    def __init__(
        self,
        key: str,
        parent_key: str | None = None,
        factory: Callable[[Node], Iterable[Node]] | None = None,
    ) -> None:
        super().__init__(
            model=Model(key, parent_key),
            children_factory=factory or (lambda _: []),
            hub=MessageHub(),
            dispatcher=RxDispatcher.immediate(),
            name=key,
        )


def attach(
    root: Node,
    items: list[Node],
    policy: MissingParentPolicy = MissingParentPolicy.PARK,
) -> BatchAttachResult[Node]:
    return root.attach_many(
        items,
        key_of=lambda node: node.model.key,
        parent_key_of=lambda node: node.model.parent_key,
        on_missing_parent=policy,
    )


@pytest.mark.conformance("HIER-042")
def test_hier_042_candidate_attaches_below_a_node_of_an_attached_subtree() -> None:
    root = Node("root")
    p = Node("p")
    c = Node("c")
    p.add_child(c)
    x = Node("x", "c")

    result = attach(root, [p, x])

    assert result.added == [p, x]
    assert result.rejections == []
    assert result.orphans == []
    assert result.duplicates == []
    assert list(root.children) == [p]
    assert list(p.children) == [c]
    assert list(c.children) == [x]
    assert x.path == [root, p, c, x]
    assert root.parked_attach_count == 0


@pytest.mark.conformance("HIER-042")
def test_hier_042_parent_key_naming_own_descendant_is_a_cycle() -> None:
    calls = 0

    def counting(_: Node) -> list[Node]:
        nonlocal calls
        calls += 1
        return []

    root = Node("root")
    q = Node("q", "d")
    d = Node("d", factory=counting)
    q.add_child(d)

    result = attach(root, [q], MissingParentPolicy.PARK)

    assert result.added == []
    assert result.orphans == []
    assert result.rejections == [BatchAttachRejection(q, BatchAttachRejectionReason.CYCLE)]
    assert root.parked_attach_count == 0
    assert q.parent is None
    assert calls == 0, "reading subtree keys must not run a children factory"


@pytest.mark.conformance("HIER-043")
def test_hier_043_descendant_key_in_the_index_rejects_the_candidate() -> None:
    root = Node("root")
    existing = Node("c")
    root.add_child(existing)
    p = Node("p")
    inner = Node("c")
    p.add_child(inner)

    result = attach(root, [p])

    assert result.added == []
    assert result.duplicates == [p]
    assert result.rejections == [
        BatchAttachRejection(p, BatchAttachRejectionReason.DUPLICATE_EXISTING_KEY)
    ]
    assert p.parent is None
    assert list(p.children) == [inner]
    assert list(root.children) == [existing]


@pytest.mark.conformance("HIER-043")
def test_hier_043_descendant_key_claimed_first_rejects_a_later_candidate() -> None:
    root = Node("root")
    p = Node("p")
    c = Node("c")
    p.add_child(c)
    c2 = Node("c", "p")

    result = attach(root, [p, c2])

    assert result.added == [p]
    assert result.duplicates == [c2]
    assert result.rejections == [
        BatchAttachRejection(c2, BatchAttachRejectionReason.DUPLICATE_BATCH_KEY)
    ]
    assert list(p.children) == [c]
    assert c2.parent is None


@pytest.mark.conformance("HIER-043")
def test_hier_043_earlier_candidate_key_rejects_a_subtree_that_repeats_it() -> None:
    root = Node("root")
    p = Node("p")
    c = Node("c")
    p.add_child(c)
    c2 = Node("c", "p")

    result = attach(root, [c2, p])

    assert result.added == []
    assert result.duplicates == [p]
    assert BatchAttachRejection(p, BatchAttachRejectionReason.DUPLICATE_BATCH_KEY) in (
        result.rejections
    )
    assert result.orphans == [c2]
    assert BatchAttachRejection(c2, BatchAttachRejectionReason.MISSING_PARENT) in (
        result.rejections
    )
    assert p.parent is None and c2.parent is None
    assert list(p.children) == [c]


@pytest.mark.conformance("HIER-044")
def test_hier_044_factory_children_join_the_index_only_in_the_next_batch() -> None:
    root = Node("root")
    f = Node("f")
    lazy = Node("L", factory=lambda _: [f])
    root.add_child(lazy)
    y = Node("y", "L")
    z = Node("z", "f")

    first = attach(root, [y, z], MissingParentPolicy.PARK)

    assert first.added == [y]
    assert list(lazy.children) == [f, y]
    assert first.orphans == [z]
    assert first.rejections == [BatchAttachRejection(z, BatchAttachRejectionReason.MISSING_PARENT)]
    assert root.parked_attach_count == 1

    second = attach(root, [])

    assert second.added == [z]
    assert second.rejections == []
    assert z.parent is f
    assert root.parked_attach_count == 0

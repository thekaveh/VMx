"""HIER-023..030 — key-aware batch attachment for HierarchicalVM."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from vmx.hierarchical import (
    BatchAttachRejectionReason,
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
    def __init__(self, key: str, parent_key: str | None = None) -> None:
        super().__init__(
            model=Model(key, parent_key),
            children_factory=lambda _: [],
            hub=MessageHub(),
            dispatcher=RxDispatcher.immediate(),
            name=key,
        )


def attach(root: Node, items: list[Node], policy: MissingParentPolicy = MissingParentPolicy.PARK):
    return root.attach_many(
        items,
        key_of=lambda node: node.model.key,
        parent_key_of=lambda node: node.model.parent_key,
        on_missing_parent=policy,
    )


@pytest.mark.conformance("HIER-023")
def test_hier_023_child_before_parent_reaches_fixpoint_in_stable_sibling_order() -> None:
    root = Node("root")
    grandchild = Node("grandchild", "child-a")
    child_b = Node("child-b", "parent")
    child_a = Node("child-a", "parent")
    parent = Node("parent")

    result = attach(root, [grandchild, child_b, child_a, parent])

    assert set(result.added) == {grandchild, child_b, child_a, parent}
    assert list(root.children) == [parent]
    assert list(parent.children) == [child_b, child_a]
    assert list(child_a.children) == [grandchild]
    assert grandchild.path == [root, parent, child_a, grandchild]
    assert result.rejections == []


@pytest.mark.conformance("HIER-024")
def test_hier_024_null_parent_keys_attach_multiple_roots_below_receiver_root() -> None:
    root = Node("root")
    first = Node("first")
    second = Node("second")

    result = attach(root, [first, second])

    assert result.added == [first, second]
    assert list(root.children) == [first, second]
    assert first.parent is root and second.parent is root


@pytest.mark.conformance("HIER-025")
def test_hier_025_duplicate_keys_never_replace_existing_or_first_batch_node() -> None:
    root = Node("root")
    existing = Node("existing")
    root.add_child(existing)
    conflict = Node("existing")
    first = Node("new")
    conflict_in_batch = Node("new")

    result = attach(root, [conflict, first, conflict_in_batch])

    assert result.added == [first]
    assert result.duplicates == [conflict, conflict_in_batch]
    assert list(root.children) == [existing, first]
    assert [rejection.reason for rejection in result.rejections] == [
        BatchAttachRejectionReason.DUPLICATE_EXISTING_KEY,
        BatchAttachRejectionReason.DUPLICATE_BATCH_KEY,
    ]

    repeated = attach(root, [first])
    assert repeated.added == []
    assert repeated.duplicates == [first]
    assert list(root.children) == [existing, first]


@pytest.mark.conformance("HIER-026")
def test_hier_026_parked_orphan_resolves_when_parent_arrives_in_later_batch() -> None:
    root = Node("root")
    child = Node("child", "parent")

    first = attach(root, [child])
    assert first.orphans == [child]
    assert root.parked_attach_count == 1
    assert child.parent is None

    parent = Node("parent")
    second = attach(root, [parent])

    assert set(second.added) == {parent, child}
    assert child.parent is parent
    assert root.parked_attach_count == 0


@pytest.mark.conformance("HIER-027")
def test_hier_027_reject_policy_returns_orphan_without_retaining_it() -> None:
    root = Node("root")
    child = Node("child", "parent")

    first = attach(root, [child], MissingParentPolicy.REJECT)

    assert first.orphans == [child]
    assert root.parked_attach_count == 0
    parent = Node("parent")
    attach(root, [parent])
    assert child.parent is None
    assert list(parent.children) == []


@pytest.mark.conformance("HIER-028")
def test_hier_028_parent_key_cycles_are_terminal_non_throwing_rejections() -> None:
    root = Node("root")
    first = Node("first", "second")
    second = Node("second", "first")

    result = attach(root, [first, second])

    assert result.added == []
    assert result.orphans == []
    assert [rejection.reason for rejection in result.rejections] == [
        BatchAttachRejectionReason.CYCLE,
        BatchAttachRejectionReason.CYCLE,
    ]
    assert root.parked_attach_count == 0
    assert list(root.children) == []


@pytest.mark.conformance("HIER-029")
def test_hier_029_item_rejections_are_structured_and_leave_parent_links_atomic() -> None:
    root = Node("root")
    outside = Node("outside")
    attached = Node("attached")
    outside.add_child(attached)
    detached_same_key = Node("attached")

    result = attach(root, [attached, detached_same_key])

    assert result.added == [detached_same_key]
    assert result.rejections[0].item is attached
    assert result.rejections[0].reason is BatchAttachRejectionReason.ALREADY_ATTACHED
    assert attached.parent is outside
    assert list(outside.children) == [attached]
    assert list(root.children) == [detached_same_key]

    selector_failure = root.attach_many(
        [Node("bad")],
        key_of=lambda _: (_ for _ in ()).throw(RuntimeError("bad key")),
        parent_key_of=lambda _: None,
    )
    assert selector_failure.rejections[0].reason is BatchAttachRejectionReason.SELECTOR_FAILED


@pytest.mark.conformance("HIER-030")
def test_hier_030_dispose_clears_root_owned_parked_items() -> None:
    root = Node("root")
    attach(root, [Node("child", "missing")])
    assert root.parked_attach_count == 1

    root.dispose()

    assert root.parked_attach_count == 0

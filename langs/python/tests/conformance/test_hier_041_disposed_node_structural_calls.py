"""HIER-041 — a disposed node refuses structural calls (spec/18 §7.1, ADR-0190)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

from vmx.hierarchical import BatchAttachRejectionReason, HierarchicalVM, MissingParentPolicy
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.tree_structure_changed import TreeStructureChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class Model:
    pass


class Node(HierarchicalVM[Model, "Node"]):
    """Tree node whose factory returns a fixed list and counts its calls."""

    def __init__(self, hub: MessageHub[Any], name: str, children: Iterable[Node] = ()) -> None:
        self.factory_calls = 0
        fixed = list(children)

        def factory(_: Node) -> list[Node]:
            self.factory_calls += 1
            return fixed

        super().__init__(
            model=Model(),
            children_factory=factory,
            hub=hub,
            dispatcher=RxDispatcher.immediate(),
            name=name,
        )


def _record(hub: MessageHub[Any]) -> list[object]:
    messages: list[object] = []

    def record(message: object) -> None:
        if isinstance(message, TreeStructureChangedMessage | PropertyChangedMessage):
            messages.append(message)

    hub.messages.subscribe(record)
    return messages


def _key(node: Node) -> str:
    return node.name


def _children_changes(messages: list[object], sender: Node) -> list[object]:
    return [
        message
        for message in messages
        if isinstance(message, PropertyChangedMessage)
        and message.sender is sender
        and message.property_name == "children"
    ]


class _Tree:
    """r -> [a -> [aa], b], every child list materialized, and detached d."""

    def __init__(self) -> None:
        self.hub: MessageHub[Any] = MessageHub()
        self.aa = Node(self.hub, "aa")
        self.a = Node(self.hub, "a", [self.aa])
        self.b = Node(self.hub, "b")
        self.r = Node(self.hub, "r", [self.a, self.b])
        self.d = Node(self.hub, "d")
        self.r.construct()
        for node in (self.r, self.a, self.aa, self.b, self.d):
            _ = node.children


def _disposed_a() -> tuple[_Tree, list[object]]:
    tree = _Tree()
    tree.a.dispose()
    assert tree.a.status is ConstructionStatus.DISPOSED
    return tree, _record(tree.hub)


@pytest.mark.conformance("HIER-041")
def test_HIER_041_disposed_node_refuses_every_structural_call() -> None:
    tree, messages = _disposed_a()
    a, aa, d = tree.a, tree.aa, tree.d
    calls: list[Callable[[], object]] = [
        lambda: a.add_child(d),
        lambda: a.remove_child(aa),
        lambda: a.reparent_child(d),
        lambda: a.add_child(aa),  # would be a no-op re-add
        lambda: a.remove_child(d),  # would be a no-op remove
        a.invalidate_children,
        a.invalidate_subtree,
        lambda: a.attach_many([d], key_of=_key, parent_key_of=lambda _n: None),
    ]

    for call in calls:
        with pytest.raises(RuntimeError):
            call()

    assert a.children == [aa]
    assert aa.parent is a
    assert d.parent is None
    assert messages == []


@pytest.mark.conformance("HIER-041")
def test_HIER_041_live_node_refuses_a_transfer_out_of_a_disposed_parent() -> None:
    tree, messages = _disposed_a()

    with pytest.raises(RuntimeError):
        tree.b.add_child(tree.aa)
    with pytest.raises(RuntimeError):
        tree.b.reparent_child(tree.aa)

    assert tree.aa.parent is tree.a
    assert tree.a.children == [tree.aa]
    assert tree.b.children == []
    assert messages == []


@pytest.mark.conformance("HIER-041")
def test_HIER_041_attach_many_rejects_a_candidate_under_a_disposed_parent() -> None:
    tree, messages = _disposed_a()

    result = tree.r.attach_many(
        [tree.d],
        key_of=_key,
        parent_key_of=lambda node: "a" if node is tree.d else None,
    )

    assert result.added == []
    assert result.orphans == []
    assert [(item.item, item.reason) for item in result.rejections] == [
        (tree.d, BatchAttachRejectionReason.ATTACHMENT_FAILED)
    ]
    assert tree.r.parked_attach_count == 0
    assert tree.d.parent is None
    assert tree.a.children == [tree.aa]
    assert messages == []


@pytest.mark.conformance("HIER-041")
def test_HIER_041_invalidate_subtree_skips_a_disposed_descendant() -> None:
    tree, messages = _disposed_a()
    a_calls, aa_calls = tree.a.factory_calls, tree.aa.factory_calls

    tree.r.invalidate_subtree()

    assert _children_changes(messages, tree.r) != []
    assert _children_changes(messages, tree.aa) != []
    assert _children_changes(messages, tree.a) == []
    assert tree.a.children == [tree.aa]
    assert tree.a.factory_calls == a_calls
    _ = tree.aa.children
    assert tree.aa.factory_calls == aa_calls + 1


@pytest.mark.conformance("HIER-041")
def test_HIER_041_attach_many_refuses_under_a_disposed_structural_root() -> None:
    hub: MessageHub[Any] = MessageHub()
    c = Node(hub, "c")
    root = Node(hub, "root", [c])
    _ = root.children
    root.dispose()
    assert c.status is not ConstructionStatus.DISPOSED
    orphan = Node(hub, "orphan")

    with pytest.raises(RuntimeError):
        c.attach_many(
            [orphan],
            key_of=_key,
            parent_key_of=lambda _node: "missing",
            on_missing_parent=MissingParentPolicy.PARK,
        )

    assert root.parked_attach_count == 0
    assert orphan.parent is None

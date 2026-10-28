"""HIER-033..040 — TreeSelection over a HierarchicalVM tree (spec/18 §10)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM, TreeSelection
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class Model:
    pass


class Node(HierarchicalVM[Model, "Node"]):
    """Tree node whose factory returns a fixed list and counts its calls."""

    def __init__(
        self,
        children: Iterable[Node] = (),
        hub: MessageHub[Any] | None = None,
        name: str | None = None,
    ) -> None:
        self.factory_calls = 0
        fixed = list(children)

        def factory(_: Node) -> list[Node]:
            self.factory_calls += 1
            return fixed

        super().__init__(
            model=Model(),
            children_factory=factory,
            hub=hub if hub is not None else MessageHub(),
            dispatcher=RxDispatcher.immediate(),
            name=name,
        )


class Tree:
    """root -> [A -> [AA], B], all on one hub, with A and B materialized."""

    def __init__(self, hub: MessageHub[Any] | None = None) -> None:
        self.hub: MessageHub[Any] = hub if hub is not None else MessageHub()
        self.aa = Node(hub=self.hub, name="AA")
        self.a = Node([self.aa], hub=self.hub, name="A")
        self.b = Node(hub=self.hub, name="B")
        self.root = Node([self.a, self.b], hub=self.hub, name="root")
        _ = self.root.children
        _ = self.a.children
        _ = self.b.children

    def nodes(self) -> list[Node]:
        return [self.root, self.a, self.aa, self.b]


def recorder(selection: TreeSelection[Node]) -> list[Node | None]:
    seen: list[Node | None] = []
    selection.current_changed.subscribe(seen.append)
    return seen


@pytest.mark.conformance("HIER-033")
def test_HIER_033_reentrant_select_reaches_every_subscriber_in_order() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)

    def reselect(value: Node | None) -> None:
        if value is tree.aa:
            selection.select(tree.a)

    selection.current_changed.subscribe(reselect)
    seen = recorder(selection)

    selection.select(tree.aa)

    assert seen == [tree.aa, tree.a]
    assert selection.current is tree.a


@pytest.mark.conformance("HIER-033")
def test_HIER_033_select_member_and_publish_each_change_once() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    seen = recorder(selection)

    assert selection.can_select(tree.root)
    assert selection.can_select(tree.a)
    assert selection.can_select(tree.aa)

    selection.select(tree.aa)
    assert selection.current is tree.aa
    selection.select(tree.aa)
    assert selection.current is tree.aa

    selection.clear()
    assert selection.current is None
    selection.clear()

    assert seen == [tree.aa, None]
    assert seen[0] is tree.aa


@pytest.mark.conformance("HIER-034")
def test_HIER_034_select_rejects_nodes_outside_the_materialized_tree() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.a)
    seen = recorder(selection)

    detached = Node(name="detached")
    other_child = Node(name="other-child")
    other_root = Node([other_child], name="other-root")
    _ = other_root.children
    disposed_member = tree.b
    disposed_member.dispose()
    assert disposed_member.parent is tree.root

    candidates = [detached, other_root, other_child, disposed_member]
    every_node = [*tree.nodes(), detached, other_root, other_child]
    calls_before = [node.factory_calls for node in every_node]

    for candidate in candidates:
        assert not selection.can_select(candidate)
        with pytest.raises(ValueError):
            selection.select(candidate)
        assert selection.current is tree.a

    assert seen == []
    assert [node.factory_calls for node in every_node] == calls_before


@pytest.mark.conformance("HIER-035")
def test_HIER_035_removing_an_ancestor_clears_the_selection() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.root.remove_child(tree.a)

    assert selection.current is None
    assert seen == [None]


@pytest.mark.conformance("HIER-035")
def test_HIER_035_removing_the_current_node_clears_the_selection() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.a.remove_child(tree.aa)

    assert selection.current is None
    assert seen == [None]


@pytest.mark.conformance("HIER-036")
def test_HIER_036_move_inside_keeps_and_transfer_out_clears() -> None:
    tree = Tree()
    other_hub: MessageHub[Any] = MessageHub()
    other_root = Node(hub=other_hub, name="other-root")
    _ = other_root.children
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.b.reparent_child(tree.a)

    assert tree.a.parent is tree.b
    assert selection.current is tree.aa
    assert seen == []

    other_root.add_child(tree.a)

    assert tree.a.parent is other_root
    assert selection.current is None
    assert seen == [None]


@pytest.mark.conformance("HIER-037")
def test_HIER_037_invalidating_an_ancestor_clears_the_selection() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.a.invalidate_children()

    assert selection.current is None
    assert seen == [None]
    assert tree.aa.status is not ConstructionStatus.DISPOSED
    assert tree.aa.parent is None
    assert not selection.can_select(tree.aa)


@pytest.mark.conformance("HIER-038")
def test_HIER_038_disposing_an_ancestor_clears_the_selection() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.a.dispose()

    assert selection.current is None
    assert seen == [None]
    assert tree.a.parent is tree.root
    assert tree.aa.parent is tree.a
    assert not selection.can_select(tree.aa)


@pytest.mark.conformance("HIER-038")
def test_HIER_038_disposing_the_current_node_clears_the_selection() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.aa.dispose()

    assert selection.current is None
    assert seen == [None]
    assert not selection.can_select(tree.aa)


@pytest.mark.conformance("HIER-039")
def test_HIER_039_selection_does_not_navigate() -> None:
    hub: MessageHub[Any] = MessageHub()
    a = Node([Node(hub=hub)], hub=hub, name="A")
    root = Node([a], hub=hub, name="root")
    _ = root.children
    assert a.factory_calls == 0
    nodes = [root, a]
    before = [(node.status, node.parent, node.is_current) for node in nodes]
    messages: list[object] = []
    hub.messages.subscribe(messages.append)
    selection = TreeSelection(root)

    selection.select(a)

    assert selection.current is a
    assert a.factory_calls == 0
    assert [(node.status, node.parent, node.is_current) for node in nodes] == before
    assert messages == []


@pytest.mark.conformance("HIER-040")
def test_HIER_040_disposed_selection_is_inert() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen: list[Node | None] = []
    completed: list[bool] = []
    selection.current_changed.subscribe(
        on_next=seen.append, on_completed=lambda: completed.append(True)
    )

    selection.dispose()

    assert completed == [True]
    assert seen == []
    assert selection.current is None
    assert not any(selection.can_select(node) for node in tree.nodes())

    selection.select(tree.a)
    selection.select(Node(name="detached"))
    selection.clear()
    tree.root.remove_child(tree.a)
    tree.b.dispose()
    assert selection.current is None
    selection.dispose()
    assert seen == []
    assert completed == [True]

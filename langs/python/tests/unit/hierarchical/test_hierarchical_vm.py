"""Unit tests for HierarchicalVM[TModel, TVM] edge cases.

Conformance-level tests live in tests/conformance/test_hier_001_to_014.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM
from vmx.messages import TreeStructureChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------


class Model:
    def __init__(self, tag: str = "") -> None:
        self.tag = tag


class Node(HierarchicalVM[Model, "Node"]):
    def __init__(
        self,
        model: Model | None = None,
        children_factory: Any = None,
        hub: MessageHub[Any] | None = None,
        dispatcher: RxDispatcher | None = None,
        name: str | None = None,
        eager_children: bool = False,
    ) -> None:
        super().__init__(
            model=model if model is not None else Model(),
            children_factory=children_factory if children_factory is not None else (lambda _: []),
            hub=hub,
            dispatcher=dispatcher,
            name=name,
            eager_children=eager_children,
        )


def leaf(hub: MessageHub[Any] | None = None, name: str | None = None) -> Node:
    return Node(hub=hub, name=name)


def parent_of(children: list[Node], hub: MessageHub[Any] | None = None) -> Node:
    return Node(children_factory=lambda _: children, hub=hub)


def make_hub() -> MessageHub[Any]:
    return MessageHub()


# ---------------------------------------------------------------------------
# Empty children factory
# ---------------------------------------------------------------------------


class TestEmptyChildrenFactory:
    def test_returns_empty_list(self) -> None:
        node = leaf()
        assert node.children == []

    def test_is_leaf_true(self) -> None:
        node = leaf()
        assert node.is_leaf is True

    def test_multiple_accesses_return_same_object(self) -> None:
        node = leaf()
        first = node.children
        second = node.children
        assert first is second


# ---------------------------------------------------------------------------
# Single-node tree
# ---------------------------------------------------------------------------


class TestSingleNodeTree:
    def test_path_contains_only_self(self) -> None:
        node = leaf()
        assert node.path == [node]

    def test_depth_is_zero(self) -> None:
        assert leaf().depth == 0

    def test_is_root_and_is_leaf(self) -> None:
        node = leaf()
        assert node.is_root is True
        assert node.is_leaf is True


# ---------------------------------------------------------------------------
# Reparenting
# ---------------------------------------------------------------------------


class TestReparenting:
    def test_reparent_updates_parent_reference(self) -> None:
        hub = make_hub()
        child = Node(hub=hub)
        p1 = Node(hub=hub)
        p2 = Node(hub=hub)

        p1.add_child(child)
        assert child.parent is p1

        p2.reparent_child(child)
        assert child.parent is p2
        assert child not in p1.children
        assert child in p2.children

    def test_reparent_noop_when_same_parent(self) -> None:
        hub = make_hub()
        child = Node(hub=hub)
        p = Node(hub=hub)

        p.add_child(child)

        tree_msgs: list[TreeStructureChangedMessage] = []

        def on_msg(m: object) -> None:
            if isinstance(m, TreeStructureChangedMessage):
                tree_msgs.append(m)

        hub.messages.subscribe(on_next=on_msg)

        p.reparent_child(child)  # same parent — no-op
        assert tree_msgs == [], "reparent to same parent must be a no-op"


# ---------------------------------------------------------------------------
# Multiple lazy accesses
# ---------------------------------------------------------------------------


class TestLazyChildrenAccess:
    def test_factory_invoked_exactly_once(self) -> None:
        count = 0

        def factory(_: Node) -> list[Node]:
            nonlocal count
            count += 1
            return [leaf()]

        node = Node(children_factory=factory)
        _ = node.children
        _ = node.children
        _ = node.children
        assert count == 1, "factory must be called exactly once"


# ---------------------------------------------------------------------------
# Path cache invalidation across a chain
# ---------------------------------------------------------------------------


class TestPathCacheInvalidation:
    def test_path_cache_invalidated_for_whole_subtree(self) -> None:
        hub = make_hub()
        grandchild = Node(hub=hub)
        child = Node(children_factory=lambda _: [grandchild], hub=hub)
        root = Node(children_factory=lambda _: [child], hub=hub)

        _ = root.children
        _ = child.children

        old_child_path = child.path
        old_gc_path = grandchild.path

        new_root = Node(hub=hub)
        new_root.reparent_child(child)

        assert child.path is not old_child_path
        assert grandchild.path is not old_gc_path
        assert grandchild.path[0] is new_root


# ---------------------------------------------------------------------------
# AddChild / RemoveChild messaging
# ---------------------------------------------------------------------------


class TestAddRemoveMessaging:
    def test_add_child_publishes_with_correct_index(self) -> None:
        hub = make_hub()
        parent_vm = Node(hub=hub)
        c1 = Node(hub=hub)
        c2 = Node(hub=hub)

        msgs: list[TreeStructureChangedMessage] = []

        def on_msg(m: object) -> None:
            if isinstance(m, TreeStructureChangedMessage):
                msgs.append(m)

        hub.messages.subscribe(on_next=on_msg)

        parent_vm.add_child(c1)
        parent_vm.add_child(c2)

        assert msgs[0].index == 0
        assert msgs[1].index == 1

    def test_remove_child_noop_when_not_in_list(self) -> None:
        hub = make_hub()
        parent_vm = Node(hub=hub)
        orphan = Node(hub=hub)

        msgs: list[TreeStructureChangedMessage] = []

        def on_msg(m: object) -> None:
            if isinstance(m, TreeStructureChangedMessage):
                msgs.append(m)

        hub.messages.subscribe(on_next=on_msg)

        parent_vm.remove_child(orphan)  # not a child
        assert msgs == [], "no message for removing a non-child"


# ---------------------------------------------------------------------------
# IsFirst / IsLast on single child
# ---------------------------------------------------------------------------


class TestSingleChildPredicates:
    def test_single_child_is_both_first_and_last(self) -> None:
        child = leaf()
        root = parent_of([child])
        _ = root.children
        assert child.is_first is True
        assert child.is_last is True


# ---------------------------------------------------------------------------
# Depth across multiple levels
# ---------------------------------------------------------------------------


class TestDepthMultipleLevels:
    def test_depth_accumulates_correctly(self) -> None:
        nodes = [leaf() for _ in range(5)]
        for i in range(3, -1, -1):
            nodes[i] = Node(children_factory=lambda _, n=nodes[i + 1]: [n])

        # Force materialization top-down.
        for n in nodes:
            _ = n.children

        for i, n in enumerate(nodes):
            assert n.depth == i, f"node[{i}].depth should be {i}"


# ---------------------------------------------------------------------------
# None argument validation
# ---------------------------------------------------------------------------


class TestNullValidation:
    def test_add_child_raises_on_none(self) -> None:
        parent_vm = leaf()
        with pytest.raises((ValueError, TypeError)):
            parent_vm.add_child(None)  # type: ignore[arg-type]

    def test_remove_child_raises_on_none(self) -> None:
        parent_vm = leaf()
        with pytest.raises((ValueError, TypeError)):
            parent_vm.remove_child(None)  # type: ignore[arg-type]

    def test_reparent_child_raises_on_none(self) -> None:
        parent_vm = leaf()
        with pytest.raises((ValueError, TypeError)):
            parent_vm.reparent_child(None)  # type: ignore[arg-type]


class _FactoryNode(HierarchicalVM[Model, "_FactoryNode"]):
    """Subclass accepting the documented vm_factory kwargs (incl. hint)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


def test_builder_vm_factory_builds_subclass() -> None:
    """vm_factory wires a concrete subclass (parity with TS vmFactory / C# VmFactory)."""
    from vmx.hierarchical.builders import HierarchicalVMBuilder

    builder: HierarchicalVMBuilder[Model, _FactoryNode] = HierarchicalVMBuilder()
    node = (
        builder.model(Model("root"))
        .children_factory(lambda _: [])
        .services(MessageHub(), RxDispatcher.immediate())
        .vm_factory(_FactoryNode)
        .build()
    )
    assert isinstance(node, _FactoryNode)
    assert node.model.tag == "root"

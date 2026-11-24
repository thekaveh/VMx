"""Unit tests for HierarchicalVM[TModel, TVM] edge cases.

Conformance-level tests live in tests/conformance/test_hier_001_to_014.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM
from vmx.messages import TreeStructureChange, TreeStructureChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub
from vmx.tree import find, walk, walk_expanded

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
            hub=hub if hub is not None else MessageHub(),
            dispatcher=dispatcher if dispatcher is not None else RxDispatcher.immediate(),
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


# ---------------------------------------------------------------------------
# Disposed nodes (spec/18 §7.1, ADR-0190)
# ---------------------------------------------------------------------------


class TestDisposedNodeRefusal:
    def test_transfer_out_of_disposed_parent_does_not_materialize_the_receiver(self) -> None:
        hub = make_hub()
        child = leaf(hub, "child")
        old = parent_of([child], hub)
        _ = old.children
        old.dispose()
        calls: list[Node] = []
        receiver = Node(children_factory=lambda node: calls.append(node) or [], hub=hub)

        with pytest.raises(RuntimeError):
            receiver.add_child(child)

        assert calls == []
        assert child.parent is old

    def test_add_child_rereads_parent_after_lazy_factory_adopts_the_child(self) -> None:
        hub = make_hub()
        child = leaf(hub, "child")
        receiver = parent_of([child], hub)
        tree_msgs: list[TreeStructureChangedMessage] = []

        def on_msg(m: object) -> None:
            if isinstance(m, TreeStructureChangedMessage):
                tree_msgs.append(m)

        hub.messages.subscribe(on_next=on_msg)

        receiver.add_child(child)

        assert list(receiver.children) == [child]
        assert child.parent is receiver
        assert [m.change for m in tree_msgs] == [TreeStructureChange.REPARENTED]

    def test_disposed_unmaterialized_node_refuses_invalidation_without_materializing(
        self,
    ) -> None:
        calls: list[Node] = []
        node = Node(children_factory=lambda vm: calls.append(vm) or [])
        node.dispose()

        with pytest.raises(RuntimeError):
            node.invalidate_children()
        with pytest.raises(RuntimeError):
            node.invalidate_subtree()
        with pytest.raises(RuntimeError):
            node.remove_child(leaf())

        assert calls == []

    def test_live_parent_can_remove_and_invalidate_a_disposed_child(self) -> None:
        hub = make_hub()
        first, second = leaf(hub, "first"), leaf(hub, "second")
        root = parent_of([first, second], hub)
        _ = root.children
        first.dispose()
        second.dispose()

        root.remove_child(first)
        root.invalidate_children()

        assert first.parent is None
        assert second.parent is None


# ---------------------------------------------------------------------------
# Tree walks, depth and path invalidation on deep chains (no recursion)
# ---------------------------------------------------------------------------

DEEP_CHAIN_LEVELS = 10_000


def _deep_chain(levels: int, hub: MessageHub[Any], dispatcher: RxDispatcher) -> Node:
    """A chain of ``levels`` nodes. Children come from factories, so building the
    chain does not touch the path caches."""

    def build(depth: int) -> Node:
        def factory(_: Node) -> list[Node]:
            return [] if depth + 1 == levels else [build(depth + 1)]

        return Node(children_factory=factory, hub=hub, dispatcher=dispatcher, name=f"n{depth}")

    return build(0)


def test_deep_chain_walks_find_and_depth_do_not_recurse() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)

    nodes = list(walk(root))
    last = nodes[-1]

    assert len(nodes) == DEEP_CHAIN_LEVELS
    assert last.depth == DEEP_CHAIN_LEVELS - 1
    assert len(last.path) == DEEP_CHAIN_LEVELS
    assert len(list(walk_expanded(root))) == DEEP_CHAIN_LEVELS
    assert find(root, lambda node: node is last) is last


def test_deep_chain_moves_under_a_new_parent() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    # Materialize top-down in a loop, so the move itself is what recurses.
    last = root
    while not last.is_leaf:
        last = last.children[0]
    new_root = Node(hub=hub, dispatcher=dispatcher, name="new-root")

    new_root.add_child(root)

    assert root.parent is new_root
    assert last.depth == DEEP_CHAIN_LEVELS
    assert last.path[0] is new_root
    assert last.path[1] is root


def _materialize_top_down(root: Node) -> Node:
    """Materialize the chain from the root down, in a loop, and return its leaf."""
    last = root
    while not last.is_leaf:
        last = last.children[0]
    return last


def test_deep_chain_invalidate_subtree_does_not_recurse() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    last = _materialize_top_down(root)
    old_child = root.children[0]

    root.invalidate_subtree()

    assert root.children[0] is not old_child
    assert old_child.parent is None
    assert last.parent is None
    assert last.depth == 0


def test_deep_chain_move_stamps_the_new_tree_root_on_its_subtree() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    nodes = list(walk(root))
    middle, last = nodes[DEEP_CHAIN_LEVELS // 2], nodes[-1]
    new_root = Node(hub=hub, dispatcher=dispatcher, name="new-root")

    new_root.add_child(middle)
    # The chain above middle is now a tree of its own, so it may move under last.
    last.add_child(root)

    assert root.parent is last
    assert last.path[0] is new_root


def test_deep_chain_refuses_its_root_under_a_descendant() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    last = _materialize_top_down(root)
    new_root = Node(hub=hub, dispatcher=dispatcher, name="new-root")
    new_root.add_child(root)

    # The move stamped new_root as the tree root of last, so last refuses it.
    with pytest.raises(ValueError, match="HIER-018"):
        last.add_child(new_root)

    assert new_root.parent is None
    assert root.parent is new_root


def test_deep_chain_refuses_an_ancestor_under_a_descendant() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    nodes = list(walk(root))
    middle, last = nodes[DEEP_CHAIN_LEVELS // 2], nodes[-1]
    parent_of_middle = middle.parent

    with pytest.raises(ValueError, match="HIER-018"):
        last.add_child(middle)

    assert middle.parent is parent_of_middle
    assert last.depth == DEEP_CHAIN_LEVELS - 1


def test_deep_chain_moves_within_one_tree_to_another_branch() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    nodes = list(walk(root))
    branch_tail, last = nodes[-2], nodes[-1]

    # Same tree, and nodes[1] is not inside branch_tail, so the move is legal.
    nodes[1].add_child(branch_tail)

    assert branch_tail.parent is nodes[1]
    assert last.depth == 3


def test_deep_chain_factory_returning_an_ancestor_is_refused() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    last = _materialize_top_down(root)
    tail = Node(children_factory=lambda _: [root], hub=hub, dispatcher=dispatcher, name="tail")
    last.add_child(tail)

    # root has no parent, but it is the top of tail's tree, so it is an ancestor of tail.
    with pytest.raises(ValueError, match="one of its ancestors"):
        _ = tail.children

    assert root.parent is None


def test_deep_chain_factory_adoption_stamps_the_adopter_tree_root() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    root = _deep_chain(DEEP_CHAIN_LEVELS, hub, dispatcher)
    last = _materialize_top_down(root)
    holder = Node(children_factory=lambda _: [root], hub=hub, dispatcher=dispatcher, name="holder")

    assert holder.children[0] is root
    holder.attach_many(
        [Node(hub=hub, dispatcher=dispatcher, name="orphan")],
        key_of=lambda node: node.name,
        parent_key_of=lambda _: "missing",
    )

    # The parked item belongs to the tree root, which is holder for every node below it.
    assert holder.parked_attach_count == 1
    assert last.parked_attach_count == 1


def test_walks_pin_preorder_and_child_read_order_on_a_small_tree() -> None:
    hub = make_hub()
    dispatcher = RxDispatcher.immediate()
    shape = {"root": ["a", "b"], "a": ["a1", "a2"], "a1": ["a1x"], "b": ["b1"]}
    reads: list[str] = []
    by_name: dict[str, Node] = {}

    def factory_for(name: str) -> Callable[[Node], list[Node]]:
        def factory(_: Node) -> list[Node]:
            reads.append(name)
            return [by_name[child] for child in shape.get(name, [])]

        return factory

    for name in ["root", "a", "a1", "a1x", "a2", "b", "b1"]:
        by_name[name] = Node(
            children_factory=factory_for(name), hub=hub, dispatcher=dispatcher, name=name
        )
    root = by_name["root"]
    expected = ["root", "a", "a1", "a1x", "a2", "b", "b1"]

    assert [node.name for node in walk(root)] == expected
    assert reads == expected, "children are read in the same pre-order as the walk"
    assert [node.name for node in walk_expanded(root)] == expected
    assert find(root, lambda node: node.name == "b1") is by_name["b1"]
    assert by_name["a1x"].depth == 3

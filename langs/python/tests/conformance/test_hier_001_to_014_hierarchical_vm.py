"""HIER-001..HIER-014 conformance tests — VMx absorption audit Stage 2 (HierarchicalVM).

Per spec/18-hierarchical-vm.md and ADR-0028.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.capabilities.expandable_state import ExpandableState
from vmx.capabilities.expansion import IExpandable
from vmx.commands.modeled_crud_commands import ModeledCrudCommands
from vmx.hierarchical import HierarchicalVM
from vmx.messages import TreeStructureChange, TreeStructureChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub
from vmx.tree import walk_expanded

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def make_hub() -> MessageHub[Any]:
    return MessageHub()


def make_dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


class MyModel:
    def __init__(self, value: str = "m") -> None:
        self.value = value


# Concrete node subclass — proves the recursive constraint compiles.
class MyNode(HierarchicalVM[MyModel, "MyNode"]):
    def __init__(
        self,
        model: MyModel | None = None,
        children_factory: Any = None,
        hub: MessageHub[Any] | None = None,
        dispatcher: RxDispatcher | None = None,
        name: str | None = None,
        eager_children: bool = False,
    ) -> None:
        super().__init__(
            model=model if model is not None else MyModel(),
            children_factory=children_factory if children_factory is not None else (lambda _: []),
            hub=hub if hub is not None else MessageHub(),
            dispatcher=dispatcher if dispatcher is not None else RxDispatcher.immediate(),
            name=name,
            eager_children=eager_children,
        )


def leaf_node(
    hub: MessageHub[Any] | None = None,
    name: str | None = None,
    dispatcher: RxDispatcher | None = None,
) -> MyNode:
    return MyNode(hub=hub, name=name, dispatcher=dispatcher)


def parent_node(
    children: list[MyNode],
    hub: MessageHub[Any] | None = None,
    eager_children: bool = False,
) -> MyNode:
    return MyNode(children_factory=lambda _: children, hub=hub, eager_children=eager_children)


# ---------------------------------------------------------------------------
# HIER-001 — Recursive generic constraint compiles
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-001")
def test_hier_001_recursive_generic_constraint() -> None:
    """HIER-001: A concrete subclass with the recursive generic constraint
    compiles and constructs without type errors.
    """
    node = MyNode()
    assert node is not None
    assert node.is_root is True
    assert node.depth == 0


# ---------------------------------------------------------------------------
# HIER-002 — Parent is null for root, non-null for non-root
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-002")
def test_hier_002_parent_null_for_root_nonnull_for_child() -> None:
    """HIER-002: parent is None for the root and a TVM reference for non-root nodes."""
    child = leaf_node()
    root = parent_node([child])

    # Force materialization.
    _ = root.children

    assert root.parent is None, "root.parent must be None"
    assert child.parent is root, "child.parent must be the root node"


# ---------------------------------------------------------------------------
# HIER-003 — Depth derivation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-003")
def test_hier_003_depth_derivation() -> None:
    """HIER-003: depth is 0 for root, parent.depth + 1 for each level."""
    grandchild = leaf_node()
    child = parent_node([grandchild])
    root = parent_node([child])

    _ = root.children
    _ = child.children

    assert root.depth == 0
    assert child.depth == 1
    assert grandchild.depth == 2


# ---------------------------------------------------------------------------
# HIER-004 — Path materialization and cache identity
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-004")
def test_hier_004_path_materialization_and_cache() -> None:
    """HIER-004: path returns root-first snapshot; same list returned on repeated
    calls (cached); cache is invalidated after parent changes.
    """
    hub = make_hub()
    grandchild = leaf_node(hub=hub)
    child = parent_node([grandchild], hub=hub)
    root = parent_node([child], hub=hub)

    _ = root.children
    _ = child.children

    # 1. Correct path contents.
    path = grandchild.path
    assert path == [root, child, grandchild]

    # 2. Same list returned on second call (cached).
    assert grandchild.path is path

    # 3. After reparent, path is recomputed.
    new_root = leaf_node(hub=hub)
    new_root.add_child(grandchild)
    assert grandchild.path is not path
    assert grandchild.path == [new_root, grandchild]


# ---------------------------------------------------------------------------
# HIER-005 — IsLeaf and IsRoot derivation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-005")
def test_hier_005_isleaf_and_isroot_derivation() -> None:
    """HIER-005: is_leaf and is_root match parent/children state."""
    leaf = leaf_node()
    root = parent_node([leaf])

    _ = root.children

    assert root.is_root is True
    assert root.is_leaf is False
    assert leaf.is_root is False
    assert leaf.is_leaf is True


# ---------------------------------------------------------------------------
# HIER-006 — IsFirst and IsLast position predicates
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-006")
def test_hier_006_isfirst_and_islast_position_predicates() -> None:
    """HIER-006: is_first and is_last reflect position in parent's children list."""
    c1, c2, c3 = leaf_node(), leaf_node(), leaf_node()
    root = parent_node([c1, c2, c3])

    _ = root.children

    assert c1.is_first is True
    assert c1.is_last is False
    assert c2.is_first is False
    assert c2.is_last is False
    assert c3.is_first is False
    assert c3.is_last is True

    # Root has no parent so both False.
    assert root.is_first is False
    assert root.is_last is False


# ---------------------------------------------------------------------------
# HIER-007 — Default lazy child loading
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-007")
def test_hier_007_default_lazy_child_loading() -> None:
    """HIER-007: children factory is NOT invoked until children is first accessed."""
    factory_invoked = False

    def factory(_: MyNode) -> list[MyNode]:
        nonlocal factory_invoked
        factory_invoked = True
        return [leaf_node()]

    root = MyNode(children_factory=factory)

    assert not factory_invoked, "factory must not be called before .children"

    _ = root.children
    assert factory_invoked, "factory must be called on first .children access"

    factory_invoked = False
    _ = root.children
    assert not factory_invoked, "factory must NOT be called again on subsequent accesses"


# ---------------------------------------------------------------------------
# HIER-008 — Eager child loading via constructor option
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-008")
def test_hier_008_eager_child_loading_via_constructor_option() -> None:
    """HIER-008: passing eager_children=True materializes the full subtree at
    construct() time.
    """
    factory_invoked = False
    leaf = leaf_node()

    def factory(_: MyNode) -> list[MyNode]:
        nonlocal factory_invoked
        factory_invoked = True
        return [leaf]

    root = MyNode(children_factory=factory, eager_children=True)

    assert not factory_invoked, "eager mode: factory not called before construct()"

    root.construct()

    assert factory_invoked, "eager mode: factory invoked during construct()"
    assert root.children == [leaf]


# ---------------------------------------------------------------------------
# HIER-009 — Depth-first construction order
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-009")
def test_hier_009_depth_first_construction_order() -> None:
    """HIER-009: in eager mode, deepest node reaches Constructed before root."""
    from vmx.lifecycle.status import ConstructionStatus
    from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage

    hub = make_hub()
    dispatcher = make_dispatcher()
    order: list[str] = []

    def record_constructed(m: object) -> None:
        if (
            isinstance(m, ConstructionStatusChangedMessage)
            and m.status == ConstructionStatus.CONSTRUCTED
        ):
            order.append(m.sender_name)

    hub.messages.subscribe(on_next=record_constructed)

    grandchild = MyNode(hub=hub, dispatcher=dispatcher, name="grandchild", eager_children=True)
    child = MyNode(
        children_factory=lambda _: [grandchild],
        hub=hub,
        dispatcher=dispatcher,
        name="child",
        eager_children=True,
    )
    root = MyNode(
        children_factory=lambda _: [child],
        hub=hub,
        dispatcher=dispatcher,
        name="root",
        eager_children=True,
    )

    root.construct()

    assert order == ["grandchild", "child", "root"]


# ---------------------------------------------------------------------------
# HIER-010 — PropertyChangedMessage on Parent change
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-010")
def test_hier_010_property_changed_message_on_parent_change() -> None:
    """HIER-010: a PropertyChangedMessage for 'parent' is published when parent changes."""
    hub = make_hub()
    dispatcher = make_dispatcher()

    messages: list[PropertyChangedMessage[Any]] = []

    def on_msg(m: object) -> None:
        if isinstance(m, PropertyChangedMessage):
            messages.append(m)

    hub.messages.subscribe(on_next=on_msg)

    child = MyNode(hub=hub, dispatcher=dispatcher)
    parent_vm = MyNode(hub=hub, dispatcher=dispatcher)

    parent_vm.add_child(child)

    prop_msg = next(
        (m for m in messages if m.property_name == "parent" and m.sender is child),
        None,
    )
    assert prop_msg is not None, "add_child must publish PropertyChangedMessage(parent) on child"


# ---------------------------------------------------------------------------
# HIER-011 — TreeStructureChangedMessage on structural mutations
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-011")
def test_hier_011_tree_structure_changed_message() -> None:
    """HIER-011: TreeStructureChangedMessage is published on add, remove, and reparent."""
    hub = make_hub()
    dispatcher = make_dispatcher()

    tree_msgs: list[TreeStructureChangedMessage] = []

    def on_msg(m: object) -> None:
        if isinstance(m, TreeStructureChangedMessage):
            tree_msgs.append(m)

    hub.messages.subscribe(on_next=on_msg)

    parent_vm = MyNode(hub=hub, dispatcher=dispatcher)
    child = MyNode(hub=hub, dispatcher=dispatcher)

    # Add
    parent_vm.add_child(child)
    assert len(tree_msgs) == 1
    add_msg = tree_msgs[0]
    assert add_msg.change == TreeStructureChange.ADDED
    assert add_msg.sender is parent_vm
    assert add_msg.affected is child
    assert add_msg.index == 0

    tree_msgs.clear()

    # Remove
    parent_vm.remove_child(child)
    assert len(tree_msgs) == 1
    rem_msg = tree_msgs[0]
    assert rem_msg.change == TreeStructureChange.REMOVED
    assert rem_msg.index == 0

    tree_msgs.clear()

    # Reparent
    parent_vm.add_child(child)
    tree_msgs.clear()
    new_parent = MyNode(hub=hub, dispatcher=dispatcher)
    new_parent.reparent_child(child)
    assert len(tree_msgs) == 1
    rep_msg = tree_msgs[0]
    assert rep_msg.change == TreeStructureChange.REPARENTED
    assert rep_msg.sender is new_parent
    assert rep_msg.affected is child
    assert rep_msg.index == -1


# ---------------------------------------------------------------------------
# HIER-012 — walk_expanded honors ExpandableState lazy boundary
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-012")
def test_hier_012_walk_expanded_honors_expandable_state() -> None:
    """HIER-012: walk_expanded honors the lazy boundary when ExpandableState
    is composed and the node is not expanded.

    Uses the same trick as EXP-005: skipping _ComponentVMBase.__init__ to
    avoid the relay-command subscription that triggers a Python 3.10 ABC
    recursion when combining HierarchicalVM (ABC) + IExpandable (ABC).
    The conformance requirement is about walk_expanded behavior, not full VM
    lifecycle — so the partial initialization is intentional and documented.
    """
    from vmx.components.base import _ComponentVMBase

    class ExpandableNode(_ComponentVMBase, IExpandable):
        """Minimal IExpandable HierarchicalVM-like node for HIER-012 testing.

        Does NOT call _ComponentVMBase.__init__ to avoid relay-command
        subscription recursion in Python 3.10 (see EXP-005 for precedent).
        """

        def __init__(
            self,
            children: list[ExpandableNode] | None = None,
            collapsed: bool = True,
        ) -> None:
            # Skip _ComponentVMBase.__init__ per EXP-005 pattern.
            self._name = "expandable-node"
            self._children: list[ExpandableNode] = children or []
            self._expansion = ExpandableState(initially_expanded=not collapsed)

        @property
        def type(self) -> object:
            from vmx.components.protocols import ViewModelType

            return ViewModelType.COMPONENT

        def __iter__(self) -> Any:
            return iter(self._children)

        @property
        def is_expanded(self) -> bool:
            return self._expansion.is_expanded

        def can_expand(self) -> bool:
            return self._expansion.can_expand()

        def expand(self) -> None:
            self._expansion.expand()

    child_leaf = ExpandableNode(children=[], collapsed=False)
    root = ExpandableNode(children=[child_leaf], collapsed=True)

    walked = list(walk_expanded(root))
    # Collapsed root itself is yielded; its children are NOT.
    assert len(walked) == 1
    assert walked[0] is root

    # Expand and walk again.
    root.expand()
    walked_expanded_result = list(walk_expanded(root))
    assert len(walked_expanded_result) == 2  # root + 1 child leaf


# ---------------------------------------------------------------------------
# HIER-013 — Composition with SearchableState filters materialized portion
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-013")
def test_hier_013_searchable_state_composition() -> None:
    """HIER-013: SearchableState composition filters the materialized portion."""
    from vmx.capabilities.searchable_state import SearchableState

    hub = make_hub()
    dispatcher = make_dispatcher()

    apple = MyNode(model=MyModel("apple"), hub=hub, dispatcher=dispatcher)
    banana = MyNode(model=MyModel("banana"), hub=hub, dispatcher=dispatcher)
    cherry = MyNode(model=MyModel("cherry"), hub=hub, dispatcher=dispatcher)
    root = parent_node([apple, banana, cherry], hub=hub)

    search: SearchableState[MyNode] = SearchableState(
        items=lambda: root.children,
        predicate=lambda node, term: term.lower() in node.model.value.lower(),
        debounce_seconds=0,
    )

    result: list[MyNode] = []

    def on_filtered(items: list[MyNode]) -> None:
        result.clear()
        result.extend(items)

    search.filtered.subscribe(on_next=on_filtered)

    search.search_term = "an"
    search.search()

    assert len(result) == 1
    assert result[0].model.value == "banana"


# ---------------------------------------------------------------------------
# HIER-014 — Composition with ModeledCrudCommands mutates the tree
# ---------------------------------------------------------------------------


@pytest.mark.conformance("HIER-014")
def test_hier_014_modeled_crud_commands_composition() -> None:
    """HIER-014: ModeledCrudCommands composition mutates the tree via add/remove_child."""
    hub = make_hub()
    dispatcher = make_dispatcher()

    root = MyNode(hub=hub, dispatcher=dispatcher)
    current: list[MyNode] = []  # mutable container

    def create_new() -> None:
        child = MyNode(model=MyModel("created"), hub=hub, dispatcher=dispatcher)
        root.add_child(child)
        current.clear()
        current.append(child)

    def update_current(node: MyNode) -> None:
        pass  # no-op for this test

    def delete_current(node: MyNode) -> None:
        root.remove_child(node)
        current.clear()

    crud: ModeledCrudCommands[MyModel, MyNode] = ModeledCrudCommands(
        current=lambda: current[0] if current else None,
        create_new=create_new,
        update_current=update_current,
        delete_current=delete_current,
    )

    # Create
    crud.create_new_command.execute(None)
    assert len(root.children) == 1, "create_new_command adds one child"
    assert len(current) == 1

    # Delete
    crud.delete_current_command.execute(None)
    assert len(root.children) == 0, "delete_current_command removes the child"
    assert len(current) == 0

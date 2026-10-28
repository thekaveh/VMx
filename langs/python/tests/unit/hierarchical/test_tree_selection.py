"""Unit tests for TreeSelection[TVM] (spec/18 §10, ADR-0164).

Conformance-level tests live in
tests/conformance/test_hier_033_to_040_tree_selection.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
import reactivex as rx
from reactivex.abc import DisposableBase, ObserverBase
from reactivex.disposable import Disposable

import vmx
from vmx.components.component_vm import ComponentVM
from vmx.hierarchical import HierarchicalVM, TreeSelection
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared test doubles
# ---------------------------------------------------------------------------


class CountingHub:
    """MessageHub wrapper that counts live ``messages`` subscriptions."""

    def __init__(self) -> None:
        self._inner: MessageHub[Any] = MessageHub()
        self.active = 0
        self.subscribed = 0

    @property
    def messages(self) -> rx.Observable[Message]:
        def subscribe(observer: ObserverBase[Message], scheduler: Any = None) -> DisposableBase:
            self.active += 1
            self.subscribed += 1
            inner = self._inner.messages.subscribe(observer)

            def release() -> None:
                self.active -= 1
                inner.dispose()

            return Disposable(release)

        return rx.create(subscribe)

    def send(self, message: Message) -> None:
        self._inner.send(message)

    def batch(self) -> Any:
        return self._inner.batch()


class Model:
    pass


class Node(HierarchicalVM[Model, "Node"]):
    def __init__(
        self,
        children: Iterable[Node] = (),
        hub: Any = None,
        name: str | None = None,
    ) -> None:
        fixed = list(children)
        super().__init__(
            model=Model(),
            children_factory=lambda _: fixed,
            hub=hub if hub is not None else MessageHub(),
            dispatcher=RxDispatcher.immediate(),
            name=name,
        )


class Tree:
    """root -> [A -> [AA], B -> [BB]], with every node materialized."""

    def __init__(self, hub: Any = None, b_hub: Any = None) -> None:
        self.hub = hub if hub is not None else MessageHub()
        b_hub = b_hub if b_hub is not None else self.hub
        self.aa = Node(hub=self.hub, name="AA")
        self.a = Node([self.aa], hub=self.hub, name="A")
        self.bb = Node(hub=b_hub, name="BB")
        self.b = Node([self.bb], hub=b_hub, name="B")
        self.root = Node([self.a, self.b], hub=self.hub, name="root")
        for node in (self.root, self.a, self.aa, self.b, self.bb):
            _ = node.children


def recorder(selection: TreeSelection[Node]) -> list[Node | None]:
    seen: list[Node | None] = []
    selection.current_changed.subscribe(seen.append)
    return seen


# ---------------------------------------------------------------------------
# Surface
# ---------------------------------------------------------------------------


def test_tree_selection_is_exported_from_the_package_root() -> None:
    assert vmx.TreeSelection is TreeSelection
    assert "TreeSelection" in vmx.__all__
    assert "TreeSelection" in vmx.hierarchical.__all__


def test_none_arguments() -> None:
    tree = Tree()
    with pytest.raises(ValueError):
        TreeSelection(None)  # type: ignore[type-var]

    selection = TreeSelection(tree.root)
    assert not selection.can_select(None)
    with pytest.raises(ValueError):
        selection.select(None)  # type: ignore[arg-type]
    assert selection.current is None

    selection.dispose()
    selection.select(None)  # type: ignore[arg-type]  # inert after dispose


def test_current_changed_does_not_replay() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.a)

    seen = recorder(selection)

    assert seen == []


def test_selecting_the_root() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    seen = recorder(selection)

    selection.select(tree.root)

    assert selection.current is tree.root
    assert seen == [tree.root]


def test_root_need_not_be_a_structural_root() -> None:
    tree = Tree()
    selection = TreeSelection(tree.a)

    assert selection.can_select(tree.aa)
    assert not selection.can_select(tree.root)
    assert not selection.can_select(tree.bb)


# ---------------------------------------------------------------------------
# Leaving the tree
# ---------------------------------------------------------------------------


def test_intra_tree_move_rewatches_the_new_path() -> None:
    # B and BB publish on their own hub, which the first path never watched.
    tree = Tree(b_hub=MessageHub())
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.bb.reparent_child(tree.a)
    assert selection.current is tree.aa
    assert seen == []

    # Only BB (on the new path) publishes this event, on the second hub.
    tree.bb.invalidate_children()

    assert selection.current is None
    assert seen == [None]


def test_intra_tree_move_then_removal_from_the_new_location_clears() -> None:
    tree = Tree(b_hub=MessageHub())
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.b.reparent_child(tree.a)
    tree.root.remove_child(tree.b)

    assert selection.current is None
    assert seen == [None]


def test_ancestor_on_another_hub_invalidated_or_removed_clears() -> None:
    tree = Tree(b_hub=MessageHub())
    selection = TreeSelection(tree.root)
    selection.select(tree.bb)
    seen = recorder(selection)

    tree.b.invalidate_children()

    assert selection.current is None
    assert seen == [None]

    tree.b.add_child(tree.bb)
    selection.select(tree.bb)
    tree.root.remove_child(tree.b)

    assert selection.current is None
    assert seen == [None, tree.bb, None]


def test_invalidate_subtree_on_the_root_clears() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.root.invalidate_subtree()

    assert selection.current is None
    assert seen == [None]


def test_root_disposal_clears() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.root.dispose()

    assert selection.current is None
    assert seen == [None]
    assert not selection.can_select(tree.root)


def test_messages_from_nodes_off_the_path_are_ignored() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    tree.b.remove_child(tree.bb)
    tree.b.dispose()

    assert selection.current is tree.aa
    assert seen == []


def test_hub_transaction_defers_the_clear_until_delivery() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    seen = recorder(selection)

    with tree.hub.batch():
        tree.root.remove_child(tree.a)
        assert selection.current is tree.aa
        assert seen == []

    assert selection.current is None
    assert seen == [None]


# ---------------------------------------------------------------------------
# Change stream
# ---------------------------------------------------------------------------


def test_reentrant_select_from_a_subscriber() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    first: list[Node | None] = []
    second: list[Node | None] = []
    current_seen_by_first: list[Node | None] = []

    def redirect(node: Node | None) -> None:
        first.append(node)
        current_seen_by_first.append(selection.current)
        if node is tree.a:
            selection.select(tree.b)

    selection.current_changed.subscribe(redirect)
    selection.current_changed.subscribe(second.append)

    selection.select(tree.a)

    assert selection.current is tree.b
    assert first == [tree.a, tree.b]
    assert current_seen_by_first == [tree.a, tree.b]
    # Every subscriber sees the changes in order, ending at the final value.
    assert second == [tree.a, tree.b]


def test_reentrant_select_after_a_clear_watches_the_new_path() -> None:
    tree = Tree(b_hub=MessageHub())
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    reselected: list[bool] = []

    def reselect_once(node: Node | None) -> None:
        if node is None and not reselected:
            reselected.append(True)
            selection.select(tree.bb)

    selection.current_changed.subscribe(reselect_once)
    seen = recorder(selection)

    tree.root.remove_child(tree.a)
    assert selection.current is tree.bb
    tree.b.invalidate_children()

    assert selection.current is None
    assert seen == [None, tree.bb, None]


def test_raising_subscriber_does_not_drop_queued_changes() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    later: list[Node | None] = []

    def redirect_then_fail(node: Node | None) -> None:
        if node is tree.a:
            selection.select(tree.b)
            raise RuntimeError("boom")

    selection.current_changed.subscribe(redirect_then_fail)
    selection.current_changed.subscribe(later.append)

    with pytest.raises(RuntimeError, match="boom"):
        selection.select(tree.a)

    assert selection.current is tree.b
    assert later[-1] is tree.b


class TreeOwnerVM(ComponentVM):
    """Owner VM that forwards TreeSelection changes (spec/14 rule 6)."""

    def __init__(self, root: Node, hub: MessageHub[Any]) -> None:
        super().__init__(name="TreeOwner", hub=hub, dispatcher=RxDispatcher.immediate())
        self.selection: TreeSelection[Node] = self._own(TreeSelection(root))
        self._own(
            self.selection.current_changed.subscribe(
                lambda _: self._notify_property_changed("selected_node")
            )
        )

    @property
    def selected_node(self) -> Node | None:
        return self.selection.current


def test_owner_forwards_current_changed_to_its_property_notification() -> None:
    tree = Tree()
    owner_hub: MessageHub[Any] = MessageHub()
    owner = TreeOwnerVM(tree.root, owner_hub)
    local: list[str] = []
    owner.property_changed.subscribe(local.append)
    hub_names: list[str] = []

    def record(message: object) -> None:
        if isinstance(message, PropertyChangedMessage) and message.sender is owner:
            hub_names.append(message.property_name)

    owner_hub.messages.subscribe(record)

    owner.selection.select(tree.aa)
    assert owner.selected_node is tree.aa
    tree.root.remove_child(tree.a)
    assert owner.selected_node is None

    assert local == ["selected_node", "selected_node"]
    assert hub_names == ["selected_node", "selected_node"]

    owner.dispose()
    assert owner.selected_node is None
    assert not owner.selection.can_select(tree.root)


# ---------------------------------------------------------------------------
# Hub subscriptions
# ---------------------------------------------------------------------------


def test_one_subscription_per_distinct_hub_on_the_path() -> None:
    hub = CountingHub()
    b_hub = CountingHub()
    tree = Tree(hub=hub, b_hub=b_hub)
    selection = TreeSelection(tree.root)
    assert hub.active == 0

    selection.select(tree.aa)
    assert (hub.active, b_hub.active) == (1, 0)

    selection.select(tree.bb)
    assert (hub.active, b_hub.active) == (1, 1)

    selection.clear()
    assert (hub.active, b_hub.active) == (0, 0)


def test_unrelated_messages_from_the_path_keep_the_subscriptions() -> None:
    hub = CountingHub()
    tree = Tree(hub=hub)
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    subscribed = hub.subscribed

    tree.a.construct()
    tree.root.add_child(Node(hub=hub))

    assert selection.current is tree.aa
    assert hub.subscribed == subscribed
    assert hub.active == 1


def test_dispose_releases_hub_subscriptions() -> None:
    hub = CountingHub()
    b_hub = CountingHub()
    tree = Tree(hub=hub, b_hub=b_hub)
    selection = TreeSelection(tree.root)
    selection.select(tree.bb)
    seen = recorder(selection)

    selection.dispose()

    assert (hub.active, b_hub.active) == (0, 0)
    tree.root.remove_child(tree.b)
    tree.root.dispose()
    assert seen == []
    assert hub.subscribed == 1
    assert b_hub.subscribed == 1


def test_dispose_runs_every_step_and_reraises_the_first_failure() -> None:
    hub = CountingHub()
    tree = Tree(hub=hub)
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)

    def fail() -> None:
        raise RuntimeError("observer failed")

    selection.current_changed.subscribe(on_completed=fail)

    with pytest.raises(RuntimeError, match="observer failed"):
        selection.dispose()

    assert hub.active == 0
    assert selection.current is None
    assert not selection.can_select(tree.root)
    selection.dispose()  # idempotent


def test_dispose_never_disposes_or_detaches_nodes() -> None:
    tree = Tree()
    selection = TreeSelection(tree.root)
    selection.select(tree.aa)
    statuses = [node.status for node in (tree.root, tree.a, tree.aa)]

    selection.dispose()

    assert [node.status for node in (tree.root, tree.a, tree.aa)] == statuses
    assert tree.aa.parent is tree.a
    assert tree.a.parent is tree.root

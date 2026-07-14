"""HIER-019..022 — HierarchicalVM child-cache invalidation."""

from __future__ import annotations

from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class Model:
    pass


class Node(HierarchicalVM[Model, "Node"]):
    def __init__(
        self,
        children_factory: Any = None,
        hub: MessageHub[Any] | None = None,
    ) -> None:
        super().__init__(
            model=Model(),
            children_factory=children_factory if children_factory is not None else (lambda _: []),
            hub=hub if hub is not None else MessageHub(),
            dispatcher=RxDispatcher.immediate(),
        )


@pytest.mark.conformance("HIER-019")
def test_HIER_019_invalidate_children_reloads_on_next_access() -> None:
    calls = 0

    def factory(_: Node) -> list[Node]:
        nonlocal calls
        calls += 1
        return [Node()]

    root = Node(factory)
    first = root.children[0]

    root.invalidate_children()
    second = root.children[0]

    assert calls == 2
    assert second is not first


def test_invalidate_children_detaches_discarded_children() -> None:
    root = Node(lambda _: [Node()])
    discarded = root.children[0]

    root.invalidate_children()
    replacement = root.children[0]

    assert replacement is not discarded
    assert discarded.parent is None
    assert discarded.is_root
    root.add_child(discarded)
    assert discarded in root.children


@pytest.mark.conformance("HIER-020")
def test_HIER_020_invalidate_unmaterialized_children_is_noop() -> None:
    calls = 0

    def factory(_: Node) -> list[Node]:
        nonlocal calls
        calls += 1
        return []

    root = Node(factory)
    root.invalidate_children()

    assert calls == 0


@pytest.mark.conformance("HIER-021")
def test_HIER_021_invalidate_subtree_reloads_materialized_descendants() -> None:
    grandchild_calls = 0

    def grandchild_factory(_: Node) -> list[Node]:
        nonlocal grandchild_calls
        grandchild_calls += 1
        return [Node()]

    child = Node(grandchild_factory)
    root = Node(lambda _: [child])
    _ = root.children
    first_grandchild = child.children[0]

    root.invalidate_subtree()
    reloaded_child = root.children[0]
    second_grandchild = reloaded_child.children[0]

    assert grandchild_calls == 2
    assert second_grandchild is not first_grandchild


@pytest.mark.conformance("HIER-022")
def test_HIER_022_invalidate_children_publishes_children_property_changed() -> None:
    hub: MessageHub[Any] = MessageHub()
    seen: list[PropertyChangedMessage[Any]] = []

    def record(message: object) -> None:
        if isinstance(message, PropertyChangedMessage):
            seen.append(message)

    hub.messages.subscribe(record)
    root = Node(lambda _: [Node()], hub=hub)
    _ = root.children

    root.invalidate_children()

    assert any(m.sender is root and m.property_name == "children" for m in seen)

"""HIER-031 — child-factory hydration is validated and committed atomically."""

from __future__ import annotations

from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class _Node(HierarchicalVM[str, "_Node"]):
    def __init__(
        self,
        name: str,
        factory: Any = None,
        hub: MessageHub[Any] | None = None,
    ) -> None:
        super().__init__(
            model=name,
            children_factory=factory or (lambda _: []),
            hub=hub or MessageHub(),
            dispatcher=RxDispatcher.immediate(),
            name=name,
        )


@pytest.mark.conformance("HIER-031")
def test_HIER_031_factory_hydration_preflights_before_mutation_and_can_retry() -> None:
    hub: MessageHub[Any] = MessageHub()
    messages: list[object] = []
    hub.messages.subscribe(messages.append)
    first = _Node("first", hub=hub)
    second = _Node("second", hub=hub)
    grandchild = _Node("grandchild", hub=hub)
    first.add_child(grandchild)
    assert list(first.path) == [first]
    assert list(grandchild.path) == [first, grandchild]
    messages.clear()
    snapshot = [first, first]
    root = _Node("root", lambda _: snapshot, hub)

    with pytest.raises(ValueError, match="factory"):
        _ = root.children

    assert first.parent is None
    assert messages == []

    snapshot[:] = [first, second]
    assert list(root.children) == [first, second]
    assert first.parent is root
    assert second.parent is root
    assert list(first.path) == [root, first]
    assert list(grandchild.path) == [root, first, grandchild]
    assert messages == []


@pytest.mark.conformance("HIER-031")
@pytest.mark.parametrize("invalid_kind", ["null", "self", "ancestor", "already_parented"])
def test_HIER_031_factory_rejects_structurally_invalid_nodes(invalid_kind: str) -> None:
    holder: dict[str, _Node] = {}
    existing_parent = _Node("existing")
    candidate = _Node("candidate")
    if invalid_kind == "already_parented":
        existing_parent.add_child(candidate)

    root = _Node(
        "root",
        lambda _: [
            None
            if invalid_kind == "null"
            else holder["root"]
            if invalid_kind == "self"
            else existing_parent
            if invalid_kind == "ancestor"
            else candidate
        ],
    )
    holder["root"] = root
    if invalid_kind == "ancestor":
        existing_parent.add_child(root)

    with pytest.raises(ValueError, match="factory"):
        _ = root.children

    if invalid_kind == "already_parented":
        assert candidate.parent is existing_parent
    elif invalid_kind == "ancestor":
        assert root.parent is existing_parent
    else:
        assert root.parent is None


@pytest.mark.conformance("HIER-032")
@pytest.mark.parametrize("operation", ["add", "remove", "invalidate"])
def test_HIER_032_factory_reentry_is_rejected_and_retryable(operation: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    messages: list[object] = []
    hub.messages.subscribe(messages.append)
    child = _Node("child", hub=hub)
    first_attempt = True

    def factory(parent: _Node) -> list[_Node]:
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            if operation == "add":
                parent.add_child(child)
            elif operation == "remove":
                parent.remove_child(child)
            else:
                parent.invalidate_children()
        return [child]

    root = _Node("root", factory, hub)
    with pytest.raises(ValueError, match="factory"):
        _ = root.children

    assert list(root.children) == [child]
    assert child.parent is root
    assert messages == []

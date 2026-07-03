"""HIER-018 conformance test — ReparentChild rejects self- and ancestor-reparenting.

See spec/18-hierarchical-vm.md §6 and ADR-0037 §2.3.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM
from vmx.messages import TreeStructureChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class _Model:
    def __init__(self, value: str = "m") -> None:
        self.value = value


class _Node(HierarchicalVM[_Model, "_Node"]):
    def __init__(
        self,
        children_factory: Any = None,
        hub: MessageHub[Any] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            model=_Model(),
            children_factory=children_factory if children_factory is not None else (lambda _: []),
            hub=hub if hub is not None else MessageHub(),
            dispatcher=RxDispatcher.immediate(),
            name=name,
        )


@pytest.mark.conformance("HIER-018")
def test_HIER_018_reparent_rejects_self_and_ancestor() -> None:
    hub: MessageHub[Any] = MessageHub()
    leaf = _Node(hub=hub, name="leaf")
    mid = _Node(children_factory=lambda _: [leaf], hub=hub, name="mid")
    root = _Node(children_factory=lambda _: [mid], hub=hub, name="root")
    # Materialize the lazy tree so parent backpointers are wired.
    assert [c.name for c in root.children] == ["mid"]
    assert [c.name for c in mid.children] == ["leaf"]
    assert [n.name for n in leaf.path] == ["root", "mid", "leaf"]

    messages: list[TreeStructureChangedMessage] = []
    hub.messages.subscribe(
        lambda m: messages.append(m) if isinstance(m, TreeStructureChangedMessage) else None
    )

    # Self-reparenting raises.
    with pytest.raises(ValueError, match="HIER-018"):
        leaf.reparent_child(leaf)

    # Reparenting an ancestor under its own descendant raises.
    with pytest.raises(ValueError, match="HIER-018"):
        leaf.reparent_child(root)

    # Tree structure unchanged; no message published.
    assert root.parent is None
    assert mid.parent is root
    assert leaf.parent is mid
    assert leaf.depth == 2
    assert messages == []

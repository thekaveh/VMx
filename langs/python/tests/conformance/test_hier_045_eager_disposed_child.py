"""HIER-045 — eager construction skips a disposed child (spec/18 §3, ADR-0258)."""

from __future__ import annotations

from typing import Any

import pytest

from vmx.hierarchical import HierarchicalVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class Model:
    pass


class Node(HierarchicalVM[Model, "Node"]):
    def __init__(
        self,
        hub: MessageHub[Any],
        name: str,
        children: list[Node] | None = None,
        eager: bool = False,
    ) -> None:
        fixed = list(children or [])
        super().__init__(
            model=Model(),
            children_factory=lambda _: fixed,
            hub=hub,
            dispatcher=RxDispatcher.immediate(),
            name=name,
            eager_children=eager,
        )


@pytest.mark.conformance("HIER-045")
def test_hier_045_eager_construction_skips_a_disposed_child() -> None:
    """An eager root with a disposed child: construct() and reconstruct() do not
    raise, the live sibling is constructed, and the disposed child stays Disposed
    and publishes no construction-status change."""
    hub: MessageHub[Any] = MessageHub()
    a = Node(hub, "a")
    b = Node(hub, "b")
    root = Node(hub, "root", children=[a, b], eager=True)

    changes: list[tuple[str, ConstructionStatus]] = []

    def record(message: object) -> None:
        if isinstance(message, ConstructionStatusChangedMessage):
            changes.append((message.sender_name, message.status))

    hub.messages.subscribe(record)

    root.construct()
    a.dispose()
    root.destruct()
    b.destruct()
    changes.clear()

    root.construct()
    root.reconstruct()

    assert root.status == ConstructionStatus.CONSTRUCTED
    assert b.status == ConstructionStatus.CONSTRUCTED
    assert a.status == ConstructionStatus.DISPOSED
    assert [name for name, _ in changes if name == "a"] == []

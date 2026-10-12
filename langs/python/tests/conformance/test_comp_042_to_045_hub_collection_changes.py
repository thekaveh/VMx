"""Conformance tests: COMP-042..045 and GRP-012..013.

Composites and groups publish their collection changes on their own hub
(spec ch. 01 §1.4, ch. 06 §4, ch. 07, ch. 21 §2.4, ADR-0142).
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.collections import CollectionChangedEvent
from vmx.components.base import _ComponentVMBase
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM, CompositeVMOf
from vmx.forwarding.composite import ForwardingCompositeVM
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

_Entry = tuple[str, str, int, int, tuple[str, ...], tuple[str, ...]]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_DISPATCHER = RxDispatcher.immediate()


def _child(hub: MessageHub[Any], name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, _DISPATCHER).build()


def _composite(
    hub: MessageHub[Any], name: str = "composite", *, auto_construct: bool = False
) -> CompositeVM[_ComponentVMBase]:
    return (
        CompositeVMBuilder()
        .name(name)
        .services(hub, _DISPATCHER)
        .auto_construct_on_add(auto_construct)
        .children(lambda: ())
        .build()
    )


def _group(hub: MessageHub[Any], name: str = "group") -> GroupVM[_ComponentVMBase]:
    return GroupVMBuilder().name(name).services(hub, _DISPATCHER).children(lambda: ()).build()


def _names(items: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(str(getattr(item, "name", item)) for item in items)


def _hub_messages(hub: MessageHub[Any]) -> list[CollectionChangedMessage[object]]:
    messages: list[CollectionChangedMessage[object]] = []

    def record(message: object) -> None:
        if isinstance(message, CollectionChangedMessage):
            messages.append(message)

    hub.messages.subscribe(record)
    return messages


def _interleaved(hub: MessageHub[Any], *containers: Any) -> list[_Entry]:
    """One delivery-ordered log of local events and hub messages from *containers*.

    Each entry is ``(channel, action, old_index, new_index, new_items,
    old_items)``; the channel names the container and whether the entry came
    from its local stream or the hub.
    """
    log: list[_Entry] = []
    for container in containers:

        def on_local(event: CollectionChangedEvent, owner: Any = container) -> None:
            log.append(
                (
                    f"local:{owner.name}",
                    event.action,
                    event.old_index,
                    event.new_index,
                    _names(event.new_items),
                    _names(event.old_items),
                )
            )

        container.on_collection_changed.subscribe(on_local)

    def on_hub(message: object) -> None:
        if not isinstance(message, CollectionChangedMessage):
            return
        for container in containers:
            if message.sender is container:
                log.append(
                    (
                        f"hub:{container.name}",
                        message.action,
                        message.old_index,
                        message.new_index,
                        _names(message.new_items),
                        _names(message.old_items),
                    )
                )

    hub.messages.subscribe(on_hub)
    return log


def _assert_hub_follows_each_local_event(log: list[_Entry], local_events: int) -> None:
    assert len(log) == local_events * 2, log
    for local, hub in zip(log[0::2], log[1::2], strict=True):
        assert local[0].startswith("local:"), log
        assert hub == ("hub:" + local[0].removeprefix("local:"), *local[1:]), log


# ===========================================================================
# COMP-042 — Composite collection changes publish on the hub
# ===========================================================================


@pytest.mark.conformance("COMP-042")
def test_COMP_042_publishes_one_hub_message_after_each_local_event() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    a, b, c, d = (_child(hub, name) for name in "abcd")
    log = _interleaved(hub, parent)
    messages = _hub_messages(hub)

    parent.add(a)
    parent.insert(0, b)
    parent.move(0, 1)
    parent[0] = c  # replacement keeps Python's local Remove + Add decomposition
    parent.remove_at(1)
    assert parent.remove(c) is True
    parent.add(d)
    parent.clear()

    _assert_hub_follows_each_local_event(log, 9)
    assert all(message.sender is parent for message in messages)
    assert all(message.sender_object is parent for message in messages)
    assert [message.action for message in messages] == [
        "add",
        "add",
        "move",
        "remove",
        "add",
        "remove",
        "remove",
        "add",
        "reset",
    ]
    assert messages[0].new_items == (a,)
    assert (messages[0].index, messages[0].new_index) == (0, 0)
    assert messages[2].new_items == (b,)
    assert messages[2].old_items == (b,)
    assert (messages[2].old_index, messages[2].new_index) == (0, 1)
    assert messages[3].old_items == (a,)
    assert (messages[3].index, messages[3].old_index) == (0, 0)
    assert messages[4].new_items == (c,)
    assert (messages[5].old_items, messages[5].old_index) == ((b,), 1)
    assert (messages[8].new_items, messages[8].old_items, messages[8].index) == ((), (), -1)


@pytest.mark.conformance("COMP-042")
def test_COMP_042_local_and_hub_observe_the_committed_membership() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    a = _child(hub, "a")
    seen: list[tuple[str, bool]] = []
    parent.on_collection_changed.subscribe(lambda _event: seen.append(("local", a in parent)))

    def on_hub(message: object) -> None:
        if isinstance(message, CollectionChangedMessage):
            seen.append(("hub", a in parent.snapshot()))

    hub.messages.subscribe(on_hub)

    parent.add(a)
    parent.remove(a)

    assert seen == [("local", True), ("hub", True), ("local", False), ("hub", False)]


@pytest.mark.conformance("COMP-042")
def test_COMP_042_modeled_composite_population_publishes_each_add() -> None:
    hub: MessageHub[Any] = MessageHub()

    def to_child(model: str) -> _ComponentVMBase:
        return _child(hub, model)

    parent: CompositeVMOf[str, _ComponentVMBase] = (
        CompositeVMOfBuilder()
        .name("modeled")
        .services(hub, _DISPATCHER)
        .children_models(lambda: ["x", "y"])
        .child_model_to_child_view_model(to_child)
        .build()
    )
    log = _interleaved(hub, parent)

    parent.construct()

    _assert_hub_follows_each_local_event(log, 2)
    assert [(entry[1], entry[3], entry[4]) for entry in log[1::2]] == [
        ("add", 0, ("x",)),
        ("add", 1, ("y",)),
    ]


def test_failing_local_subscriber_does_not_suppress_the_hub_message() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    messages = _hub_messages(hub)

    def fail(_event: CollectionChangedEvent) -> None:
        raise RuntimeError("local subscriber failure")

    parent.on_collection_changed.subscribe(fail)

    with pytest.raises(RuntimeError, match="local subscriber failure"):
        parent.add(_child(hub, "a"))

    assert [(message.sender, message.action) for message in messages] == [(parent, "add")]


# ===========================================================================
# COMP-043 — Composite batches publish one hub Reset
# ===========================================================================


@pytest.mark.conformance("COMP-043")
def test_COMP_043_batch_publishes_nothing_inside_and_one_reset_after_local_reset() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    log = _interleaved(hub, parent)

    outer = parent.batch_update()
    parent.add(_child(hub, "a"))
    with parent.batch_update():
        parent.add(_child(hub, "b"))
        parent.move(0, 1)
    assert log == []
    outer.dispose()

    assert log == [
        ("local:composite", "reset", -1, -1, (), ()),
        ("hub:composite", "reset", -1, -1, (), ()),
    ]


@pytest.mark.conformance("COMP-043")
def test_COMP_043_empty_or_same_index_move_batch_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    parent.add(_child(hub, "a"))
    messages = _hub_messages(hub)

    parent.batch_update().dispose()
    with parent.batch_update():
        parent.move(0, 0)

    assert messages == []


# ===========================================================================
# COMP-044 — Transfers publish removal before addition; failures publish nothing
# ===========================================================================


@pytest.mark.conformance("COMP-044")
def test_COMP_044_transfer_publishes_old_remove_before_new_add() -> None:
    hub: MessageHub[Any] = MessageHub()
    old = _composite(hub, "old")
    new = _composite(hub, "new")
    old.add(_child(hub, "sibling"))
    moved = _child(hub, "moved")
    old.add(moved)
    log = _interleaved(hub, old, new)
    messages = _hub_messages(hub)

    new.add(moved)

    assert log == [
        ("local:old", "remove", 1, -1, (), ("moved",)),
        ("hub:old", "remove", 1, -1, (), ("moved",)),
        ("local:new", "add", -1, 0, ("moved",), ()),
        ("hub:new", "add", -1, 0, ("moved",), ()),
    ]
    assert [(message.sender, message.action) for message in messages] == [
        (old, "remove"),
        (new, "add"),
    ]


@pytest.mark.conformance("COMP-044")
def test_COMP_044_transfer_into_group_publishes_old_remove_before_new_add() -> None:
    hub: MessageHub[Any] = MessageHub()
    old = _composite(hub, "old")
    new = _group(hub, "new")
    moved = _child(hub, "moved")
    old.add(moved)
    messages = _hub_messages(hub)

    new.add(moved)

    assert [(message.sender, message.action) for message in messages] == [
        (old, "remove"),
        (new, "add"),
    ]


@pytest.mark.conformance("COMP-044")
def test_COMP_044_rejected_rolled_back_and_same_index_mutations_publish_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    outer = _composite(hub, "outer")
    a = _child(hub, "a")
    parent.add(a)
    outer.add(parent)
    source = _composite(hub, "source")

    def fail_construct() -> None:
        raise RuntimeError("construct failed")

    failing = (
        ComponentVMBuilder()
        .name("failing")
        .services(hub, _DISPATCHER)
        .on_construct(fail_construct)
        .build()
    )
    source.add(failing)
    destination = _composite(hub, "destination", auto_construct=True)
    destination.construct()
    local_events: list[CollectionChangedEvent] = []
    for container in (parent, outer, source, destination):
        container.on_collection_changed.subscribe(local_events.append)
    messages = _hub_messages(hub)

    with pytest.raises(ValueError):
        parent.add(a)  # duplicate
    with pytest.raises(ValueError):
        parent.add(outer)  # cycle
    with pytest.raises(IndexError):
        parent.remove_at(99)
    with pytest.raises(IndexError):
        parent[99] = _child(hub, "late")
    with pytest.raises(IndexError):
        parent.move(0, 99)
    with pytest.raises(RuntimeError, match="construct failed"):
        destination.add(failing)  # transfer rolls back
    parent.move(0, 0)

    assert source.snapshot() == (failing,)
    assert destination.snapshot() == ()
    assert local_events == []
    assert messages == []


# ===========================================================================
# COMP-045 — Hub transactions, disposal, and forwarding
# ===========================================================================


@pytest.mark.conformance("COMP-045")
def test_COMP_045_hub_transaction_defers_messages_in_mutation_order() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    local_events: list[CollectionChangedEvent] = []
    parent.on_collection_changed.subscribe(local_events.append)
    messages = _hub_messages(hub)

    with hub.batch():
        parent.add(_child(hub, "a"))
        with hub.batch():
            parent.add(_child(hub, "b"))
        parent.move(1, 0)
        assert len(local_events) == 3
        assert messages == []

    assert [(m.action, m.old_index, m.new_index, _names(m.new_items)) for m in messages] == [
        ("add", -1, 0, ("a",)),
        ("add", -1, 1, ("b",)),
        ("move", 1, 0, ("b",)),
    ]


@pytest.mark.conformance("COMP-045")
def test_COMP_045_disposed_composite_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    parent.add(_child(hub, "a"))
    batch = parent.batch_update()
    parent.add(_child(hub, "b"))  # dirties the batch
    messages = _hub_messages(hub)

    parent.dispose()
    batch.dispose()
    with pytest.raises(RuntimeError):
        parent.add(_child(hub, "late"))
    with pytest.raises(RuntimeError):
        parent.move(0, 1)
    with pytest.raises(RuntimeError):
        parent.clear()

    assert [message for message in messages if message.sender is parent] == []


@pytest.mark.conformance("COMP-045")
def test_COMP_045_composite_disposed_by_a_local_subscriber_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    parent.add(_child(hub, "a"))
    parent.add(_child(hub, "b"))
    parent.on_collection_changed.subscribe(lambda _event: parent.dispose())
    messages = _hub_messages(hub)

    parent.move(0, 1)

    assert parent.status is ConstructionStatus.DISPOSED
    assert messages == []


@pytest.mark.conformance("COMP-045")
def test_COMP_045_forwarding_wrapper_publishes_once_as_the_wrapped_composite() -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = _composite(hub)
    wrapper: ForwardingCompositeVM[_ComponentVMBase] = ForwardingCompositeVM(parent)
    messages = _hub_messages(hub)

    wrapper.add(_child(hub, "a"))
    wrapper.insert(0, _child(hub, "b"))
    wrapper.remove_at(1)

    assert [(message.sender, message.action) for message in messages] == [
        (parent, "add"),
        (parent, "add"),
        (parent, "remove"),
    ]


# ===========================================================================
# GRP-012 — Group collection changes publish on the hub
# ===========================================================================


@pytest.mark.conformance("GRP-012")
def test_GRP_012_publishes_one_hub_message_after_each_local_event() -> None:
    hub: MessageHub[Any] = MessageHub()
    peers = _group(hub)
    a, b, c, d = (_child(hub, name) for name in "abcd")
    log = _interleaved(hub, peers)
    messages = _hub_messages(hub)

    peers.add(a)
    peers.insert(0, b)
    peers.move(0, 1)
    peers.move(1, 1)  # same-index: no local event, nothing published
    peers[0] = c
    assert peers.remove(b) is True
    assert peers.remove(b) is False  # absent: no local event, nothing published
    peers.remove_at(0)
    peers.add(d)
    peers.clear()

    _assert_hub_follows_each_local_event(log, 9)
    assert all(message.sender is peers for message in messages)
    assert [message.action for message in messages] == [
        "add",
        "add",
        "move",
        "remove",
        "add",
        "remove",
        "remove",
        "add",
        "reset",
    ]
    assert (messages[3].old_items, messages[4].new_items) == ((a,), (c,))


@pytest.mark.conformance("GRP-012")
def test_GRP_012_disposed_group_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    peers = _group(hub)
    peers.add(_child(hub, "a"))
    batch = peers.batch_update()
    peers.add(_child(hub, "b"))  # dirties the batch
    messages = _hub_messages(hub)

    peers.dispose()
    batch.dispose()
    with pytest.raises(RuntimeError):
        peers.add(_child(hub, "late"))
    with pytest.raises(RuntimeError):
        peers.remove_at(0)
    with pytest.raises(RuntimeError):
        peers.clear()

    assert messages == []


@pytest.mark.conformance("GRP-012")
def test_GRP_012_group_disposed_by_a_local_subscriber_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    peers = _group(hub)
    peers.add(_child(hub, "a"))
    peers.add(_child(hub, "b"))
    peers.on_collection_changed.subscribe(lambda _event: peers.dispose())
    messages = _hub_messages(hub)

    peers.move(0, 1)

    assert peers.status is ConstructionStatus.DISPOSED
    assert messages == []


# ===========================================================================
# GRP-013 — Group batches publish one hub Reset
# ===========================================================================


@pytest.mark.conformance("GRP-013")
def test_GRP_013_batch_publishes_one_reset_on_outermost_completion() -> None:
    hub: MessageHub[Any] = MessageHub()
    peers = _group(hub)
    log = _interleaved(hub, peers)

    peers.batch_update().dispose()
    with peers.batch_update():
        peers.add(_child(hub, "a"))
        inner = peers.batch_update()
        peers.add(_child(hub, "b"))
        inner.dispose()
        assert log == []

    assert log == [
        ("local:group", "reset", -1, -1, (), ()),
        ("hub:group", "reset", -1, -1, (), ()),
    ]


@pytest.mark.conformance("GRP-013")
def test_GRP_013_empty_or_same_index_move_batch_publishes_nothing() -> None:
    hub: MessageHub[Any] = MessageHub()
    peers = _group(hub)
    peers.add(_child(hub, "a"))
    messages = _hub_messages(hub)

    with peers.batch_update():
        pass
    with peers.batch_update():
        peers.move(0, 0)

    assert messages == []

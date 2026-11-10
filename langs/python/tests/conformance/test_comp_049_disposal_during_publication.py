"""Conformance tests: COMP-049.

A container whose disposal is requested during a change sends no hub message
for it, also when the disposal is deferred. The local event is still
delivered (spec ch. 01 §1.4, ch. 06 §4/§4.2/§4.3, ch. 07 §1, ADR-0190).
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.collections import CollectionChangedEvent
from vmx.components.base import _ComponentVMBase
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

_DISPATCHER = RxDispatcher.immediate()


def _child(hub: MessageHub[Any], name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, _DISPATCHER).build()


def _composite(hub: MessageHub[Any], name: str) -> CompositeVM[_ComponentVMBase]:
    return CompositeVMBuilder().name(name).services(hub, _DISPATCHER).children(lambda: ()).build()


def _group(hub: MessageHub[Any], name: str) -> GroupVM[_ComponentVMBase]:
    return GroupVMBuilder().name(name).services(hub, _DISPATCHER).children(lambda: ()).build()


def _hub_log(hub: MessageHub[Any], *containers: Any) -> list[tuple[str, str]]:
    log: list[tuple[str, str]] = []

    def record(message: object) -> None:
        if not isinstance(message, CollectionChangedMessage):
            return
        for container in containers:
            if message.sender is container:
                log.append((container.name, message.action))

    hub.messages.subscribe(record)
    return log


def _local_log(container: Any) -> list[str]:
    events: list[str] = []

    def record(event: CollectionChangedEvent) -> None:
        events.append(event.action)

    container.on_collection_changed.subscribe(record)
    return events


@pytest.mark.conformance("COMP-049")
def test_COMP_049_transfer_from_self_disposing_old_parent_publishes_only_new_add() -> None:
    hub: MessageHub[Any] = MessageHub()
    holder: list[CompositeVM[_ComponentVMBase]] = []

    def on_current_changed(value: _ComponentVMBase | None) -> None:
        if value is None:
            holder[0].dispose()

    old: CompositeVM[_ComponentVMBase] = (
        CompositeVMBuilder()
        .name("old")
        .services(hub, _DISPATCHER)
        .children(lambda: ())
        .on_current_changed(on_current_changed)
        .build()
    )
    holder.append(old)
    new = _composite(hub, "new")
    x = _child(hub, "x")
    old.add(x)
    old.current = x
    old_local = _local_log(old)
    messages = _hub_log(hub, old, new)

    new.add(x)

    assert messages == [("new", "add")]
    assert old.status is ConstructionStatus.DISPOSED
    assert old_local == ["remove"]
    assert new.snapshot() == (x,)


@pytest.mark.conformance("COMP-049")
@pytest.mark.parametrize("factory", [_composite, _group], ids=["composite", "group"])
def test_COMP_049_add_whose_local_subscriber_disposes_publishes_nothing(
    factory: Any,
) -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = factory(hub, "p")
    local = _local_log(parent)
    parent.on_collection_changed.subscribe(lambda _event: parent.dispose())
    messages = _hub_log(hub, parent)

    parent.add(_child(hub, "c"))

    assert local == ["add"]
    assert messages == []
    assert parent.status is ConstructionStatus.DISPOSED


@pytest.mark.conformance("COMP-049")
@pytest.mark.parametrize("factory", [_composite, _group], ids=["composite", "group"])
def test_COMP_049_move_whose_local_subscriber_disposes_publishes_nothing(
    factory: Any,
) -> None:
    hub: MessageHub[Any] = MessageHub()
    parent = factory(hub, "p")
    parent.add(_child(hub, "a"))
    parent.add(_child(hub, "b"))
    local = _local_log(parent)
    parent.on_collection_changed.subscribe(lambda _event: parent.dispose())
    messages = _hub_log(hub, parent)

    parent.move(0, 1)

    assert local == ["move"]
    assert messages == []
    assert parent.status is ConstructionStatus.DISPOSED

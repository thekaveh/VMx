"""A raising ``on_collection_changed`` subscriber does not stop the rest of a
committed change's publication (spec ch. 01 §1.4, #727).

Every local event and hub message of the change still goes out, and the first
failure re-raises, as the ``CompositeVM`` indexer already does.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from vmx.collections import CollectionChangedEvent
from vmx.components.base import _ComponentVMBase
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

_DISPATCHER = RxDispatcher.immediate()


class _SubscriberError(RuntimeError):
    pass


def _child(hub: MessageHub[Any], name: str) -> ComponentVM:
    return ComponentVMBuilder().name(name).services(hub, _DISPATCHER).build()


def _group(hub: MessageHub[Any], name: str, *children: ComponentVM) -> GroupVM[_ComponentVMBase]:
    return GroupVMBuilder().name(name).services(hub, _DISPATCHER).children(lambda: children).build()


def _record(
    hub: MessageHub[Any], container: object, *, raising: bool
) -> tuple[list[str], list[str]]:
    local: list[str] = []
    remote: list[str] = []

    def on_local(event: CollectionChangedEvent) -> None:
        local.append(event.action)
        if raising:
            raise _SubscriberError(f"{getattr(container, 'name', '?')} subscriber")

    def on_hub(message: object) -> None:
        if isinstance(message, CollectionChangedMessage) and message.sender is container:
            remote.append(message.action)

    container.on_collection_changed.subscribe(on_local)  # type: ignore[attr-defined]
    hub.messages.subscribe(on_hub)
    return local, remote


def test_group_indexer_publishes_remove_and_add_after_a_raising_subscriber() -> None:
    hub: MessageHub[Any] = MessageHub()
    group = _group(hub, "group", _child(hub, "a"), _child(hub, "b"))
    group.construct()
    local, remote = _record(hub, group, raising=True)

    with pytest.raises(_SubscriberError):
        group[0] = _child(hub, "d")

    assert local == ["remove", "add"]
    assert remote == ["remove", "add"]


_Builder = Callable[[MessageHub[Any], tuple[ComponentVM, ...]], Any]

_POPULATED: list[tuple[str, _Builder]] = [
    (
        "GroupVM",
        lambda hub, kids: (
            GroupVMBuilder().name("p").services(hub, _DISPATCHER).children(lambda: kids).build()
        ),
    ),
    (
        "CompositeVM",
        lambda hub, kids: (
            CompositeVMBuilder().name("p").services(hub, _DISPATCHER).children(lambda: kids).build()
        ),
    ),
    (
        "CompositeVMOf",
        lambda hub, kids: (
            CompositeVMOfBuilder()
            .name("p")
            .services(hub, _DISPATCHER)
            .children_models(lambda: [kid.name for kid in kids])
            .child_model_to_child_view_model(lambda name: _child(hub, name))
            .build()
        ),
    ),
]


@pytest.mark.parametrize(("kind", "build"), _POPULATED, ids=[kind for kind, _ in _POPULATED])
def test_population_publishes_every_add_after_a_raising_subscriber(
    kind: str, build: _Builder
) -> None:
    hub: MessageHub[Any] = MessageHub()
    container = build(hub, tuple(_child(hub, name) for name in ("x", "y", "z")))
    local, remote = _record(hub, container, raising=True)

    with pytest.raises(_SubscriberError):
        container.construct()

    assert local == ["add", "add", "add"], kind
    assert remote == ["add", "add", "add"], kind


def test_transfer_commit_error_reraises_after_every_publication_step() -> None:
    hub: MessageHub[Any] = MessageHub()
    moving = _child(hub, "moving")
    old_parent = _group(hub, "old", moving)
    old_parent.construct()
    destination = _group(hub, "destination", _child(hub, "kept"))
    destination.construct()
    _record(hub, old_parent, raising=True)  # its removal publication fails the commit
    local, remote = _record(hub, destination, raising=True)

    with pytest.raises(_SubscriberError, match="old subscriber"):
        destination[0] = moving

    assert local == ["remove", "add"]
    assert remote == ["remove", "add"]

"""VMX-017 regression — when_property_changed typed hub helper.

Replaces the hand-wired ``ops.filter(lambda m: isinstance(m, PropertyChangedMessage)
and m.sender is x and m.property_name == "p")`` filter repeated across cross-VM
bindings; emits the matching message (not the value). The several-name form
(ADR-0160) is covered below the single-name tests.
"""

from __future__ import annotations

from typing import Any

import pytest
import reactivex
from reactivex import Observable
from reactivex.abc import DisposableBase
from reactivex.subject import Subject

from vmx.messages import PropertyChangedMessage, when_property_changed
from vmx.services.message_hub import MessageHub


def test_filters_by_sender_identity_and_property_name() -> None:
    hub: MessageHub[object] = MessageHub()
    sender_a = object()
    sender_b = object()

    received: list[str] = []
    sub = when_property_changed(hub, sender_a, "foo").subscribe(
        on_next=lambda m: received.append(m.property_name)
    )

    hub.send(PropertyChangedMessage.create(sender_a, "A", "foo"))  # match
    hub.send(PropertyChangedMessage.create(sender_a, "A", "bar"))  # wrong property
    hub.send(PropertyChangedMessage.create(sender_b, "B", "foo"))  # wrong sender

    sub.dispose()
    assert received == ["foo"]


def test_emits_the_matching_message() -> None:
    hub: MessageHub[object] = MessageHub()
    sender = object()

    captured: list[PropertyChangedMessage[object]] = []
    sub = when_property_changed(hub, sender, "p").subscribe(on_next=captured.append)

    hub.send(PropertyChangedMessage.create(sender, "S", "p"))
    sub.dispose()

    assert len(captured) == 1
    assert captured[0].sender is sender
    assert captured[0].property_name == "p"


def test_several_names_emit_matching_messages_in_hub_order() -> None:
    hub: MessageHub[object] = MessageHub()
    sender_a = object()
    sender_b = object()

    received: list[str] = []
    sub = when_property_changed(hub, sender_a, "foo", "bar").subscribe(
        on_next=lambda m: received.append(m.property_name)
    )

    hub.send(PropertyChangedMessage.create(sender_a, "A", "bar"))  # match
    hub.send(PropertyChangedMessage.create(sender_a, "A", "baz"))  # name not listed
    hub.send(PropertyChangedMessage.create(sender_b, "B", "foo"))  # wrong sender
    hub.send(PropertyChangedMessage.create(sender_a, "A", "foo"))  # match
    hub.send(PropertyChangedMessage.create(sender_a, "A", "Foo"))  # exact match only
    hub.send(PropertyChangedMessage.create(sender_a, "A", "bar"))  # match

    sub.dispose()
    assert received == ["bar", "foo", "bar"]


def test_several_names_accept_an_unpacked_sequence() -> None:
    hub: MessageHub[object] = MessageHub()
    sender = object()
    names = ["foo", "bar"]

    received: list[str] = []
    sub = when_property_changed(hub, sender, *names).subscribe(
        on_next=lambda m: received.append(m.property_name)
    )
    names[1] = "baz"  # the helper keeps the names it was called with

    hub.send(PropertyChangedMessage.create(sender, "S", "bar"))
    hub.send(PropertyChangedMessage.create(sender, "S", "baz"))

    sub.dispose()
    assert received == ["bar"]


def test_repeated_name_emits_each_message_once() -> None:
    hub: MessageHub[object] = MessageHub()
    sender = object()

    received: list[str] = []
    sub = when_property_changed(hub, sender, "foo", "foo", "bar").subscribe(
        on_next=lambda m: received.append(m.property_name)
    )

    hub.send(PropertyChangedMessage.create(sender, "S", "foo"))

    sub.dispose()
    assert received == ["foo"]


class _CountingHub:
    """Hub stand-in that counts subscriptions to ``messages``."""

    def __init__(self) -> None:
        self.subject: Subject[Any] = Subject()
        self.subscriptions = 0

        def _subscribe(observer: Any, scheduler: Any = None) -> DisposableBase:
            self.subscriptions += 1
            return self.subject.subscribe(observer, scheduler=scheduler)

        self.messages: Observable[Any] = reactivex.create(_subscribe)


def test_several_names_use_one_hub_subscription() -> None:
    hub = _CountingHub()
    sender = object()

    received: list[str] = []
    sub = when_property_changed(hub, sender, "foo", "bar").subscribe(
        on_next=lambda m: received.append(m.property_name)
    )
    assert hub.subscriptions == 1

    hub.subject.on_next(PropertyChangedMessage.create(sender, "S", "foo"))
    sub.dispose()
    hub.subject.on_next(PropertyChangedMessage.create(sender, "S", "bar"))

    assert received == ["foo"]
    assert not hub.subject.observers


def test_a_call_without_names_raises_type_error() -> None:
    hub: MessageHub[object] = MessageHub()
    no_names: list[str] = []

    with pytest.raises(TypeError):
        when_property_changed(hub, object(), *no_names)

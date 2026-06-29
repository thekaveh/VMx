"""VMX-017 regression — when_property_changed typed hub helper.

Replaces the hand-wired ``ops.filter(lambda m: isinstance(m, PropertyChangedMessage)
and m.sender is x and m.property_name == "p")`` filter repeated across cross-VM
bindings; emits the matching message (not the value).
"""

from __future__ import annotations

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

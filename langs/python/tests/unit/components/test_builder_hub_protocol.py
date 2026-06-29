"""VMX-015 regression — builders accept any ``MessageHubProto`` implementation.

The component builders (and the underlying ``_ComponentVMBase``) used to type the
``hub`` parameter as the *concrete* ``MessageHub`` class, which defeated the
advertised extension point ``MessageHubProto`` and forced ``# type: ignore`` at the
``with_null_services`` call sites.  This test wires a *structural* hub — one that
satisfies the protocol without subclassing ``MessageHub`` — through ``services()``
and verifies the VM publishes to it, proving the protocol is honoured at runtime
(the ``mypy --strict`` gate proves it at type-check time).
"""

from __future__ import annotations

import reactivex as rx
from reactivex.subject import Subject

from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder
from vmx.messages.protocols import Message
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHubProto


class _RecordingHub:
    """Minimal structural ``MessageHubProto`` — NOT a ``MessageHub`` subclass."""

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()
        self.sent: list[Message] = []

    @property
    def messages(self) -> rx.Observable[Message]:
        return self._subject

    def send(self, message: Message) -> None:
        self.sent.append(message)
        self._subject.on_next(message)


def test_component_builder_accepts_hub_protocol() -> None:
    # Bind the structural hub to the protocol-typed name: if ``services`` still
    # demanded the concrete class this would be a type error under mypy --strict.
    recording = _RecordingHub()
    hub: MessageHubProto[Message] = recording

    vm = ComponentVMBuilder().name("leaf").services(hub, RxDispatcher.immediate()).build()
    vm.construct()

    # The protocol hub received the lifecycle status messages — proof the VM
    # published through the injected protocol implementation, not a concrete one.
    assert len(recording.sent) > 0
    vm.dispose()


def test_modeled_component_builder_accepts_hub_protocol() -> None:
    recording = _RecordingHub()
    hub: MessageHubProto[Message] = recording

    vm = (
        ComponentVMOfBuilder()
        .name("modeled")
        .model("hello")
        .services(hub, RxDispatcher.immediate())
        .build()
    )
    vm.construct()

    assert len(recording.sent) > 0
    vm.dispose()

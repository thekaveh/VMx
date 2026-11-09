"""Decorator notification helpers act on the wrapped VM (#1352).

A forwarding decorator's dual-channel helper publishes one hub message whose
sender is the wrapped VM, and the decorator's ``property_changed`` emits the
name once. The local-only helper emits on ``property_changed`` and sends no hub
message. After the wrapped VM is disposed, the helpers do nothing. Per
spec/09-forwarding.md §1.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.components.base import _ComponentVMBase
from vmx.components.builders import ComponentVMOfBuilder
from vmx.composites.builders import CompositeVMBuilder
from vmx.forwarding.component import ForwardingComponentVM
from vmx.forwarding.composite import ForwardingCompositeVM
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class _NotifyingComponent(ForwardingComponentVM[str]):
    def notify(self, name: str) -> None:
        self._notify_property_changed(name)

    def raise_local(self, name: str) -> None:
        self._raise_property_changed(name)


class _NotifyingComposite(ForwardingCompositeVM[Any]):
    def notify(self, name: str) -> None:
        self._notify_property_changed(name)

    def raise_local(self, name: str) -> None:
        self._raise_property_changed(name)


def _component(hub: MessageHub[Any]) -> tuple[_ComponentVMBase, Any]:
    inner = (
        ComponentVMOfBuilder[str]()
        .name("inner")
        .model("m")
        .services(hub, RxDispatcher.immediate())
        .build()
    )
    return inner, _NotifyingComponent(inner)


def _composite(hub: MessageHub[Any]) -> tuple[_ComponentVMBase, Any]:
    inner = (
        CompositeVMBuilder[Any]()
        .name("inner")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: ())
        .build()
    )
    return inner, _NotifyingComposite(inner)


@pytest.mark.parametrize("factory", [_component, _composite], ids=["component", "composite"])
def test_decorator_helpers_publish_through_the_wrapped_vm(factory: Any) -> None:
    hub: MessageHub[Any] = MessageHub()
    inner, decorator = factory(hub)
    messages: list[PropertyChangedMessage[Any]] = []
    hub.messages.subscribe(
        lambda m: messages.append(m) if isinstance(m, PropertyChangedMessage) else None
    )
    names: list[str] = []
    decorator.property_changed.subscribe(names.append)

    decorator.notify("custom")

    assert names == ["custom"]
    assert len(messages) == 1
    assert messages[0].sender is inner
    assert messages[0].property_name == "custom"

    decorator.raise_local("local")

    assert names == ["custom", "local"]
    assert len(messages) == 1

    inner.dispose()
    names.clear()
    messages.clear()
    decorator.notify("after")
    decorator.raise_local("after")

    assert names == []
    assert messages == []

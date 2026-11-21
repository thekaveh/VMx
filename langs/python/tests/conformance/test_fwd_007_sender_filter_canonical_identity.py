"""FWD-007 — sender-filter helpers match a decorator by its canonical identity.

The chapter 03 §7 hub helpers keep the messages whose sender is the VM they are
given. A forwarding decorator causes no message of its own: the wrapped VM sends
each one (ADR-0221), and nested decorators resolve to the same innermost VM
(ADR-0124). A helper given a decorator, through any number of layers, therefore
matches the wrapped VM's messages. Per spec/03-messages.md §7.1, §7.2 and §7.4,
spec/09-forwarding.md §1 and ADR-0233.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from vmx import ComponentVMOf, Message, MessageHub, RxDispatcher, subscribe_value
from vmx.forwarding.component import ForwardingComponentVM
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.property_value_changed import property_value_changed_messages_for
from vmx.messages.when_property_changed import when_property_changed


@dataclass(frozen=True, slots=True)
class _Model:
    value: int


def _make_vm(hub: MessageHub[Message], name: str) -> ComponentVMOf[_Model]:
    return ComponentVMOf[_Model].create(
        name=name,
        model=_Model(0),
        hub=hub,
        dispatcher=RxDispatcher.immediate(),
    )


def _stack(hub: MessageHub[Message], layers: int) -> tuple[Any, Any]:
    """Return ``(inner, given)`` where *given* wraps *inner* in *layers* decorators."""
    inner = _make_vm(hub, "inner")
    given: Any = inner
    for _ in range(layers):
        given = ForwardingComponentVM(given)
    return inner, given


@pytest.mark.conformance("FWD-007")
@pytest.mark.parametrize("layers", [0, 1, 2], ids=["plain", "one_layer", "two_layers"])
def test_helpers_given_a_decorator_match_the_wrapped_vm_writes(layers: int) -> None:
    hub: MessageHub[Message] = MessageHub()
    inner, given = _stack(hub, layers)
    messages: list[PropertyChangedMessage[Any]] = []
    values: list[Any] = []
    selected: list[tuple[int, int]] = []
    when_sub = when_property_changed(hub, given, "model").subscribe(messages.append)
    value_sub = property_value_changed_messages_for(hub, given, "model").subscribe(values.append)
    select_sub = subscribe_value(
        given,
        lambda vm: vm.model.value,
        lambda current, previous: selected.append((current, previous)),
    )

    given.model = _Model(1)

    assert len(messages) == 1
    assert messages[0].sender is inner
    assert values == [_Model(1)]
    assert selected == [(1, 0)]

    when_sub.dispose()
    value_sub.dispose()
    select_sub.dispose()


@pytest.mark.conformance("FWD-007")
def test_helpers_given_a_two_layer_decorator_ignore_other_vms_on_the_hub() -> None:
    hub: MessageHub[Message] = MessageHub()
    _inner, given = _stack(hub, 2)
    other = _make_vm(hub, "other")
    messages: list[PropertyChangedMessage[Any]] = []
    values: list[Any] = []
    selected: list[tuple[int, int]] = []
    when_sub = when_property_changed(hub, given, "model").subscribe(messages.append)
    value_sub = property_value_changed_messages_for(hub, given, "model").subscribe(values.append)
    select_sub = subscribe_value(
        given,
        lambda vm: vm.model.value,
        lambda current, previous: selected.append((current, previous)),
    )

    other.model = _Model(9)

    assert messages == []
    assert values == []
    assert selected == []

    when_sub.dispose()
    value_sub.dispose()
    select_sub.dispose()

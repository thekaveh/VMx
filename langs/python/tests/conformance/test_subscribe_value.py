"""Conformance tests for the imperative selected-state bridge."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pytest
from reactivex.abc import DisposableBase

from vmx import (
    ComponentVMOf,
    ConstructionStatusChangedMessage,
    Message,
    MessageHub,
    RxDispatcher,
    subscribe_value,
)


@dataclass(frozen=True, slots=True)
class _Model:
    value: float


def _make_vm(hub: MessageHub[Message], name: str, value: float) -> ComponentVMOf[_Model]:
    return ComponentVMOf[_Model].create(
        name=name,
        model=_Model(value),
        hub=hub,
        dispatcher=RxDispatcher.immediate(),
    )


@pytest.mark.conformance("SUBV-001")
def test_SUBV_001_fixed_source_default_equality_and_immediate() -> None:
    hub: MessageHub[Message] = MessageHub()
    vm = _make_vm(hub, "source", 0)
    other = _make_vm(hub, "other", 0)
    seen: list[tuple[float, float]] = []
    selector_calls = 0

    def select(source: ComponentVMOf[_Model]) -> float:
        nonlocal selector_calls
        selector_calls += 1
        return source.model.value

    sub = subscribe_value(
        vm,
        select,
        lambda current, previous: seen.append((current, previous)),
        fire_immediately=True,
    )

    assert seen == [(0, 0)]
    assert selector_calls == 1

    other.republish_model()
    hub.send(ConstructionStatusChangedMessage.create(vm, vm.name, vm.status))
    assert selector_calls == 1

    vm.republish_model()
    assert selector_calls == 2
    assert seen == [(0, 0)]

    vm.model = _Model(1)
    vm.model = _Model(2)
    assert selector_calls == 4
    assert seen == [(0, 0), (1, 0), (2, 1)]

    sub.dispose()


@pytest.mark.conformance("SUBV-002")
def test_SUBV_002_custom_equality_and_single_evaluation() -> None:
    hub: MessageHub[Message] = MessageHub()
    vm = _make_vm(hub, "source", 1.1)
    seen: list[tuple[float, float]] = []
    comparisons: list[tuple[float, float]] = []
    selector_calls = 0

    def select(source: ComponentVMOf[_Model]) -> float:
        nonlocal selector_calls
        selector_calls += 1
        return source.model.value

    def equal(current: float, next_value: float) -> bool:
        comparisons.append((current, next_value))
        return math.floor(current) == math.floor(next_value)

    sub = subscribe_value(
        vm,
        select,
        lambda current, previous: seen.append((current, previous)),
        equality=equal,
    )

    vm.model = _Model(1.9)
    vm.republish_model()
    vm.model = _Model(2.1)

    assert selector_calls == 4
    assert comparisons == [(1.1, 1.9), (1.1, 1.9), (1.1, 2.1)]
    assert seen == [(2.1, 1.1)]

    sub.dispose()


@pytest.mark.conformance("SUBV-003")
def test_SUBV_003_reentrant_batch_and_disposal_behavior() -> None:
    hub: MessageHub[Message] = MessageHub()
    vm = _make_vm(hub, "source", 0)
    seen: list[tuple[float, float]] = []

    def callback(current: float, previous: float) -> None:
        seen.append((current, previous))
        if current == 1:
            vm.model = _Model(2)

    sub = subscribe_value(vm, lambda source: source.model.value, callback)

    vm.model = _Model(1)
    assert seen == [(1, 0), (2, 1)]

    with hub.batch():
        vm.model = _Model(3)
        vm.model = _Model(4)
    assert seen == [(1, 0), (2, 1), (4, 2)]

    sub.dispose()
    vm.model = _Model(5)
    assert seen == [(1, 0), (2, 1), (4, 2)]

    callback_vm = _make_vm(hub, "callback-source", 0)
    callback_seen: list[tuple[float, float]] = []
    selector_calls = 0
    callback_sub: DisposableBase | None = None

    def callback_select(source: ComponentVMOf[_Model]) -> float:
        nonlocal selector_calls
        selector_calls += 1
        return source.model.value

    def dispose_during_callback(current: float, previous: float) -> None:
        callback_seen.append((current, previous))
        assert callback_sub is not None
        callback_sub.dispose()
        callback_vm.model = _Model(2)

    callback_sub = subscribe_value(callback_vm, callback_select, dispose_during_callback)
    callback_vm.model = _Model(1)
    callback_vm.model = _Model(3)

    assert callback_seen == [(1, 0)]
    assert selector_calls == 2


@pytest.mark.conformance("SUBV-004")
def test_SUBV_004_setup_and_delivery_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hub: MessageHub[Message] = MessageHub()
    selector_vm = _make_vm(hub, "selector-source", 0)
    failed_selector_calls = 0

    def fail_initial_selector(_source: ComponentVMOf[_Model]) -> float:
        nonlocal failed_selector_calls
        failed_selector_calls += 1
        raise RuntimeError("initial selector failed")

    with pytest.raises(RuntimeError, match="initial selector failed"):
        subscribe_value(selector_vm, fail_initial_selector, lambda _current, _previous: None)
    selector_vm.republish_model()
    assert failed_selector_calls == 1

    immediate_vm = _make_vm(hub, "immediate-source", 0)
    immediate_selector_calls = 0

    def select_immediate(source: ComponentVMOf[_Model]) -> float:
        nonlocal immediate_selector_calls
        immediate_selector_calls += 1
        return source.model.value

    def fail_immediate_callback(_current: float, _previous: float) -> None:
        raise RuntimeError("immediate callback failed")

    with pytest.raises(RuntimeError, match="immediate callback failed"):
        subscribe_value(
            immediate_vm,
            select_immediate,
            fail_immediate_callback,
            fire_immediately=True,
        )
    immediate_vm.republish_model()
    assert immediate_selector_calls == 1

    delivery_vm = _make_vm(hub, "delivery-source", 0)
    seen: list[tuple[float, float]] = []
    healthy_deliveries = 0

    def healthy_subscriber(_message: Message) -> None:
        nonlocal healthy_deliveries
        healthy_deliveries += 1

    hub.messages.subscribe(healthy_subscriber)

    def delivery_callback(current: float, previous: float) -> None:
        seen.append((current, previous))
        if current == 1:
            raise RuntimeError("delivery callback failed")

    caplog.set_level(logging.ERROR, logger="vmx.services.message_hub")
    sub = subscribe_value(
        delivery_vm,
        lambda source: source.model.value,
        delivery_callback,
    )

    delivery_vm.model = _Model(1)
    delivery_vm.model = _Model(2)

    assert seen == [(1, 0), (2, 1)]
    assert healthy_deliveries == 2
    assert "MessageHub subscriber raised" in caplog.text

    sub.dispose()

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

    class FalseyEquality:
        def __bool__(self) -> bool:
            return False

        def __call__(self, current: float, next_value: float) -> bool:
            comparisons.append((current, next_value))
            return math.floor(current) == math.floor(next_value)

    sub = subscribe_value(
        vm,
        select,
        lambda current, previous: seen.append((current, previous)),
        equality=FalseyEquality(),
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

    selector_delivery_vm = _make_vm(hub, "selector-delivery-source", 0)
    selector_seen: list[tuple[float, float]] = []
    selector_calls = 0
    selector_equality_calls = 0
    selector_healthy_deliveries = 0
    fail_next_selector = False

    def selector_delivery(source: ComponentVMOf[_Model]) -> float:
        nonlocal fail_next_selector, selector_calls
        selector_calls += 1
        if fail_next_selector:
            fail_next_selector = False
            raise RuntimeError("delivery selector failed")
        return source.model.value

    def selector_equality(current: float, next_value: float) -> bool:
        nonlocal selector_equality_calls
        selector_equality_calls += 1
        return current == next_value

    def selector_healthy_subscriber(message: Message) -> None:
        nonlocal selector_healthy_deliveries
        if getattr(message, "sender", None) is selector_delivery_vm:
            selector_healthy_deliveries += 1

    selector_healthy_sub = hub.messages.subscribe(selector_healthy_subscriber)
    selector_sub = subscribe_value(
        selector_delivery_vm,
        selector_delivery,
        lambda current, previous: selector_seen.append((current, previous)),
        equality=selector_equality,
    )

    fail_next_selector = True
    selector_delivery_vm.model = _Model(1)
    selector_delivery_vm.model = _Model(2)

    assert selector_calls == 3
    assert selector_equality_calls == 1
    assert selector_seen == [(2, 0)]
    assert selector_healthy_deliveries == 2

    selector_sub.dispose()
    selector_healthy_sub.dispose()

    equality_delivery_vm = _make_vm(hub, "equality-delivery-source", 0)
    equality_seen: list[tuple[float, float]] = []
    equality_selector_calls = 0
    equality_calls = 0
    equality_healthy_deliveries = 0

    def equality_selector(source: ComponentVMOf[_Model]) -> float:
        nonlocal equality_selector_calls
        equality_selector_calls += 1
        return source.model.value

    def fail_first_equality(current: float, next_value: float) -> bool:
        nonlocal equality_calls
        equality_calls += 1
        if equality_calls == 1:
            raise RuntimeError("delivery equality failed")
        return current == next_value

    def equality_healthy_subscriber(message: Message) -> None:
        nonlocal equality_healthy_deliveries
        if getattr(message, "sender", None) is equality_delivery_vm:
            equality_healthy_deliveries += 1

    equality_healthy_sub = hub.messages.subscribe(equality_healthy_subscriber)
    equality_sub = subscribe_value(
        equality_delivery_vm,
        equality_selector,
        lambda current, previous: equality_seen.append((current, previous)),
        equality=fail_first_equality,
    )

    equality_delivery_vm.model = _Model(1)
    equality_delivery_vm.model = _Model(2)

    assert equality_selector_calls == 3
    assert equality_calls == 2
    assert equality_seen == [(2, 0)]
    assert equality_healthy_deliveries == 2

    equality_sub.dispose()
    equality_healthy_sub.dispose()

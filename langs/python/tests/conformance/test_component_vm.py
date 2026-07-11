"""Conformance tests: CVM-001..010.

The LIFE-001..010, 012 and PROP-001..004 ids each own a single self-contained
test in test_lifecycle.py / test_property_change.py respectively; this file no
longer hosts duplicate (double-counted) copies of them (VMX-055).
"""

from __future__ import annotations

import pytest

from vmx.components.base import _ComponentVMBase
from vmx.components.builders import (
    ComponentVMBuilder,
    ComponentVMOfBuilder,
    ReadonlyComponentVMOfBuilder,
)
from vmx.components.protocols import ViewModelType
from vmx.forwarding.component import ForwardingComponentVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _build_vm(name: str = "vm1") -> tuple[object, MessageHub[object]]:
    """Return (ComponentVM, hub)."""
    hub = _hub()
    dispatcher = _dispatcher()
    vm = ComponentVMBuilder().name(name).services(hub, dispatcher).build()
    return vm, hub


def _build_vm_of(
    name: str = "vm1",
    model: object = "m1",
) -> tuple[object, MessageHub[object]]:
    """Return (ComponentVMOf, hub)."""
    hub = _hub()
    dispatcher = _dispatcher()
    vm = ComponentVMOfBuilder().name(name).model(model).services(hub, dispatcher).build()
    return vm, hub


def _status_messages(hub: MessageHub[object]) -> list[ConstructionStatusChangedMessage]:
    """Subscribe and return a list that accumulates ConstructionStatusChangedMessages."""
    collected: list[ConstructionStatusChangedMessage] = []
    hub.messages.subscribe(
        lambda m: collected.append(m) if isinstance(m, ConstructionStatusChangedMessage) else None
    )
    return collected


def _prop_messages(hub: MessageHub[object]) -> list[PropertyChangedMessage]:
    """Subscribe and return a list that accumulates PropertyChangedMessages."""
    collected: list[PropertyChangedMessage] = []
    hub.messages.subscribe(
        lambda m: collected.append(m) if isinstance(m, PropertyChangedMessage) else None
    )
    return collected


# ===========================================================================
# CVM-001 — Construct emits ConstructionStatusChangedMessage(Constructed)
# ===========================================================================


@pytest.mark.conformance("CVM-001")
def test_CVM_001_construct_emits_status_messages() -> None:
    """CVM-001: construct() emits exactly Constructing then Constructed messages."""
    vm, hub = _build_vm()
    msgs = _status_messages(hub)
    vm.construct()

    statuses = [m.status for m in msgs]
    # Spec LIFE-001: subscriber observes exactly TWO messages in order.
    assert statuses == [
        ConstructionStatus.CONSTRUCTING,
        ConstructionStatus.CONSTRUCTED,
    ], f"Expected exactly [Constructing, Constructed]; got {statuses}"
    assert vm.is_constructed is True


# ===========================================================================
# CVM-002 — Modeled component fires PropertyChanged("Model") on set
# ===========================================================================


@pytest.mark.conformance("CVM-002")
def test_CVM_002_modeled_component_fires_property_changed_on_set() -> None:
    """CVM-002: setting model to a different value emits PropertyChangedMessage('model')."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"

    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1
    assert model_msgs[0].sender is vm
    assert model_msgs[0].property_name == "model"


# ===========================================================================
# CVM-003 — ReadonlyComponentVM has no Model setter
# ===========================================================================


@pytest.mark.conformance("CVM-003")
def test_CVM_003_readonly_has_no_model_setter() -> None:
    """CVM-003: ReadonlyComponentVMOf exposes no public model setter."""
    from vmx.components.builders import ReadonlyComponentVMOfBuilder

    hub = _hub()
    dispatcher = _dispatcher()

    vm = ReadonlyComponentVMOfBuilder().name("ro-vm").model("m1").services(hub, dispatcher).build()

    # Verify value is correct.
    assert vm.model == "m1"

    # Verify there is no setter on the property descriptor.
    prop = type(vm).__dict__.get("model")
    assert prop is not None
    assert prop.fset is None, "ReadonlyComponentVMOf.model must NOT have a setter"


# ===========================================================================
# CVM-004 — ModeledHint recomputes when Model changes
# ===========================================================================


@pytest.mark.conformance("CVM-004")
def test_CVM_004_modeled_hint_recomputes_on_model_change() -> None:
    """CVM-004: modeled_hint is recomputed when model changes, emitting a message."""

    class _M:
        def __init__(self, id_: int) -> None:
            self.id = id_

    hub = _hub()
    dispatcher = _dispatcher()
    m1 = _M(7)
    m2 = _M(8)
    vm = (
        ComponentVMOfBuilder()
        .name("v")
        .model(m1)
        .services(hub, dispatcher)
        .modeled_hinter(lambda m: f"hint:{m.id}")
        .build()
    )

    msgs = _prop_messages(hub)
    vm.model = m2

    assert vm.modeled_hint == "hint:8"
    hint_msgs = [m for m in msgs if m.property_name == "modeled_hint"]
    assert len(hint_msgs) == 1, "Expected one PropertyChangedMessage('modeled_hint')"


# ===========================================================================
# CVM-005 — Name and Hint are immutable post-construction
# ===========================================================================


@pytest.mark.conformance("CVM-005")
def test_CVM_005_name_and_hint_immutable() -> None:
    """CVM-005: name and hint have no public setter; values are stable."""
    vm, _ = _build_vm(name="orig")

    # Verify readable values.
    assert vm.name == "orig"
    assert vm.hint == ""

    # Verify no setter on the property descriptors.
    name_prop = type(vm).__dict__.get("name")
    hint_prop = type(vm).__dict__.get("hint")
    # Properties inherited from base — walk MRO.
    if name_prop is None:
        for cls in type(vm).__mro__:
            if "name" in cls.__dict__:
                name_prop = cls.__dict__["name"]
                break
    if hint_prop is None:
        for cls in type(vm).__mro__:
            if "hint" in cls.__dict__:
                hint_prop = cls.__dict__["hint"]
                break
    assert name_prop is not None
    assert hint_prop is not None
    assert getattr(name_prop, "fset", None) is None, "name must NOT have a setter"
    assert getattr(hint_prop, "fset", None) is None, "hint must NOT have a setter"


# ===========================================================================
# CVM-006 — SelectCommand can_execute reflects selection state
# ===========================================================================


@pytest.mark.conformance("CVM-006")
def test_CVM_006_select_command_predicate() -> None:
    """CVM-006: SelectCommand.can_execute() reflects current/parent state."""

    # Build a minimal parent stub. Represents a selection-supporting composite
    # (groups, which do not support child selection, set this False — VMX-077).
    class _FakeParent:
        supports_child_selection = True

        def __init__(self) -> None:
            self.current_child: object | None = None

        def select_child(self, vm: object) -> None:
            self.current_child = vm

        def deselect_child(self, vm: object) -> None:
            if self.current_child is vm:
                self.current_child = None

    vm, _ = _build_vm()
    parent = _FakeParent()
    vm._parent = parent
    vm.construct()

    # With parent set and no current: can_select should be True.
    assert vm.can_select() is True
    assert vm.select_command.can_execute() is True

    # After select: can_select should be False.
    vm.select()
    assert parent.current_child is vm
    assert vm.can_select() is False
    assert vm.select_command.can_execute() is False


class _NotificationProbeVM(_ComponentVMBase):
    def __init__(self, hub: MessageHub[object]) -> None:
        super().__init__(name="probe", hint="", hub=hub, dispatcher=_dispatcher())
        self._value = 0

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, value: int) -> None:
        if self._value == value:
            return
        self._value = value
        self._notify_property_changed("value")

    def emit_value_notification(self) -> None:
        self._notify_property_changed("value")


@pytest.mark.conformance("CVM-007")
def test_CVM_007_notification_helper_emits_hub_then_local_once() -> None:
    hub = _hub()
    vm = _NotificationProbeVM(hub)
    trace: list[str] = []
    hub.messages.subscribe(
        lambda message: (
            trace.append(f"hub:{vm.value}")
            if isinstance(message, PropertyChangedMessage) and message.property_name == "value"
            else None
        )
    )
    vm.property_changed.subscribe(lambda name: trace.append(f"local:{name}:{vm.value}"))

    vm.value = 7

    assert trace == ["hub:7", "local:value:7"]


@pytest.mark.conformance("CVM-007")
def test_CVM_007_deferred_delivery_and_reentrant_disposal_complete_pair() -> None:
    batched_hub = _hub()
    batched_vm = _NotificationProbeVM(batched_hub)
    batched_trace: list[str] = []
    batched_hub.messages.subscribe(
        lambda message: (
            batched_trace.append("hub")
            if isinstance(message, PropertyChangedMessage) and message.property_name == "value"
            else None
        )
    )
    batched_vm.property_changed.subscribe(
        lambda name: batched_trace.append("local") if name == "value" else None
    )

    with batched_hub.batch():
        batched_vm.value = 7

    assert batched_trace == ["local", "hub"]

    disposing_hub = _hub()
    disposing_vm = _NotificationProbeVM(disposing_hub)
    disposing_trace: list[str] = []

    def dispose_from_hub(message: object) -> None:
        if isinstance(message, PropertyChangedMessage) and message.property_name == "value":
            disposing_trace.append("hub")
            disposing_vm.dispose()

    disposing_hub.messages.subscribe(dispose_from_hub)
    disposing_vm.property_changed.subscribe(
        lambda name: disposing_trace.append("local") if name == "value" else None
    )

    disposing_vm.value = 7

    assert disposing_trace == ["hub", "local"]


@pytest.mark.conformance("CVM-008")
def test_CVM_008_equality_guard_suppresses_both_channels() -> None:
    hub = _hub()
    vm = _NotificationProbeVM(hub)
    hub_names: list[str] = []
    local_names: list[str] = []
    hub.messages.subscribe(
        lambda message: (
            hub_names.append(message.property_name)
            if isinstance(message, PropertyChangedMessage)
            else None
        )
    )
    vm.property_changed.subscribe(local_names.append)

    vm.value = 7
    vm.value = 7

    assert hub_names == ["value"]
    assert local_names == ["value"]


@pytest.mark.conformance("CVM-009")
def test_CVM_009_notification_helper_is_inert_after_disposal() -> None:
    hub = _hub()
    vm = _NotificationProbeVM(hub)
    hub_names: list[str] = []
    local_names: list[str] = []
    hub.messages.subscribe(
        lambda message: (
            hub_names.append(message.property_name)
            if isinstance(message, PropertyChangedMessage)
            else None
        )
    )
    vm.property_changed.subscribe(local_names.append)
    vm.dispose()
    hub_names.clear()
    local_names.clear()

    vm.emit_value_notification()

    assert hub_names == []
    assert local_names == []


@pytest.mark.conformance("CVM-010")
def test_CVM_010_modeled_components_explicitly_republish_retained_model() -> None:
    class ReferenceModel:
        def __init__(self, value: int) -> None:
            self.value = value
            self.equality_calls = 0

        def __eq__(self, other: object) -> bool:
            self.equality_calls += 1
            return isinstance(other, ReferenceModel) and self.value == other.value

    model = ReferenceModel(7)
    hinter_calls = 0
    callback_calls = 0

    def hinter(value: ReferenceModel) -> str:
        nonlocal hinter_calls
        hinter_calls += 1
        return f"hint:{value.value}"

    def on_model_changed(_value: ReferenceModel) -> None:
        nonlocal callback_calls
        callback_calls += 1

    hub = _hub()
    vm = (
        ComponentVMOfBuilder()
        .name("writable")
        .model(model)
        .modeled_hinter(hinter)
        .on_model_changed(on_model_changed)
        .services(hub, _dispatcher())
        .build()
    )
    hint = vm.modeled_hint
    hinter_calls_after_build = hinter_calls
    equality_calls_before_republish = model.equality_calls
    trace: list[str] = []
    hub.messages.subscribe(
        lambda message: (
            trace.append("hub:model")
            if isinstance(message, PropertyChangedMessage)
            and message.property_name == "model"
            and message.sender is vm
            else None
        )
    )
    vm.property_changed.subscribe(
        lambda name: trace.append("local:model") if name == "model" else None
    )

    vm.republish_model()

    assert vm.model is model
    assert vm.modeled_hint == hint
    assert hinter_calls == hinter_calls_after_build
    assert model.equality_calls == equality_calls_before_republish
    assert callback_calls == 0
    assert trace == ["hub:model", "local:model"]

    trace.clear()
    vm.model = model
    assert trace == []

    replacement = ReferenceModel(8)
    trace.clear()
    vm.model = replacement

    assert vm.model is replacement
    assert vm.modeled_hint == "hint:8"
    assert hinter_calls == hinter_calls_after_build + 1
    assert callback_calls == 1
    assert model.equality_calls > equality_calls_before_republish
    assert trace == ["hub:model", "local:model"]

    readonly_hub = _hub()
    readonly_vm = (
        ReadonlyComponentVMOfBuilder()
        .name("readonly")
        .model(model)
        .services(readonly_hub, _dispatcher())
        .build()
    )
    readonly_trace: list[str] = []
    readonly_hub.messages.subscribe(
        lambda message: (
            readonly_trace.append("hub:model")
            if isinstance(message, PropertyChangedMessage) and message.property_name == "model"
            else None
        )
    )
    readonly_vm.property_changed.subscribe(
        lambda name: readonly_trace.append("local:model") if name == "model" else None
    )

    readonly_vm.republish_model()

    assert readonly_vm.model is model
    assert readonly_trace == ["hub:model", "local:model"]

    wrapped_hub = _hub()
    wrapped = (
        ComponentVMOfBuilder()
        .name("wrapped")
        .model(model)
        .services(wrapped_hub, _dispatcher())
        .build()
    )
    forwarding = ForwardingComponentVM(wrapped)
    forwarded_senders: list[object] = []
    forwarded_local: list[str] = []
    wrapped_hub.messages.subscribe(
        lambda message: (
            forwarded_senders.append(message.sender)
            if isinstance(message, PropertyChangedMessage) and message.property_name == "model"
            else None
        )
    )
    forwarding.property_changed.subscribe(forwarded_local.append)

    forwarding.republish_model()

    assert forwarded_senders == [wrapped]
    assert forwarded_local == ["model"]

    null_vm = ComponentVMOfBuilder().name("null").model(model).with_null_services().build()
    null_local: list[str] = []
    null_vm.property_changed.subscribe(null_local.append)

    null_vm.republish_model()

    assert null_local == ["model"]

    disposed_hub = _hub()
    disposed_vm = (
        ComponentVMOfBuilder()
        .name("disposed")
        .model(model)
        .services(disposed_hub, _dispatcher())
        .build()
    )
    disposed_hub_names: list[str] = []
    disposed_local: list[str] = []
    disposed_hub.messages.subscribe(
        lambda message: (
            disposed_hub_names.append(message.property_name)
            if isinstance(message, PropertyChangedMessage)
            else None
        )
    )
    disposed_vm.property_changed.subscribe(disposed_local.append)
    disposed_vm.dispose()
    disposed_hub_names.clear()
    disposed_local.clear()

    disposed_vm.republish_model()

    assert disposed_hub_names == []
    assert disposed_local == []

    reentrant_hub = _hub()
    reentrant_vm = (
        ComponentVMOfBuilder()
        .name("reentrant")
        .model(model)
        .services(reentrant_hub, _dispatcher())
        .build()
    )
    reentered = False
    reentrant_trace: list[str] = []

    def reenter_once(message: object) -> None:
        nonlocal reentered
        if not isinstance(message, PropertyChangedMessage) or message.property_name != "model":
            return
        reentrant_trace.append("hub:model")
        if reentered:
            return
        reentered = True
        reentrant_vm.republish_model()

    reentrant_hub.messages.subscribe(reenter_once)
    reentrant_vm.property_changed.subscribe(
        lambda name: reentrant_trace.append("local:model") if name == "model" else None
    )

    reentrant_vm.republish_model()

    assert reentrant_trace == ["hub:model", "local:model", "hub:model", "local:model"]

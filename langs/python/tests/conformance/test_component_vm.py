"""Conformance tests: CVM-001..006.

The LIFE-001..010, 012 and PROP-001..004 ids each own a single self-contained
test in test_lifecycle.py / test_property_change.py respectively; this file no
longer hosts duplicate (double-counted) copies of them (VMX-055).
"""

from __future__ import annotations

import pytest

from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder
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

    # Build a minimal parent stub.
    class _FakeParent:
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

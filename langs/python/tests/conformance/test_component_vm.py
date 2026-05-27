"""Conformance tests: CVM-001..006 + delegated LIFE-001..010, 012 + PROP-001..004.

Function names here are imported by test_lifecycle.py and test_property_change.py
via their delegation stubs — do NOT rename them.

Naming convention for delegated functions:
  test_LIFE_NNN_<description>     — imported by test_lifecycle.py
  test_PROP_NNN_<description>     — imported by test_property_change.py
"""

from __future__ import annotations

import pytest

from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status import ConstructionStatusChangedMessage
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


# ===========================================================================
# LIFE-* delegated implementations
# ===========================================================================
# These function names are imported verbatim by tests/conformance/test_lifecycle.py.


@pytest.mark.conformance("LIFE-001")
def test_LIFE_001_construct_emits_status_messages() -> None:
    """LIFE-001: construct() emits Constructing then Constructed."""
    vm, hub = _build_vm()
    msgs = _status_messages(hub)
    vm.construct()
    statuses = [m.status for m in msgs]
    assert ConstructionStatus.CONSTRUCTING in statuses
    assert ConstructionStatus.CONSTRUCTED in statuses
    assert statuses.index(ConstructionStatus.CONSTRUCTING) < statuses.index(
        ConstructionStatus.CONSTRUCTED
    )
    assert vm.is_constructed is True


@pytest.mark.conformance("LIFE-002")
def test_LIFE_002_destruct_emits_status_messages() -> None:
    """LIFE-002: destruct() emits Destructing then Destructed."""
    vm, hub = _build_vm()
    vm.construct()
    msgs = _status_messages(hub)
    vm.destruct()
    statuses = [m.status for m in msgs]
    assert ConstructionStatus.DESTRUCTING in statuses
    assert ConstructionStatus.DESTRUCTED in statuses
    assert statuses.index(ConstructionStatus.DESTRUCTING) < statuses.index(
        ConstructionStatus.DESTRUCTED
    )
    assert vm.is_constructed is False


@pytest.mark.conformance("LIFE-003")
def test_LIFE_003_reconstruct_emits_four_messages() -> None:
    """LIFE-003: reconstruct() emits exactly four messages in the right order."""
    vm, hub = _build_vm()
    vm.construct()
    msgs = _status_messages(hub)
    vm.reconstruct()
    statuses = [m.status for m in msgs]
    assert statuses == [
        ConstructionStatus.DESTRUCTING,
        ConstructionStatus.DESTRUCTED,
        ConstructionStatus.CONSTRUCTING,
        ConstructionStatus.CONSTRUCTED,
    ], f"Expected full reconstruct sequence, got {statuses}"


@pytest.mark.conformance("LIFE-004")
def test_LIFE_004_dispose_reaches_disposed() -> None:
    """LIFE-004: dispose() transitions VM to Disposed from any state."""
    vm, hub = _build_vm()
    msgs = _status_messages(hub)
    vm.dispose()
    assert vm.status == ConstructionStatus.DISPOSED
    disposed_msgs = [m for m in msgs if m.status == ConstructionStatus.DISPOSED]
    assert len(disposed_msgs) == 1


@pytest.mark.conformance("LIFE-007")
def test_LIFE_007_is_constructed_invariant() -> None:
    """LIFE-007: is_constructed == (status == Constructed) at all times."""
    vm, _ = _build_vm()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
    vm.construct()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
    assert vm.is_constructed is True
    vm.destruct()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
    assert vm.is_constructed is False
    vm.dispose()
    assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)


@pytest.mark.conformance("LIFE-008")
def test_LIFE_008_concurrent_operation_raises() -> None:
    """LIFE-008: re-invoking construct() while in-flight raises StatusTransitionError."""
    caught: list[StatusTransitionError] = []
    vm = None

    def on_construct_cb() -> None:
        # This callback fires while the VM is still mid-construct (in-flight).
        # Re-entering construct() must raise StatusTransitionError.
        try:
            assert vm is not None
            vm.construct()
        except StatusTransitionError as exc:
            caught.append(exc)

    hub, dispatcher = _hub(), _dispatcher()
    vm = (
        ComponentVMBuilder()
        .name("vm-reentrant")
        .services(hub, dispatcher)
        .on_construct(on_construct_cb)
        .build()
    )

    vm.construct()

    assert len(caught) == 1, (
        "Re-entrant construct() during in-flight transition must raise StatusTransitionError"
    )


@pytest.mark.conformance("LIFE-009")
def test_LIFE_009_construct_from_constructed_is_noop() -> None:
    """LIFE-009: construct() from Constructed emits NO messages (idempotent)."""
    vm, hub = _build_vm()
    vm.construct()
    msgs = _status_messages(hub)
    vm.construct()  # should be no-op
    assert len(msgs) == 0
    assert vm.status == ConstructionStatus.CONSTRUCTED


@pytest.mark.conformance("LIFE-010")
def test_LIFE_010_destruct_from_destructed_is_noop() -> None:
    """LIFE-010: destruct() from Destructed emits NO messages (idempotent)."""
    vm, hub = _build_vm()
    msgs = _status_messages(hub)
    vm.destruct()  # should be no-op from Destructed
    assert len(msgs) == 0
    assert vm.status == ConstructionStatus.DESTRUCTED


@pytest.mark.conformance("LIFE-012")
def test_LIFE_012_dispose_from_disposed_is_noop() -> None:
    """LIFE-012: dispose() from Disposed emits NO messages (idempotent)."""
    vm, hub = _build_vm()
    vm.dispose()
    msgs = _status_messages(hub)
    vm.dispose()  # no-op
    assert len(msgs) == 0
    assert vm.status == ConstructionStatus.DISPOSED


# ===========================================================================
# PROP-* delegated implementations
# ===========================================================================
# These function names are imported verbatim by tests/conformance/test_property_change.py.


@pytest.mark.conformance("PROP-001")
def test_PROP_001_property_changed_emitted_on_change() -> None:
    """PROP-001: PropertyChangedMessage emitted when model changes."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"
    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1


@pytest.mark.conformance("PROP-002")
def test_PROP_002_no_message_on_same_value() -> None:
    """PROP-002: No PropertyChangedMessage when setting model to the same value."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m1"  # same value
    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 0


@pytest.mark.conformance("PROP-003")
def test_PROP_003_sender_identity() -> None:
    """PROP-003: message.sender is the exact VM instance."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"
    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1
    assert model_msgs[0].sender is vm, "Sender must be referentially equal to the VM"


@pytest.mark.conformance("PROP-004")
def test_PROP_004_property_name_and_sender_name() -> None:
    """PROP-004: message.property_name == 'model', message.sender_name == vm.name."""
    vm, hub = _build_vm_of(name="n1", model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"
    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1
    assert model_msgs[0].property_name == "model"
    assert model_msgs[0].sender_name == "n1"

"""Conformance tests: PROP-001..004.

Each id drives a real ``ComponentVMOf`` wired to a hub and asserts the
``PropertyChangedMessage`` contract directly — emitted only on real changes,
suppressed on same-value sets, and carrying the correct sender identity, sender
name, and property name. An earlier revision delegated these ids to one-line
wrappers around ``test_component_vm.py`` that asserted nothing locally and
double-counted each id (VMX-055); they were replaced with the self-contained
bodies below.
"""

from __future__ import annotations

import pytest

from vmx.components.builders import ComponentVMOfBuilder
from vmx.components.component_vm import ComponentVMOf
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


def _build_vm_of(
    name: str = "vm1",
    model: object = "m1",
) -> tuple[ComponentVMOf[object], MessageHub[object]]:
    """Build a ComponentVMOf wired to a real hub + immediate dispatcher."""
    hub = _hub()
    vm = ComponentVMOfBuilder().name(name).model(model).services(hub, _dispatcher()).build()
    return vm, hub


def _prop_messages(hub: MessageHub[object]) -> list[PropertyChangedMessage]:
    """Subscribe to *hub* and accumulate PropertyChangedMessages in order."""
    collected: list[PropertyChangedMessage] = []
    hub.messages.subscribe(
        lambda m: collected.append(m) if isinstance(m, PropertyChangedMessage) else None
    )
    return collected


# ---------------------------------------------------------------------------
# PROP-001 — setting a property to a different value publishes a message
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-001")
def test_PROP_001_property_changed_emitted_on_change() -> None:
    """PROP-001: setting model to a different value publishes one PropertyChangedMessage."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"

    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1


# ---------------------------------------------------------------------------
# PROP-002 — setting a property to the same value does NOT publish
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-002")
def test_PROP_002_no_message_on_same_value() -> None:
    """PROP-002: setting model to the same value publishes no PropertyChangedMessage."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m1"  # same value

    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 0


# ---------------------------------------------------------------------------
# PROP-003 — sender identity equals the VM instance
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-003")
def test_PROP_003_sender_identity() -> None:
    """PROP-003: the message's sender is the exact VM instance that changed."""
    vm, hub = _build_vm_of(model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"

    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1
    assert model_msgs[0].sender is vm, "Sender must be referentially equal to the VM"


# ---------------------------------------------------------------------------
# PROP-004 — property_name and sender_name correctness
# ---------------------------------------------------------------------------


@pytest.mark.conformance("PROP-004")
def test_PROP_004_property_name_and_sender_name() -> None:
    """PROP-004: the message carries property_name == 'model' and sender_name == vm.name."""
    vm, hub = _build_vm_of(name="n1", model="m1")
    msgs = _prop_messages(hub)
    vm.model = "m2"

    model_msgs = [m for m in msgs if m.property_name == "model"]
    assert len(model_msgs) == 1
    assert model_msgs[0].property_name == "model"
    assert model_msgs[0].sender_name == "n1"

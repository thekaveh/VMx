"""Cross-cutting builder conformance tests (BLD-001..004).

These test the builder behaviors that apply across all VM types, using
ComponentVMOf[str] as the representative VM.
"""

from __future__ import annotations

import pytest

from vmx.builders.exceptions import BuilderValidationError
from vmx.components.component_vm import ComponentVMOf
from vmx.components.protocols import ViewModelType
from vmx.messages.protocols import Message
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


@pytest.mark.conformance("BLD-001")
def test_BLD_001_setter_returns_new_builder_instance() -> None:
    """Each setter on a builder returns a NEW instance (immutability)."""
    b1 = ComponentVMOf[str].builder()
    b2 = b1.name("x")
    assert b1 is not b2
    # b1._name is None; b2._name is "x"
    assert b1._name is None
    assert b2._name == "x"


@pytest.mark.conformance("BLD-002")
def test_BLD_002_missing_required_field_raises() -> None:
    """Build() with missing required field raises BuilderValidationError with field name."""
    with pytest.raises(BuilderValidationError) as exc_info:
        # Omit services() — hub and dispatcher are required
        ComponentVMOf[str].builder().name("vm").model("init").build()
    assert exc_info.value.missing_field is not None
    assert exc_info.value.missing_field != ""


@pytest.mark.conformance("BLD-003")
def test_BLD_003_repeated_build_produces_equivalent_distinct_vms() -> None:
    """Calling build() twice on the same builder produces two distinct but
    functionally-equivalent VMs."""
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    builder = (
        ComponentVMOf[str].builder().name("vm").hint("h").services(hub, dispatcher).model("init")
    )
    vm_a = builder.build()
    vm_b = builder.build()
    assert vm_a is not vm_b
    assert vm_a.name == vm_b.name == "vm"
    assert vm_a.hint == vm_b.hint == "h"
    assert vm_a.model == vm_b.model == "init"
    vm_a.dispose()
    vm_b.dispose()


@pytest.mark.conformance("BLD-004")
def test_BLD_004_field_defaults_applied() -> None:
    """When optional fields aren't set, defaults are applied."""
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    vm = ComponentVMOf[str].builder().name("vm").services(hub, dispatcher).model("init").build()
    assert vm.hint == ""  # default
    assert vm.type is ViewModelType.COMPONENT  # default derived from class
    vm.dispose()

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


def test_with_null_services_wires_null_singletons() -> None:
    """Per ADR-0035 §2 SV1: ``with_null_services()`` is a chainable Wither
    on the component builders that wires ``NULL_MESSAGE_HUB`` +
    ``NULL_DISPATCHER`` in one call. Mirrors C# ``WithNullServices()`` /
    TS ``withNullServices()``.
    """
    from vmx.components.component_vm import ComponentVM
    from vmx.services.null_dispatcher import NULL_DISPATCHER
    from vmx.services.null_message_hub import NULL_MESSAGE_HUB

    # Non-modeled
    vm: ComponentVM = ComponentVM.builder().name("vm").with_null_services().build()
    assert vm._hub is NULL_MESSAGE_HUB
    assert vm._dispatcher is NULL_DISPATCHER
    vm.dispose()

    # Modeled
    vm_m = ComponentVMOf[str].builder().name("vm").model("init").with_null_services().build()
    assert vm_m._hub is NULL_MESSAGE_HUB
    assert vm_m._dispatcher is NULL_DISPATCHER
    vm_m.dispose()

    # Readonly modeled
    from vmx.components.readonly_component_vm import ReadonlyComponentVMOf

    ro = ReadonlyComponentVMOf[str].builder().name("vm").model("init").with_null_services().build()
    assert ro._hub is NULL_MESSAGE_HUB
    assert ro._dispatcher is NULL_DISPATCHER
    ro.dispose()


@pytest.mark.conformance("FORM-011")
def test_FORM_011_form_vm_builder_validates_required_initial() -> None:
    """FORM-011: FormVMBuilder.build() raises when ``initial`` is not set."""
    from vmx.forms import FormVMBuilder

    async def persister(_m: str) -> None:
        return None

    with pytest.raises(BuilderValidationError) as exc_info:
        FormVMBuilder().persister(persister).build()
    assert exc_info.value.missing_field == "initial"


@pytest.mark.conformance("FORM-011")
def test_FORM_011_form_vm_builder_validates_required_persister() -> None:
    """FORM-011: FormVMBuilder.build() raises when ``persister`` is not set."""
    from vmx.forms import FormVMBuilder

    with pytest.raises(BuilderValidationError) as exc_info:
        FormVMBuilder().initial("init").build()
    assert exc_info.value.missing_field == "persister"


@pytest.mark.conformance("FORM-012")
def test_FORM_012_form_vm_builder_repeated_build_produces_equivalent_forms() -> None:
    """FORM-012: Repeated ``build()`` calls produce distinct-but-equivalent forms."""
    from vmx.forms import FormVMBuilder

    async def persister(_m: str) -> None:
        return None

    b = FormVMBuilder().initial("init").persister(persister).strict(True)
    f1 = b.build()
    f2 = b.build()
    assert f1 is not f2
    assert f1.model == f2.model == "init"
    assert f1.snapshot == f2.snapshot == "init"
    assert f1.is_dirty == f2.is_dirty is False


@pytest.mark.conformance("FORM-013")
def test_FORM_013_form_vm_builder_field_defaults_applied() -> None:
    """FORM-013: Field defaults applied when optional fields not set.

    Hub defaults to NULL_MESSAGE_HUB; strict defaults to False so
    approve_command.can_execute() returns True regardless of is_dirty.
    """
    from vmx.forms import FormVMBuilder
    from vmx.services.null_message_hub import NULL_MESSAGE_HUB

    async def persister(_m: str) -> None:
        return None

    f = FormVMBuilder().initial("init").persister(persister).build()
    assert f.is_dirty is False  # initial == snapshot
    assert f.approve_command.can_execute() is True  # strict defaults to False
    assert f._hub is NULL_MESSAGE_HUB  # hub defaults to NULL_MESSAGE_HUB
    f.dispose() if hasattr(f, "dispose") else None


@pytest.mark.conformance("BLD-005")
def test_BLD_005_additive_setters_retain_prior_values() -> None:
    """BLD-005: ``RelayCommand.triggers(...)`` is additive (cumulative); calling
    it twice with distinct observables retains BOTH. Other setters such as
    ``name`` and ``task`` continue to overwrite per standard BLD-001 semantics.
    See ADR-0035 §2 BLD-005.
    """
    from reactivex.subject import Subject

    from vmx.commands.relay_command import RelayCommand

    trigger1: Subject[None] = Subject()
    trigger2: Subject[None] = Subject()

    cmd = RelayCommand.builder().triggers(trigger1).triggers(trigger2).build()

    firings: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: firings.append(1))

    trigger1.on_next(None)
    assert len(firings) == 1, "first trigger must fire can_execute_changed"

    trigger2.on_next(None)
    assert len(firings) == 2, (
        "second trigger must ALSO fire can_execute_changed — triggers is additive"
    )


def test_with_null_services_returns_new_builder_instance() -> None:
    """``with_null_services()`` adheres to BLD-001: returns a new builder
    instance rather than mutating the original."""
    b1 = ComponentVMOf[str].builder().name("vm").model("init")
    b2 = b1.with_null_services()
    assert b1 is not b2
    # b1 still has no services wired
    assert b1._hub is None
    assert b1._dispatcher is None
    # b2 has them
    assert b2._hub is not None
    assert b2._dispatcher is not None

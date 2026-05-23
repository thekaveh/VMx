"""Unit tests for ReadonlyComponentVMOf.

Verifies:
- Model is read-only (no setter)
- modeled_hint is computed from model at build time and stable
- All lifecycle operations work the same as ComponentVM
- Type is READONLY_COMPONENT
"""

from __future__ import annotations

import pytest

from vmx.builders.exceptions import BuilderValidationError
from vmx.components.builders import ReadonlyComponentVMOfBuilder
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


def make_hub() -> MessageHub[object]:
    return MessageHub()


def make_dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def make_readonly_vm(
    name: str = "ro-vm",
    model: object = "initial",
    hint: str = "",
) -> object:
    hub = make_hub()
    dispatcher = make_dispatcher()
    return (
        ReadonlyComponentVMOfBuilder()
        .name(name)
        .model(model)
        .hint(hint)
        .services(hub, dispatcher)
        .build()
    )


class TestReadonlyComponentVMOfIdentity:
    def test_name_set_correctly(self) -> None:
        vm = make_readonly_vm(name="my-ro-vm")
        assert vm.name == "my-ro-vm"

    def test_hint_set_correctly(self) -> None:
        vm = make_readonly_vm(hint="A hint")
        assert vm.hint == "A hint"

    def test_type_is_readonly_component(self) -> None:
        vm = make_readonly_vm()
        assert vm.type == ViewModelType.READONLY_COMPONENT

    def test_model_readable(self) -> None:
        vm = make_readonly_vm(model="hello")
        assert vm.model == "hello"

    def test_modeled_hint_default_empty(self) -> None:
        vm = make_readonly_vm(model="x")
        assert vm.modeled_hint == ""

    def test_modeled_hint_from_hinter(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ReadonlyComponentVMOfBuilder()
            .name("v")
            .model(42)
            .services(hub, dispatcher)
            .modeled_hinter(lambda n: f"val:{n}")
            .build()
        )
        assert vm.modeled_hint == "val:42"

    def test_no_model_setter(self) -> None:
        """ReadonlyComponentVMOf must not expose a public model setter."""
        vm = make_readonly_vm(model="x")
        # The type itself should not have a setter — verify via property descriptor.
        prop = type(vm).__dict__.get("model")
        assert prop is not None
        # Property should have no setter (fset is None).
        assert prop.fset is None, "ReadonlyComponentVMOf.model must NOT have a setter"


class TestReadonlyComponentVMOfLifecycle:
    def test_construct_works(self) -> None:
        vm = make_readonly_vm()
        vm.construct()
        assert vm.status == ConstructionStatus.CONSTRUCTED

    def test_destruct_works(self) -> None:
        vm = make_readonly_vm()
        vm.construct()
        vm.destruct()
        assert vm.status == ConstructionStatus.DESTRUCTED

    def test_dispose_works(self) -> None:
        vm = make_readonly_vm()
        vm.dispose()
        assert vm.status == ConstructionStatus.DISPOSED


class TestReadonlyComponentVMOfBuilder:
    def test_missing_name_raises(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            ReadonlyComponentVMOfBuilder().model("m").services(hub, dispatcher).build()
        assert exc_info.value.missing_field == "name"

    def test_missing_model_raises(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            ReadonlyComponentVMOfBuilder().name("v").services(hub, dispatcher).build()
        assert exc_info.value.missing_field == "model"

    def test_missing_hub_raises(self) -> None:
        with pytest.raises(BuilderValidationError) as exc_info:
            ReadonlyComponentVMOfBuilder().name("v").model("m").build()
        assert exc_info.value.missing_field == "hub"

    def test_setter_returns_new_instance(self) -> None:
        b1 = ReadonlyComponentVMOfBuilder()
        b2 = b1.name("x")
        assert b1 is not b2
        assert b1._name is None
        assert b2._name == "x"

    def test_repeated_build_produces_distinct_vms(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        b = ReadonlyComponentVMOfBuilder().name("v").model("m").hint("h").services(hub, dispatcher)
        vm_a = b.build()
        vm_b = b.build()
        assert vm_a is not vm_b
        assert vm_a.name == vm_b.name
        assert vm_a.model == vm_b.model
        assert vm_a.hint == vm_b.hint

    def test_defaults_applied(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ReadonlyComponentVMOfBuilder().name("v").model("m").services(hub, dispatcher).build()
        assert vm.hint == ""
        assert vm.type == ViewModelType.READONLY_COMPONENT

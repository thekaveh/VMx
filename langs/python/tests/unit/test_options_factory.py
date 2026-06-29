"""Tests for the additive ``create(...)`` construction form (ADR-0055 / VMX-020).

Each ``create`` classmethod is a one-call alternative to the fluent builder. It
delegates to the builder internally, so behaviour/validation are identical by
construction; these tests pin that contract: the ``create`` path produces a VM
equivalent to the builder path and validates the same required fields.
"""

from __future__ import annotations

import pytest

from vmx.builders.exceptions import BuilderValidationError
from vmx.components.component_vm import ComponentVM, ComponentVMOf
from vmx.components.protocols import ViewModelType
from vmx.composites.composite_vm import CompositeVM
from vmx.groups.group_vm import GroupVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


def make_hub() -> MessageHub[object]:
    return MessageHub()


def make_dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


# ── ComponentVM (non-modeled) ────────────────────────────────────────────────


def test_component_vm_create_matches_builder() -> None:
    hub, dispatcher = make_hub(), make_dispatcher()

    via_builder = ComponentVM.builder().name("vm").hint("h").services(hub, dispatcher).build()
    via_create = ComponentVM.create(name="vm", hint="h", hub=hub, dispatcher=dispatcher)

    assert via_create.name == via_builder.name
    assert via_create.hint == via_builder.hint
    assert via_create.type == via_builder.type == ViewModelType.COMPONENT
    assert via_create.status == via_builder.status == ConstructionStatus.DESTRUCTED


def test_component_vm_create_constructs() -> None:
    vm = ComponentVM.create(name="vm", hub=make_hub(), dispatcher=make_dispatcher())
    vm.construct()
    assert vm.is_constructed


def test_component_vm_create_missing_hub_raises() -> None:
    with pytest.raises(BuilderValidationError):
        ComponentVM.create(name="vm")


def test_component_vm_create_missing_name_raises() -> None:
    with pytest.raises(BuilderValidationError):
        ComponentVM.create(hub=make_hub(), dispatcher=make_dispatcher())


# ── ComponentVMOf (modeled) ──────────────────────────────────────────────────


def test_component_vm_of_create_matches_builder() -> None:
    hub, dispatcher = make_hub(), make_dispatcher()

    via_builder = (
        ComponentVMOf.builder().name("vm").hint("h").model("m").services(hub, dispatcher).build()
    )
    via_create = ComponentVMOf.create(
        name="vm", hint="h", model="m", hub=hub, dispatcher=dispatcher
    )

    assert via_create.name == via_builder.name
    assert via_create.hint == via_builder.hint
    assert via_create.model == via_builder.model == "m"
    assert via_create.type == via_builder.type


def test_component_vm_of_create_carries_optional_fields() -> None:
    changes: list[str] = []
    vm = ComponentVMOf.create(
        name="vm",
        model="m0",
        modeled_hinter=lambda m: f"hint:{m}",
        on_model_changed=changes.append,
        hub=make_hub(),
        dispatcher=make_dispatcher(),
    )

    assert vm.modeled_hint == "hint:m0"
    vm.model = "m1"
    assert vm.model == "m1"
    assert changes == ["m1"]


def test_component_vm_of_create_missing_hub_raises() -> None:
    with pytest.raises(BuilderValidationError):
        ComponentVMOf.create(name="vm", model="m")


# ── CompositeVM (non-modeled) ────────────────────────────────────────────────


def test_composite_vm_create_matches_builder_and_populates() -> None:
    hub, dispatcher = make_hub(), make_dispatcher()

    def child() -> ComponentVM:
        return ComponentVM.create(name="child", hub=hub, dispatcher=dispatcher)

    vm: CompositeVM[ComponentVM] = CompositeVM.create(
        name="comp",
        hint="h",
        hub=hub,
        dispatcher=dispatcher,
        children=lambda: [child()],
    )

    assert vm.name == "comp"
    assert vm.hint == "h"
    assert vm.type == ViewModelType.COMPOSITE
    assert len(vm) == 0  # children factory is lazy: evaluated on construct()

    vm.construct()
    assert vm.status == ConstructionStatus.CONSTRUCTED
    assert len(vm) == 1


def test_composite_vm_create_missing_children_raises() -> None:
    # children is a required keyword — omitting it is a TypeError at the call site.
    with pytest.raises(TypeError):
        CompositeVM.create(name="comp", hub=make_hub(), dispatcher=make_dispatcher())  # type: ignore[call-arg]


def test_composite_vm_create_missing_hub_raises() -> None:
    with pytest.raises(BuilderValidationError):
        CompositeVM.create(name="comp", children=lambda: [])


# ── GroupVM (non-modeled) ────────────────────────────────────────────────────


def test_group_vm_create_matches_builder_and_populates() -> None:
    hub, dispatcher = make_hub(), make_dispatcher()

    def child() -> ComponentVM:
        return ComponentVM.create(name="child", hub=hub, dispatcher=dispatcher)

    vm: GroupVM[ComponentVM] = GroupVM.create(
        name="grp",
        hub=hub,
        dispatcher=dispatcher,
        children=lambda: [child(), child()],
    )

    assert vm.name == "grp"
    assert vm.type == ViewModelType.GROUP

    vm.construct()
    assert vm.status == ConstructionStatus.CONSTRUCTED
    assert vm.count == 2


def test_group_vm_create_missing_hub_raises() -> None:
    with pytest.raises(BuilderValidationError):
        GroupVM.create(name="grp", children=lambda: [])

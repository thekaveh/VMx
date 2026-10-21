"""Raw constructors default ``hint`` to "" and ``modeled_hinter`` to an empty hint.

The builders already default both (spec/10 §4, BLD-004); the keyword-only raw
constructors that subclasses call through ``super().__init__`` now match.
No conformance ID (Python constructor ergonomics, #663).
"""

from __future__ import annotations

from vmx.aggregates import (
    AggregateVM1,
    AggregateVM2,
    AggregateVM3,
    AggregateVM4,
    AggregateVM5,
    AggregateVM6,
)
from vmx.components import ComponentVM, ComponentVMOf
from vmx.components.readonly_component_vm import ReadonlyComponentVMOf
from vmx.composites import CompositeVM, CompositeVMOf
from vmx.groups import GroupVM
from vmx.messages.protocols import Message
from vmx.services import MessageHub, RxDispatcher


def _leaf() -> ComponentVM:
    return ComponentVM(name="leaf", hub=MessageHub(), dispatcher=RxDispatcher.immediate())


def test_component_vm_defaults_hint() -> None:
    assert _leaf().hint == ""


def test_component_vm_of_defaults_hint_and_modeled_hint() -> None:
    vm = ComponentVMOf[int](
        name="count", initial_model=1, hub=MessageHub(), dispatcher=RxDispatcher.immediate()
    )

    assert (vm.hint, vm.modeled_hint) == ("", "")
    vm.model = 2
    assert vm.modeled_hint == ""


def test_component_vm_of_keeps_a_supplied_modeled_hinter() -> None:
    vm = ComponentVMOf[int](
        name="count",
        initial_model=1,
        modeled_hinter=lambda m: f"#{m}",
        hub=MessageHub(),
        dispatcher=RxDispatcher.immediate(),
    )

    assert (vm.hint, vm.modeled_hint) == ("", "#1")


def test_readonly_component_vm_of_defaults_hint_and_modeled_hint() -> None:
    vm = ReadonlyComponentVMOf[str](
        name="title", model="draft", hub=MessageHub(), dispatcher=RxDispatcher.immediate()
    )

    assert (vm.hint, vm.modeled_hint) == ("", "")


def test_containers_default_hint() -> None:
    hub: MessageHub[Message] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    composite = CompositeVM[ComponentVM](name="composite", hub=hub, dispatcher=dispatcher)
    modeled = CompositeVMOf[int, ComponentVM](
        name="modeled",
        hub=hub,
        dispatcher=dispatcher,
        children_models=list,
        child_model_to_child_vm=lambda _m: _leaf(),
    )
    group = GroupVM[ComponentVM](name="group", hub=hub, dispatcher=dispatcher)
    leaf = _leaf
    aggregates = [
        AggregateVM1[ComponentVM](name="a1", hub=hub, dispatcher=dispatcher, factory1=leaf),
        AggregateVM2[ComponentVM, ComponentVM](
            name="a2", hub=hub, dispatcher=dispatcher, factory1=leaf, factory2=leaf
        ),
        AggregateVM3[ComponentVM, ComponentVM, ComponentVM](
            name="a3", hub=hub, dispatcher=dispatcher, factory1=leaf, factory2=leaf, factory3=leaf
        ),
        AggregateVM4[ComponentVM, ComponentVM, ComponentVM, ComponentVM](
            name="a4",
            hub=hub,
            dispatcher=dispatcher,
            factory1=leaf,
            factory2=leaf,
            factory3=leaf,
            factory4=leaf,
        ),
        AggregateVM5[ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM](
            name="a5",
            hub=hub,
            dispatcher=dispatcher,
            factory1=leaf,
            factory2=leaf,
            factory3=leaf,
            factory4=leaf,
            factory5=leaf,
        ),
        AggregateVM6[ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM, ComponentVM](
            name="a6",
            hub=hub,
            dispatcher=dispatcher,
            factory1=leaf,
            factory2=leaf,
            factory3=leaf,
            factory4=leaf,
            factory5=leaf,
            factory6=leaf,
        ),
    ]

    assert [vm.hint for vm in (composite, modeled, group)] == ["", "", ""]
    assert [vm.hint for vm in aggregates] == [""] * 6


def test_a_supplied_hint_is_kept() -> None:
    vm = ComponentVM(
        name="leaf", hint="Leaf", hub=MessageHub(), dispatcher=RxDispatcher.immediate()
    )

    assert vm.hint == "Leaf"

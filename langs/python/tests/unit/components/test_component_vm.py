"""Unit tests for ComponentVM and ComponentVMOf.

Tests verify:
- Constructor sets name, hint, type
- Lifecycle operations (construct/destruct/reconstruct/dispose)
- Status state machine and idempotency rules
- PropertyChangedMessage emission on model set
- modeled_hint recomputation
- Built-in commands (select/deselect predicates)
- Builder fluent API (BLD-001)
"""

from __future__ import annotations

import pytest

from vmx.components.builders import ComponentVMBuilder, ComponentVMOfBuilder
from vmx.components.protocols import ViewModelType
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import (
    ConstructionStatusChangedMessage,
)
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_hub() -> MessageHub[object]:
    return MessageHub()


def _is_status_msg(m: object) -> bool:
    return isinstance(m, ConstructionStatusChangedMessage)


def make_dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def make_vm(name: str = "test-vm", hint: str = "") -> object:
    """Build a non-modeled ComponentVM."""
    hub = make_hub()
    dispatcher = make_dispatcher()
    return ComponentVMBuilder().name(name).hint(hint).services(hub, dispatcher).build()


def make_vm_of(
    name: str = "test-vm",
    model: object = "initial",
    hint: str = "",
) -> tuple[object, MessageHub[object]]:
    """Build a ComponentVMOf[str] and return (vm, hub)."""
    hub = make_hub()
    dispatcher = make_dispatcher()
    vm = ComponentVMOfBuilder().name(name).hint(hint).model(model).services(hub, dispatcher).build()
    return vm, hub


# ---------------------------------------------------------------------------
# ComponentVM (non-modeled) unit tests
# ---------------------------------------------------------------------------


class TestComponentVMIdentity:
    def test_name_set_correctly(self) -> None:
        vm = make_vm(name="my-vm")
        assert vm.name == "my-vm"

    def test_hint_set_correctly(self) -> None:
        vm = make_vm(hint="Some hint")
        assert vm.hint == "Some hint"

    def test_hint_defaults_to_empty(self) -> None:
        vm = make_vm()
        assert vm.hint == ""

    def test_type_is_component(self) -> None:
        vm = make_vm()
        assert vm.type == ViewModelType.COMPONENT

    def test_initial_status_is_destructed(self) -> None:
        vm = make_vm()
        assert vm.status == ConstructionStatus.DESTRUCTED

    def test_initial_is_constructed_false(self) -> None:
        vm = make_vm()
        assert vm.is_constructed is False


class TestComponentVMLifecycle:
    def test_construct_transitions_to_constructed(self) -> None:
        vm = make_vm()
        vm.construct()
        assert vm.status == ConstructionStatus.CONSTRUCTED
        assert vm.is_constructed is True

    def test_construct_emits_two_messages(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ComponentVMBuilder().name("v").services(hub, dispatcher).build()
        messages: list[ConstructionStatusChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if _is_status_msg(m) else None  # type: ignore[arg-type]
        )
        vm.construct()
        statuses = [m.status for m in messages]
        assert ConstructionStatus.CONSTRUCTING in statuses
        assert ConstructionStatus.CONSTRUCTED in statuses
        ing_idx = statuses.index(ConstructionStatus.CONSTRUCTING)
        ed_idx = statuses.index(ConstructionStatus.CONSTRUCTED)
        assert ing_idx < ed_idx

    def test_construct_from_constructed_is_noop(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ComponentVMBuilder().name("v").services(hub, dispatcher).build()
        vm.construct()
        messages: list[ConstructionStatusChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if _is_status_msg(m) else None  # type: ignore[arg-type]
        )
        vm.construct()  # no-op
        assert len(messages) == 0

    def test_destruct_transitions_to_destructed(self) -> None:
        vm = make_vm()
        vm.construct()
        vm.destruct()
        assert vm.status == ConstructionStatus.DESTRUCTED
        assert vm.is_constructed is False

    def test_destruct_from_destructed_is_noop(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ComponentVMBuilder().name("v").services(hub, dispatcher).build()
        messages: list[ConstructionStatusChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if _is_status_msg(m) else None  # type: ignore[arg-type]
        )
        vm.destruct()  # no-op
        assert len(messages) == 0

    def test_reconstruct_emits_four_messages(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ComponentVMBuilder().name("v").services(hub, dispatcher).build()
        vm.construct()
        messages: list[ConstructionStatusChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if _is_status_msg(m) else None  # type: ignore[arg-type]
        )
        vm.reconstruct()
        statuses = [m.status for m in messages]
        assert statuses == [
            ConstructionStatus.DESTRUCTING,
            ConstructionStatus.DESTRUCTED,
            ConstructionStatus.CONSTRUCTING,
            ConstructionStatus.CONSTRUCTED,
        ]

    def test_dispose_transitions_to_disposed(self) -> None:
        vm = make_vm()
        vm.dispose()
        assert vm.status == ConstructionStatus.DISPOSED

    def test_dispose_from_disposed_is_noop(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ComponentVMBuilder().name("v").services(hub, dispatcher).build()
        vm.dispose()
        messages: list[ConstructionStatusChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if _is_status_msg(m) else None  # type: ignore[arg-type]
        )
        vm.dispose()  # no-op
        assert len(messages) == 0

    def test_construct_from_disposed_raises(self) -> None:
        vm = make_vm()
        vm.dispose()
        with pytest.raises(StatusTransitionError):
            vm.construct()

    def test_destruct_from_disposed_raises(self) -> None:
        vm = make_vm()
        vm.dispose()
        with pytest.raises(StatusTransitionError):
            vm.destruct()

    def test_is_constructed_invariant(self) -> None:
        vm = make_vm()
        assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
        vm.construct()
        assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)
        vm.destruct()
        assert vm.is_constructed == (vm.status == ConstructionStatus.CONSTRUCTED)

    def test_on_construct_callback_invoked(self) -> None:
        calls: list[int] = []
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ComponentVMBuilder()
            .name("v")
            .services(hub, dispatcher)
            .on_construct(lambda: calls.append(1))
            .build()
        )
        vm.construct()
        assert len(calls) == 1

    def test_on_destruct_callback_invoked(self) -> None:
        calls: list[int] = []
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ComponentVMBuilder()
            .name("v")
            .services(hub, dispatcher)
            .on_destruct(lambda: calls.append(1))
            .build()
        )
        vm.construct()
        vm.destruct()
        assert len(calls) == 1


class TestComponentVMConcurrencyGuard:
    def test_concurrent_construct_raises(self) -> None:
        """Simulate re-entry during in-flight by setting _in_flight manually."""
        vm = make_vm()
        vm._in_flight = True
        vm._status = ConstructionStatus.DESTRUCTED
        with pytest.raises(StatusTransitionError):
            vm.construct()
        vm._in_flight = False

    def test_concurrent_destruct_raises(self) -> None:
        vm = make_vm()
        vm.construct()
        vm._in_flight = True
        with pytest.raises(StatusTransitionError):
            vm.destruct()
        vm._in_flight = False


class TestComponentVMCommands:
    def test_can_construct_true_from_destructed(self) -> None:
        vm = make_vm()
        assert vm.can_construct() is True

    def test_can_destruct_false_from_destructed(self) -> None:
        # can_destruct is True from Destructed (idempotent destruct is allowed)
        vm = make_vm()
        assert vm.can_destruct() is True

    def test_can_reconstruct_false_from_destructed(self) -> None:
        vm = make_vm()
        assert vm.can_reconstruct() is False

    def test_can_reconstruct_true_from_constructed(self) -> None:
        vm = make_vm()
        vm.construct()
        assert vm.can_reconstruct() is True

    def test_select_command_exists(self) -> None:
        vm = make_vm()
        assert vm.select_command is not None

    def test_reconstruct_command_exists(self) -> None:
        vm = make_vm()
        assert vm.reconstruct_command is not None


# ---------------------------------------------------------------------------
# ComponentVMOf unit tests
# ---------------------------------------------------------------------------


class TestComponentVMOfModel:
    def test_model_set_in_constructor(self) -> None:
        vm, _ = make_vm_of(model="hello")
        assert vm.model == "hello"

    def test_model_setter_updates_value(self) -> None:
        vm, _ = make_vm_of(model="old")
        vm.model = "new"
        assert vm.model == "new"

    def test_model_setter_same_value_no_message(self) -> None:
        vm, hub = make_vm_of(model="same")
        messages: list[PropertyChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if isinstance(m, PropertyChangedMessage) else None
        )
        vm.model = "same"
        prop_msgs = [m for m in messages if m.property_name == "model"]
        assert len(prop_msgs) == 0

    def test_model_setter_different_value_emits_message(self) -> None:
        vm, hub = make_vm_of(model="old")
        messages: list[PropertyChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if isinstance(m, PropertyChangedMessage) else None
        )
        vm.model = "new"
        prop_msgs = [m for m in messages if m.property_name == "model"]
        assert len(prop_msgs) == 1
        assert prop_msgs[0].sender is vm
        assert prop_msgs[0].sender_name == "test-vm"

    def test_model_setter_invokes_on_model_changed(self) -> None:
        calls: list[str] = []
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ComponentVMOfBuilder()
            .name("v")
            .model("initial")
            .services(hub, dispatcher)
            .on_model_changed(lambda m: calls.append(m))
            .build()
        )
        vm.model = "updated"
        assert calls == ["updated"]

    def test_modeled_hint_default_empty(self) -> None:
        vm, _ = make_vm_of(model="x")
        assert vm.modeled_hint == ""

    def test_modeled_hint_computed_from_hinter(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ComponentVMOfBuilder()
            .name("v")
            .model(7)
            .services(hub, dispatcher)
            .modeled_hinter(lambda n: f"id:{n}")
            .build()
        )
        assert vm.modeled_hint == "id:7"

    def test_modeled_hint_recomputed_on_model_change(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ComponentVMOfBuilder()
            .name("v")
            .model(7)
            .services(hub, dispatcher)
            .modeled_hinter(lambda n: f"id:{n}")
            .build()
        )
        vm.model = 8
        assert vm.modeled_hint == "id:8"

    def test_modeled_hint_change_emits_message(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = (
            ComponentVMOfBuilder()
            .name("v")
            .model(7)
            .services(hub, dispatcher)
            .modeled_hinter(lambda n: f"id:{n}")
            .build()
        )
        messages: list[PropertyChangedMessage] = []
        hub.messages.subscribe(
            lambda m: messages.append(m) if isinstance(m, PropertyChangedMessage) else None
        )
        vm.model = 8
        hint_msgs = [m for m in messages if m.property_name == "modeled_hint"]
        assert len(hint_msgs) == 1

    def test_type_is_component(self) -> None:
        vm, _ = make_vm_of()
        assert vm.type == ViewModelType.COMPONENT


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------


class TestComponentVMBuilder:
    def test_setter_returns_new_instance(self) -> None:
        b1 = ComponentVMBuilder()
        b2 = b1.name("x")
        assert b1 is not b2
        assert b1._name is None
        assert b2._name == "x"

    def test_missing_name_raises(self) -> None:
        from vmx.builders.exceptions import BuilderValidationError

        hub = make_hub()
        dispatcher = make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            ComponentVMBuilder().services(hub, dispatcher).build()
        assert exc_info.value.missing_field == "name"

    def test_missing_hub_raises(self) -> None:
        from vmx.builders.exceptions import BuilderValidationError

        with pytest.raises(BuilderValidationError) as exc_info:
            ComponentVMBuilder().name("v").build()
        assert exc_info.value.missing_field == "hub"

    def test_repeated_build_produces_distinct_vms(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        b = ComponentVMBuilder().name("v").hint("h").services(hub, dispatcher)
        vm_a = b.build()
        vm_b = b.build()
        assert vm_a is not vm_b
        assert vm_a.name == vm_b.name
        assert vm_a.hint == vm_b.hint

    def test_defaults_applied(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        vm = ComponentVMBuilder().name("v").services(hub, dispatcher).build()
        assert vm.hint == ""
        assert vm.type == ViewModelType.COMPONENT


class TestComponentVMOfBuilder:
    def test_missing_model_raises(self) -> None:
        from vmx.builders.exceptions import BuilderValidationError

        hub = make_hub()
        dispatcher = make_dispatcher()
        with pytest.raises(BuilderValidationError) as exc_info:
            ComponentVMOfBuilder().name("v").services(hub, dispatcher).build()
        assert exc_info.value.missing_field == "model"

    def test_setter_returns_new_instance(self) -> None:
        b1 = ComponentVMOfBuilder()
        b2 = b1.name("x")
        assert b1 is not b2

    def test_repeated_build_distinct_vms(self) -> None:
        hub = make_hub()
        dispatcher = make_dispatcher()
        b = ComponentVMOfBuilder().name("v").model("m").services(hub, dispatcher)
        vm_a = b.build()
        vm_b = b.build()
        assert vm_a is not vm_b
        assert vm_a.name == vm_b.name
        assert vm_a.model == vm_b.model


def test_builder_vm_type_overrides_reported_type() -> None:
    """The optional vm_type setter (spec/10 §2) overrides the reported type."""
    vm = (
        ComponentVMOfBuilder()
        .name("typed")
        .model("m")
        .vm_type(ViewModelType.AGGREGATE)
        .with_null_services()
        .build()
    )
    assert vm.type is ViewModelType.AGGREGATE


def test_dispose_during_inflight_background_construct_does_not_resurrect() -> None:
    """spec/02 invariant 3: Disposed is terminal even against scheduled work."""
    from typing import Any as _Any

    from reactivex.scheduler import ImmediateScheduler

    class _DeferredScheduler:
        def __init__(self) -> None:
            self.actions: list[_Any] = []

        def schedule(self, action: _Any, state: _Any = None) -> None:
            self.actions.append(action)

        def run_all(self) -> None:
            for action in self.actions:
                action(self, None)

    bg = _DeferredScheduler()
    dispatcher = RxDispatcher(ImmediateScheduler(), bg)  # type: ignore[arg-type]
    hub: MessageHub[object] = MessageHub()
    hook_calls: list[None] = []
    vm = (
        ComponentVMBuilder()
        .name("bgvm")
        .services(hub, dispatcher)
        .background(True)
        .on_construct(lambda: hook_calls.append(None))
        .build()
    )

    statuses: list[ConstructionStatus] = []
    hub.messages.subscribe(
        lambda m: (
            statuses.append(m.status) if isinstance(m, ConstructionStatusChangedMessage) else None
        )
    )

    vm.construct()  # CONSTRUCTING emitted; work deferred
    vm.dispose()  # terminal before the background work runs
    bg.run_all()  # the scheduled work must now no-op

    assert vm.status is ConstructionStatus.DISPOSED
    assert ConstructionStatus.CONSTRUCTED not in statuses
    assert statuses[-1] is ConstructionStatus.DISPOSED
    # The scheduled work itself must be skipped, not merely silenced by the
    # _set_status terminal guard (pins the background-skip guard in isolation).
    assert hook_calls == []

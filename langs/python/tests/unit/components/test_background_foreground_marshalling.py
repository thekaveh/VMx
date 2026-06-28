"""VMX-025 regression: background construct/destruct must marshal the terminal
status emission onto the foreground scheduler.

A background ``construct()``/``destruct()`` runs ``_on_construct()``/
``_on_destruct()`` on the background scheduler (THR-002), but the *terminal*
``ConstructionStatusChangedMessage`` (Constructed/Destructed) + the
``property_changed`` emission must be marshalled onto ``dispatcher.foreground`` so
UI subscribers observe the terminal transition on the foreground thread, not the
background (pool) thread. The disposed re-check stays atomic — a ``dispose()``
that lands before the marshalled emission runs still aborts it.
"""

from __future__ import annotations

from tests.unit.helpers.test_dispatcher import TestDispatcher
from vmx.components.component_vm import ComponentVMOf
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.message_hub import MessageHub


def test_background_construct_marshals_constructed_emission_onto_foreground() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = TestDispatcher()
    vm: ComponentVMOf[str] = (
        ComponentVMOf[str]
        .builder()
        .name("vm")
        .services(hub, dispatcher)
        .model("m")
        .background(True)
        .build()
    )

    constructed_seen: list[ConstructionStatus] = []
    sub = hub.messages.subscribe(
        lambda m: (
            constructed_seen.append(m.status)
            if isinstance(m, ConstructionStatusChangedMessage)
            and m.sender is vm
            and m.status is ConstructionStatus.CONSTRUCTED
            else None
        )
    )

    vm.construct()

    # Run _on_construct on the background scheduler. The terminal Constructed
    # emission is now queued on the FOREGROUND scheduler — not emitted inline on
    # the background thread — so neither the status nor the hub message has
    # reached Constructed yet.
    dispatcher.background_scheduler.advance_by(1)

    assert vm.status is ConstructionStatus.CONSTRUCTING, (
        "the terminal Constructed emission must be marshalled onto the foreground "
        "scheduler (VMX-025)"
    )
    assert constructed_seen == [], (
        "the Constructed ConstructionStatusChangedMessage must be delivered via the "
        "foreground scheduler, not inline on the background (pool) thread"
    )

    # Advance the foreground scheduler — the marshalled terminal emission runs.
    dispatcher.foreground_scheduler.advance_by(1)

    assert vm.status is ConstructionStatus.CONSTRUCTED
    assert constructed_seen == [ConstructionStatus.CONSTRUCTED]

    sub.dispose()
    vm.dispose()


def test_background_destruct_marshals_destructed_emission_onto_foreground() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = TestDispatcher()
    vm: ComponentVMOf[str] = (
        ComponentVMOf[str]
        .builder()
        .name("vm")
        .services(hub, dispatcher)
        .model("m")
        .background(True)
        .build()
    )

    # Bring the VM to Constructed (drain both schedulers).
    vm.construct()
    dispatcher.background_scheduler.advance_by(1)
    dispatcher.foreground_scheduler.advance_by(1)
    assert vm.status is ConstructionStatus.CONSTRUCTED

    destructed_seen: list[ConstructionStatus] = []
    sub = hub.messages.subscribe(
        lambda m: (
            destructed_seen.append(m.status)
            if isinstance(m, ConstructionStatusChangedMessage)
            and m.sender is vm
            and m.status is ConstructionStatus.DESTRUCTED
            else None
        )
    )

    vm.destruct()

    dispatcher.background_scheduler.advance_by(1)

    assert vm.status is ConstructionStatus.DESTRUCTING, (
        "the terminal Destructed emission must be marshalled onto the foreground "
        "scheduler (VMX-025)"
    )
    assert destructed_seen == [], (
        "the Destructed ConstructionStatusChangedMessage must be delivered via the "
        "foreground scheduler"
    )

    dispatcher.foreground_scheduler.advance_by(1)

    assert vm.status is ConstructionStatus.DESTRUCTED
    assert destructed_seen == [ConstructionStatus.DESTRUCTED]

    sub.dispose()
    vm.dispose()

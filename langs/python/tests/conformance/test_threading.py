"""Conformance tests: THR-001..004.

Threading and scheduler dispatch — all four tests use TestDispatcher /
TestScheduler for deterministic virtual-time control.

See spec/11-threading.md and spec/12-conformance.md §Threading.
"""

from __future__ import annotations

import pytest
import reactivex.operators as ops
from reactivex.testing import TestScheduler

from tests.unit.helpers.test_dispatcher import TestDispatcher
from vmx.collections import CollectionChangedEvent
from vmx.components.component_vm import ComponentVM, ComponentVMOf
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# THR-001 — PropertyChanged observed on foreground scheduler
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THR-001")
def test_THR_001_property_changed_observed_on_foreground_scheduler() -> None:
    """THR-001: hub.Messages filtered on PropertyChangedMessage with
    ObserveOn(dispatcher.Foreground) must buffer delivery until the foreground
    scheduler is advanced.

    Given  a modeled ComponentVMOf built with a TestDispatcher
    And    a subscriber using ObserveOn(dispatcher.foreground)
    When   vm.model = "b"
    Then   handler is not invoked before advancing the foreground scheduler
    And    handler is invoked after advancing by 1 tick
    """
    hub: MessageHub[object] = MessageHub()
    dispatcher = TestDispatcher()
    vm: ComponentVMOf[str] = (
        ComponentVMOf[str].builder().name("vm1").services(hub, dispatcher).model("initial").build()
    )

    seen: list[PropertyChangedMessage[object]] = []
    sub = hub.messages.pipe(
        ops.filter(lambda m: isinstance(m, PropertyChangedMessage) and m.property_name == "model"),
        ops.observe_on(dispatcher.foreground),
    ).subscribe(seen.append)

    # Act: change the model — message is sent synchronously to the hub,
    # but ObserveOn(foreground) defers delivery to the foreground scheduler.
    vm.model = "new"

    # Before advancing the foreground scheduler, handler must not have fired.
    assert len(seen) == 0, "ObserveOn(foreground) must buffer delivery until the scheduler advances"

    # Advance by 1 tick to flush the queued delivery.
    dispatcher.foreground_scheduler.advance_by(1)

    assert len(seen) == 1
    assert seen[0].property_name == "model"

    sub.dispose()
    vm.dispose()


# ---------------------------------------------------------------------------
# THR-002 — Background construct dispatches on background scheduler
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THR-002")
def test_THR_002_background_construct_dispatches_on_background_scheduler() -> None:
    """THR-002: with Background(True), construct() schedules the OnConstruct
    work on dispatcher.Background and returns immediately in the Constructing
    state.  Advancing the background scheduler completes the transition to
    Constructed.

    Python status: FULLY IMPLEMENTED.  _ComponentVMBase.construct() wires
    Background(True) dispatch (see src/vmx/components/base.py lines 268-280):
    it emits Constructing synchronously, then schedules the remaining work on
    self._dispatcher.background.  The full assertion is therefore exercised.
    """
    hub: MessageHub[object] = MessageHub()
    dispatcher = TestDispatcher()
    vm: ComponentVMOf[str] = (
        ComponentVMOf[str]
        .builder()
        .name("vm")
        .services(hub, dispatcher)
        .model("initial")
        .background(True)
        .build()
    )

    vm.construct()

    # construct() returns immediately; the VM is mid-transition (Constructing),
    # NOT yet in the terminal Constructed state.
    assert vm.status == ConstructionStatus.CONSTRUCTING, (
        "Background(True) means OnConstruct() and the final Constructed transition "
        "are scheduled on the background scheduler — only Constructing is emitted synchronously"
    )

    # Advance the background scheduler so the scheduled work runs.
    dispatcher.background_scheduler.advance_by(1)

    assert vm.status == ConstructionStatus.CONSTRUCTED, (
        "after the background scheduler is advanced the transition must complete"
    )

    vm.dispose()


# ---------------------------------------------------------------------------
# THR-003 — CollectionChanged observed on foreground scheduler
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THR-003")
def test_THR_003_collection_changed_observed_on_foreground_scheduler() -> None:
    """THR-003: on_collection_changed with ObserveOn(dispatcher.foreground)
    must buffer delivery until the foreground scheduler is advanced.

    Given  a CompositeVM built with a TestDispatcher
    And    a subscriber to on_collection_changed using ObserveOn(dispatcher.foreground)
    When   composite.append(child) is called
    Then   handler is not invoked before advancing the foreground scheduler
    And    handler is invoked after advancing by 1 tick, with action == "add"
    """
    from vmx.composites.builders import CompositeVMBuilder

    hub: MessageHub[object] = MessageHub()
    dispatcher = TestDispatcher()

    composite: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("root").services(hub, dispatcher).build()
    )
    composite.construct()

    child: ComponentVM = ComponentVM.builder().name("child").services(hub, dispatcher).build()

    observed: list[CollectionChangedEvent] = []
    sub = composite.on_collection_changed.pipe(
        ops.observe_on(dispatcher.foreground),
    ).subscribe(observed.append)

    # Act: add a child — on_collection_changed fires synchronously on the
    # subject, but ObserveOn(foreground) defers delivery.
    composite.append(child)

    # Before advancing the foreground scheduler, no notification delivered.
    assert len(observed) == 0, (
        "ObserveOn(foreground) must buffer delivery until the scheduler advances"
    )

    # Advance foreground by 1 tick to deliver the queued notification.
    dispatcher.foreground_scheduler.advance_by(1)

    assert len(observed) == 1
    assert observed[0].action == "add"
    assert child in observed[0].new_items

    sub.dispose()
    composite.dispose()


# ---------------------------------------------------------------------------
# THR-004 — Subscriber observes on chosen scheduler via ObserveOn
# ---------------------------------------------------------------------------


@pytest.mark.conformance("THR-004")
def test_THR_004_subscriber_observes_on_chosen_scheduler_via_observe_on() -> None:
    """THR-004: hub.Messages.ObserveOn(scheduler) must not invoke the handler
    until the scheduler is advanced, then delivers exactly one message.

    Given  a subscriber to hub.messages using ObserveOn(sched) for any scheduler
    When   hub.send(message) is called
    Then   handler is not invoked before advancing the scheduler
    And    handler is invoked after advancing by 1 tick with the same message
    """
    from vmx.messages.construction_status import ConstructionStatusChangedMessage

    hub: MessageHub[object] = MessageHub()
    sched: TestScheduler = TestScheduler()

    seen: list[object] = []
    sub = hub.messages.pipe(ops.observe_on(sched)).subscribe(seen.append)

    # Send a concrete message (ConstructionStatusChangedMessage is a real IMessage).
    msg = ConstructionStatusChangedMessage.create(
        object(), "thr-004", ConstructionStatus.CONSTRUCTED
    )
    hub.send(msg)

    # Before advancing the scheduler, handler must not yet be invoked.
    assert len(seen) == 0, "ObserveOn(scheduler) must buffer delivery until the scheduler advances"

    # Advance the scheduler by 1 tick to flush.
    sched.advance_by(1)

    assert len(seen) == 1
    assert seen[0] is msg

    sub.dispose()

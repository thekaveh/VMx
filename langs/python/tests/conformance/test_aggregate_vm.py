"""Conformance tests: AGG-001 through AGG-006.

Spec: spec/08-aggregate-vm.md, spec/12-conformance.md §AggregateVM.

AGG-001 — Arity-1 component factory invoked on construct
AGG-002 — Arity-2 both components reach Constructed
AGG-003 — Arity-5 all five components reach Constructed before parent
AGG-004 — ComponentN property change fires on construct
AGG-005 — Arity-2 destruct waits for both children Destructed
AGG-006 — Arity-6 all six components reach Constructed; destruction waits for all
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest

from vmx.aggregates.aggregate_vm import AggregateVM1, AggregateVM2
from vmx.aggregates.builders import (
    AggregateVM1Builder,
    AggregateVM2Builder,
    AggregateVM3Builder,
    AggregateVM4Builder,
    AggregateVM5Builder,
    AggregateVM6Builder,
)
from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.forwarding.component import ForwardingComponentVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[object]:
    return MessageHub()


def _dispatcher() -> RxDispatcher:
    return RxDispatcher.immediate()


def _child(hub: MessageHub[object], dispatcher: RxDispatcher, name: str = "child") -> object:
    return ComponentVMBuilder().name(name).services(hub, dispatcher).build()


class _BlockingDisposeComponent(ComponentVM):
    def __init__(
        self,
        *,
        name: str,
        hub: MessageHub[object],
        dispatcher: RxDispatcher,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(name=name, hint="", hub=hub, dispatcher=dispatcher)
        self._entered = entered
        self._release = release

    def _on_dispose(self) -> None:
        self._entered.set()
        if not self._release.wait(timeout=2):
            raise TimeoutError("test did not release blocked slot disposal")


class _ReentrantDisposeComponent(ComponentVM):
    def __init__(
        self,
        *,
        name: str,
        hub: MessageHub[object],
        dispatcher: RxDispatcher,
        on_dispose: Callable[[], None],
    ) -> None:
        super().__init__(name=name, hint="", hub=hub, dispatcher=dispatcher)
        self._dispose_callback = on_dispose

    def _on_dispose(self) -> None:
        self._dispose_callback()


class _ThrowingDisposeComponent(ComponentVM):
    def _on_dispose(self) -> None:
        raise RuntimeError("first disposal failure")


class _StatusReadBarrierAggregate(AggregateVM1[ComponentVM]):
    """Pause the replacement's terminal check after capturing its value."""

    def __init__(
        self,
        *,
        hub: MessageHub[object],
        dispatcher: RxDispatcher,
        factory: Callable[[], ComponentVM],
        status_read: threading.Event,
        disposal_attempted: threading.Event,
    ) -> None:
        super().__init__(
            name="aggregate",
            hint="",
            hub=hub,
            dispatcher=dispatcher,
            factory1=factory,
        )
        self._pause_status_read = False
        self._status_read = status_read
        self._disposal_attempted = disposal_attempted

    @property
    def status(self) -> ConstructionStatus:
        captured = super().status
        if self._pause_status_read:
            self._pause_status_read = False
            self._status_read.set()
            if not self._disposal_attempted.wait(timeout=2):
                raise TimeoutError("test did not attempt aggregate disposal")
        return captured


# ---------------------------------------------------------------------------
# AGG-001 — Arity-1 component factory invoked on construct
# ---------------------------------------------------------------------------


@pytest.mark.conformance("AGG-001")
def test_AGG_001_arity1_factory_invoked_on_construct() -> None:
    """Given an AggregateVM1 built with .component_1(() => makeVm1())
    When agg.construct() is called
    Then agg.component_1 is populated with the result of makeVm1()
    And agg.component_1.status == Constructed
    """
    hub = _hub()
    dispatcher = _dispatcher()
    factory_call_count = 0

    def make_vm1() -> object:
        nonlocal factory_call_count
        factory_call_count += 1
        return _child(hub, dispatcher, "vm1")

    agg = AggregateVM1Builder().name("agg1").services(hub, dispatcher).component_1(make_vm1).build()

    # Pre-construct: factory must NOT have been called yet (lazy semantics).
    assert agg.component_1 is None, "component_1 must be None before construct()"
    assert factory_call_count == 0, "Factory must not be called before construct()"

    agg.construct()

    assert factory_call_count == 1, "Factory must be called exactly once"
    assert agg.component_1 is not None
    assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]


def test_concurrent_aggregate_reconstruction_reserves_shared_candidate() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    candidate = ComponentVM(name="candidate", hint="", hub=hub, dispatcher=dispatcher)
    factories_ready = threading.Barrier(2)
    disposal_entered = threading.Event()
    release_disposal = threading.Event()

    def aggregate(name: str) -> AggregateVM1[ComponentVM]:
        calls = 0

        def factory() -> ComponentVM:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _BlockingDisposeComponent(
                    name=f"{name}-old",
                    hub=hub,
                    dispatcher=dispatcher,
                    entered=disposal_entered,
                    release=release_disposal,
                )
            factories_ready.wait(timeout=2)
            return candidate

        vm: AggregateVM1[ComponentVM] = (
            AggregateVM1Builder().name(name).services(hub, dispatcher).component_1(factory).build()
        )
        vm.construct()
        return vm

    first = aggregate("first")
    second = aggregate("second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(vm.reconstruct) for vm in (first, second)]
        assert disposal_entered.wait(timeout=2)
        release_disposal.set()
        outcomes = []
        for future in futures:
            try:
                future.result(timeout=2)
                outcomes.append("success")
            except ValueError:
                outcomes.append("rejected")

    assert sorted(outcomes) == ["rejected", "success"]
    owners = [vm for vm in (first, second) if vm.component_1 is candidate]
    assert len(owners) == 1
    assert candidate._ownership_parent is owners[0]._aggregate_parent


# ---------------------------------------------------------------------------
# AGG-002 — Arity-2 both components reach Constructed
# ---------------------------------------------------------------------------


@pytest.mark.conformance("AGG-002")
def test_AGG_002_arity2_both_reach_constructed() -> None:
    """Given an AggregateVM2 in Destructed
    When agg.construct() is called
    Then both agg.component_1.status and agg.component_2.status equal Constructed
    And the aggregate's Status == Constructed
    """
    hub = _hub()
    dispatcher = _dispatcher()

    agg = (
        AggregateVM2Builder()
        .name("agg2")
        .services(hub, dispatcher)
        .component_1(lambda: _child(hub, dispatcher, "vm1"))
        .component_2(lambda: _child(hub, dispatcher, "vm2"))
        .build()
    )

    agg.construct()

    assert agg.component_1 is not None
    assert agg.component_2 is not None
    assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.component_2.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.status == ConstructionStatus.CONSTRUCTED


# ---------------------------------------------------------------------------
# AGG-003 — Arity-5 all five reach Constructed before parent
# ---------------------------------------------------------------------------


@pytest.mark.conformance("AGG-003")
def test_AGG_003_arity5_components_constructed_before_parent() -> None:
    """Given an AggregateVM5 in Destructed
    And a subscriber filtered on ConstructionStatusChangedMessage where Sender == agg
    When agg.construct() is called
    Then the message with Status=Constructed and Sender==agg is observed
    ONLY AFTER every ComponentI.Status has reached Constructed.

    Since the implementation is synchronous (sequential), we verify by recording
    all construction status messages and checking that when the agg's own Constructed
    message is emitted, all children are already Constructed.
    """
    hub = _hub()
    dispatcher = _dispatcher()

    # Build agg first so we can reference it in the subscription
    agg = (
        AggregateVM5Builder()
        .name("agg5")
        .services(hub, dispatcher)
        .component_1(lambda: _child(hub, dispatcher, "c1"))
        .component_2(lambda: _child(hub, dispatcher, "c2"))
        .component_3(lambda: _child(hub, dispatcher, "c3"))
        .component_4(lambda: _child(hub, dispatcher, "c4"))
        .component_5(lambda: _child(hub, dispatcher, "c5"))
        .build()
    )

    # Track child statuses at the moment agg emits its own Constructed message.
    child_statuses_at_agg_constructed: list[ConstructionStatus] = []

    def on_message(msg: object) -> None:
        if (
            isinstance(msg, ConstructionStatusChangedMessage)
            and msg.sender is agg
            and msg.status == ConstructionStatus.CONSTRUCTED
        ):
            # Record each child's status when the agg's own Constructed fires
            for component in [
                agg.component_1,
                agg.component_2,
                agg.component_3,
                agg.component_4,
                agg.component_5,
            ]:
                if component is not None:
                    child_statuses_at_agg_constructed.append(component.status)  # type: ignore[union-attr]

    hub.messages.subscribe(on_message)

    agg.construct()

    # The subscription fires synchronously, so by now we have the snapshot.
    assert len(child_statuses_at_agg_constructed) == 5, (
        "Expected 5 child status snapshots when agg emitted Constructed"
    )
    for status in child_statuses_at_agg_constructed:
        assert status == ConstructionStatus.CONSTRUCTED, (
            f"Child was in {status} when agg emitted Constructed"
        )


# ---------------------------------------------------------------------------
# AGG-004 — ComponentN property change fires on construct
# ---------------------------------------------------------------------------


@pytest.mark.conformance("AGG-004")
def test_AGG_004_component_property_changed_on_construct() -> None:
    """Given an AggregateVM3 in Destructed
    And a subscriber filtered on PropertyChangedMessage
    When agg.construct() is called
    Then three PropertyChangedMessage events with
    PropertyName in {component_1, component_2, component_3} are observed.
    """
    hub = _hub()
    dispatcher = _dispatcher()

    agg = (
        AggregateVM3Builder()
        .name("agg3")
        .services(hub, dispatcher)
        .component_1(lambda: _child(hub, dispatcher, "c1"))
        .component_2(lambda: _child(hub, dispatcher, "c2"))
        .component_3(lambda: _child(hub, dispatcher, "c3"))
        .build()
    )

    slot_changes: list[str] = []

    def on_message(msg: object) -> None:
        if (
            isinstance(msg, PropertyChangedMessage)
            and msg.sender is agg
            and msg.property_name in ("component_1", "component_2", "component_3")
        ):
            slot_changes.append(msg.property_name)

    hub.messages.subscribe(on_message)
    agg.construct()

    assert "component_1" in slot_changes
    assert "component_2" in slot_changes
    assert "component_3" in slot_changes
    assert len(slot_changes) == 3


# ---------------------------------------------------------------------------
# AGG-005 — Arity-2 destruct waits for both children Destructed
# ---------------------------------------------------------------------------


@pytest.mark.conformance("AGG-005")
def test_AGG_005_arity2_destruct_waits_for_all_children() -> None:
    """Given an AggregateVM2 in Constructed
    When agg.destruct() is called
    Then when it returns, agg.component_1.status == Destructed
    AND agg.component_2.status == Destructed
    And agg.status == Destructed
    """
    hub = _hub()
    dispatcher = _dispatcher()

    agg = (
        AggregateVM2Builder()
        .name("agg2")
        .services(hub, dispatcher)
        .component_1(lambda: _child(hub, dispatcher, "vm1"))
        .component_2(lambda: _child(hub, dispatcher, "vm2"))
        .build()
    )

    agg.construct()
    assert agg.status == ConstructionStatus.CONSTRUCTED

    agg.destruct()

    assert agg.component_1 is not None
    assert agg.component_2 is not None
    assert agg.component_1.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.component_2.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.status == ConstructionStatus.DESTRUCTED


# ---------------------------------------------------------------------------
# AGG-006 — Arity-6 all six components reach Constructed; destruction waits for all
# ---------------------------------------------------------------------------


@pytest.mark.conformance("AGG-006")
def test_AGG_006_arity6_construct_and_destruct_all_six() -> None:
    """Given an AggregateVM6 in Destructed
    When agg.construct() is called
    Then when it returns, every component_I.status (I in {1..6}) equals Constructed
    And agg.status == Constructed
    When agg.destruct() is then called
    Then when it returns, every component_I.status equals Destructed
    And agg.status == Destructed
    """
    hub = _hub()
    dispatcher = _dispatcher()

    agg = (
        AggregateVM6Builder()
        .name("agg6")
        .services(hub, dispatcher)
        .component_1(lambda: _child(hub, dispatcher, "c1"))
        .component_2(lambda: _child(hub, dispatcher, "c2"))
        .component_3(lambda: _child(hub, dispatcher, "c3"))
        .component_4(lambda: _child(hub, dispatcher, "c4"))
        .component_5(lambda: _child(hub, dispatcher, "c5"))
        .component_6(lambda: _child(hub, dispatcher, "c6"))
        .build()
    )

    agg.construct()

    assert agg.component_1 is not None
    assert agg.component_2 is not None
    assert agg.component_3 is not None
    assert agg.component_4 is not None
    assert agg.component_5 is not None
    assert agg.component_6 is not None
    assert agg.component_1.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.component_2.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.component_3.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.component_4.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.component_5.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.component_6.status == ConstructionStatus.CONSTRUCTED  # type: ignore[union-attr]
    assert agg.status == ConstructionStatus.CONSTRUCTED

    agg.destruct()

    assert agg.component_1.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.component_2.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.component_3.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.component_4.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.component_5.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.component_6.status == ConstructionStatus.DESTRUCTED  # type: ignore[union-attr]
    assert agg.status == ConstructionStatus.DESTRUCTED


def test_aggregate_rejects_owned_factory_result_without_mutation() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    child = _child(hub, dispatcher)
    composite = (
        CompositeVMBuilder()
        .name("composite")
        .services(hub, dispatcher)
        .children(lambda: [child])
        .build()
    )
    composite.construct()
    aggregate = (
        AggregateVM1Builder()
        .name("aggregate")
        .services(hub, dispatcher)
        .component_1(lambda: child)
        .build()
    )

    with pytest.raises(ValueError, match="already has a parent"):
        aggregate.construct()

    assert composite.snapshot() == (child,)
    assert aggregate.component_1 is None


def test_aggregate_reconstruct_rejects_reentrant_attachment_of_reserved_candidate() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    candidate = ComponentVM(name="candidate", hint="", hub=hub, dispatcher=dispatcher)
    destination = (
        CompositeVMBuilder()
        .name("destination")
        .services(hub, dispatcher)
        .children(lambda: ())
        .build()
    )
    destination.construct()
    admission_errors: list[BaseException] = []
    calls = 0

    def reentrant_admission() -> None:
        try:
            destination.add(candidate)
        except BaseException as error:
            admission_errors.append(error)

    def factory() -> ComponentVM:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _ReentrantDisposeComponent(
                name="old",
                hub=hub,
                dispatcher=dispatcher,
                on_dispose=reentrant_admission,
            )
        return candidate

    aggregate = (
        AggregateVM1Builder()
        .name("aggregate")
        .services(hub, dispatcher)
        .component_1(factory)
        .build()
    )
    aggregate.construct()

    aggregate.reconstruct()

    assert len(admission_errors) == 1
    assert isinstance(admission_errors[0], RuntimeError)
    assert destination.snapshot() == ()
    assert aggregate.component_1 is candidate


@pytest.mark.parametrize("arity", [1, 2])
def test_aggregate_reconstruct_aborts_when_previous_disposal_disposes_parent(
    arity: int,
) -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    candidates = [
        ComponentVM(name=f"candidate-{index}", hint="", hub=hub, dispatcher=dispatcher)
        for index in range(arity)
    ]
    previous: list[ComponentVM] = []
    aggregate: AggregateVM1[ComponentVM] | AggregateVM2[ComponentVM, ComponentVM]
    calls = [0, 0]

    def first_factory() -> ComponentVM:
        calls[0] += 1
        if calls[0] == 1:
            old = _ReentrantDisposeComponent(
                name="old-1",
                hub=hub,
                dispatcher=dispatcher,
                on_dispose=lambda: aggregate.dispose(),
            )
            previous.append(old)
            return old
        return candidates[0]

    def second_factory() -> ComponentVM:
        calls[1] += 1
        if calls[1] == 1:
            old = ComponentVM(name="old-2", hint="", hub=hub, dispatcher=dispatcher)
            previous.append(old)
            return old
        return candidates[1]

    if arity == 1:
        aggregate = (
            AggregateVM1Builder()
            .name("aggregate")
            .services(hub, dispatcher)
            .component_1(first_factory)
            .build()
        )
    else:
        aggregate = (
            AggregateVM2Builder()
            .name("aggregate")
            .services(hub, dispatcher)
            .component_1(first_factory)
            .component_2(second_factory)
            .build()
        )
    aggregate.construct()

    aggregate.reconstruct()

    assert aggregate.status is ConstructionStatus.DISPOSED
    assert aggregate.components() == previous
    assert all(candidate.status is ConstructionStatus.DISPOSED for candidate in candidates)


@pytest.mark.parametrize("reconstruct", [False, True])
def test_aggregate_dispose_cannot_race_fixed_slot_commit(reconstruct: bool) -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    status_read = threading.Event()
    disposal_attempted = threading.Event()
    created: list[ComponentVM] = []

    def factory() -> ComponentVM:
        child = ComponentVM(name=f"child-{len(created)}", hint="", hub=hub, dispatcher=dispatcher)
        created.append(child)
        return child

    aggregate = _StatusReadBarrierAggregate(
        hub=hub,
        dispatcher=dispatcher,
        factory=factory,
        status_read=status_read,
        disposal_attempted=disposal_attempted,
    )
    if reconstruct:
        aggregate.construct()
    aggregate._pause_status_read = True

    operation = aggregate.reconstruct if reconstruct else aggregate.construct
    with ThreadPoolExecutor(max_workers=2) as pool:
        operation_result = pool.submit(operation)
        assert status_read.wait(timeout=2)

        def dispose() -> None:
            disposal_attempted.set()
            aggregate.dispose()

        disposal_result = pool.submit(dispose)
        operation_result.result(timeout=2)
        disposal_result.result(timeout=2)

    candidate = created[-1]
    assert aggregate.status is ConstructionStatus.DISPOSED
    assert candidate.status is ConstructionStatus.DISPOSED


def test_aggregate_reconstruct_cleans_all_slots_and_candidates_after_disposal_failure() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    candidate1 = ComponentVM(name="candidate-1", hint="", hub=hub, dispatcher=dispatcher)
    candidate2 = ComponentVM(name="candidate-2", hint="", hub=hub, dispatcher=dispatcher)
    previous2 = ComponentVM(name="old-2", hint="", hub=hub, dispatcher=dispatcher)
    calls = [0, 0]

    def factory1() -> ComponentVM:
        calls[0] += 1
        if calls[0] == 1:
            return _ThrowingDisposeComponent(name="old-1", hint="", hub=hub, dispatcher=dispatcher)
        return candidate1

    def factory2() -> ComponentVM:
        calls[1] += 1
        return previous2 if calls[1] == 1 else candidate2

    aggregate = (
        AggregateVM2Builder()
        .name("aggregate")
        .services(hub, dispatcher)
        .component_1(factory1)
        .component_2(factory2)
        .build()
    )
    aggregate.construct()
    changes: list[str] = []
    aggregate.property_changed.subscribe(changes.append)

    with pytest.raises(RuntimeError, match="first disposal failure"):
        aggregate.reconstruct()

    assert previous2.status is ConstructionStatus.DISPOSED
    assert aggregate.status is ConstructionStatus.DESTRUCTED
    assert aggregate.component_1 is candidate1
    assert aggregate.component_2 is candidate2
    assert candidate1.status is ConstructionStatus.DESTRUCTED
    assert candidate2.status is ConstructionStatus.DESTRUCTED
    assert candidate1._parent is aggregate._aggregate_parent
    assert candidate2._parent is aggregate._aggregate_parent
    assert [name for name in changes if name.startswith("component_")] == [
        "component_1",
        "component_2",
    ]


def test_aggregate_rejects_forwarding_aliases_of_one_canonical_component() -> None:
    inner = ComponentVMBuilder().name("inner").with_null_services().build()
    first = ForwardingComponentVM(inner)
    second = ForwardingComponentVM(inner)
    aggregate = (
        AggregateVM2Builder()
        .name("aggregate")
        .services(inner.hub, RxDispatcher.immediate())
        .component_1(lambda: first)
        .component_2(lambda: second)
        .build()
    )

    with pytest.raises(ValueError, match="same canonical component identity"):
        aggregate.construct()

    assert aggregate.component_1 is None
    assert aggregate.component_2 is None


def test_aggregate_reconstruct_rejects_current_slot_without_disposing_it() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    child = _child(hub, dispatcher)
    aggregate = (
        AggregateVM1Builder()
        .name("aggregate")
        .services(hub, dispatcher)
        .component_1(lambda: child)
        .build()
    )
    aggregate.construct()

    with pytest.raises(ValueError, match="already has a parent"):
        aggregate.reconstruct()

    assert aggregate.component_1 is child
    assert child.status is ConstructionStatus.DESTRUCTED  # type: ignore[attr-defined]
    assert child._ownership_parent is not None  # type: ignore[attr-defined]


def test_aggregate_rejects_forwarding_alias_of_owned_component() -> None:
    inner = ComponentVMBuilder().name("inner").with_null_services().build()
    composite = (
        CompositeVMBuilder()
        .name("composite")
        .services(inner.hub, RxDispatcher.immediate())
        .children(lambda: (inner,))
        .build()
    )
    composite.construct()
    aggregate = (
        AggregateVM1Builder()
        .name("aggregate")
        .services(inner.hub, RxDispatcher.immediate())
        .component_1(lambda: ForwardingComponentVM(inner))
        .build()
    )

    with pytest.raises(ValueError, match="already has a parent"):
        aggregate.construct()

    assert composite.snapshot() == (inner,)
    assert aggregate.component_1 is None


def test_fixed_aggregate_slot_cannot_transfer_to_mutable_parent() -> None:
    hub = _hub()
    dispatcher = _dispatcher()
    child = _child(hub, dispatcher)
    aggregate = (
        AggregateVM1Builder()
        .name("aggregate")
        .services(hub, dispatcher)
        .component_1(lambda: child)
        .build()
    )
    aggregate.construct()
    composite = (
        CompositeVMBuilder()
        .name("composite")
        .services(hub, dispatcher)
        .children(lambda: ())
        .build()
    )
    composite.construct()

    with pytest.raises(ValueError, match="fixed aggregate slot"):
        composite.add(child)

    assert aggregate.component_1 is child
    assert composite.snapshot() == ()


# ---------------------------------------------------------------------------
# LIFE-013 (AggregateVM) — depth-first dispose ordering across arities 1..6
# Sibling of test_composite_vm.py::test_LIFE_013_dispose_cascades_depth_first.
# ---------------------------------------------------------------------------


_BUILDERS = {
    1: AggregateVM1Builder,
    2: AggregateVM2Builder,
    3: AggregateVM3Builder,
    4: AggregateVM4Builder,
    5: AggregateVM5Builder,
    6: AggregateVM6Builder,
}


def _build_aggregate(arity: int, hub: MessageHub[object], dispatcher: RxDispatcher) -> object:
    # AggregateVMBuilderN is immutable — every setter returns a new builder, so
    # the chained result must be reassigned each iteration.
    builder = _BUILDERS[arity]().name(f"agg{arity}").services(hub, dispatcher)
    for n in range(1, arity + 1):
        setter = getattr(builder, f"component_{n}")
        builder = setter(lambda i=n: _child(hub, dispatcher, f"c{i}"))
    return builder.build()


@pytest.mark.parametrize("arity", [1, 2, 3, 4, 5, 6])
@pytest.mark.conformance("LIFE-013")
def test_LIFE_013_aggregate_dispose_children_before_parent(arity: int) -> None:
    """LIFE-013 for AggregateVMN: dispose disposes every component slot
    BEFORE the aggregate itself. Subscribers observe child Disposed
    transitions strictly before the aggregate's own Disposed transition —
    a single dispose-ordering rule across all aggregate arities and across
    all four flavors (mirrors C# / TS / Swift)."""
    hub = _hub()
    dispatcher = _dispatcher()

    disposal_order: list[str] = []
    hub.messages.subscribe(
        lambda m: (
            disposal_order.append(m.sender_name)
            if isinstance(m, ConstructionStatusChangedMessage)
            and m.status == ConstructionStatus.DISPOSED
            else None
        )
    )

    agg = _build_aggregate(arity, hub, dispatcher)
    agg.construct()  # type: ignore[attr-defined]

    agg.dispose()  # type: ignore[attr-defined]

    for n in range(1, arity + 1):
        assert f"c{n}" in disposal_order, f"slot c{n} must reach Disposed"
        assert disposal_order.index(f"c{n}") < disposal_order.index(f"agg{arity}"), (
            f"c{n} must be Disposed before agg{arity} (LIFE-013)"
        )

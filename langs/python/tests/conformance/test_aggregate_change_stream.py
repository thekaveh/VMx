"""Conformance tests for the dynamic aggregate change stream (AGCH-001..010)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
import reactivex as rx
from reactivex import Observable
from reactivex.abc import DisposableBase, ObserverBase, SchedulerBase
from reactivex.disposable import Disposable

from vmx import (
    AggregateChange,
    AggregateChangeReason,
    AggregateChangeStream,
    ComponentVMBuilder,
    CompositeVMBuilder,
    GroupVMBuilder,
    KeyedServicedObservableCollection,
    MessageHub,
    RxDispatcher,
    ServicedObservableCollection,
)


class BodyError(Exception):
    pass


class DeliveryError(Exception):
    pass


class SelectorError(Exception):
    pass


class SubscriptionError(Exception):
    pass


class _FailingSelectedStream:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def subscribe(self, *args: object, **kwargs: object) -> DisposableBase:
        del args, kwargs
        raise self._error


@dataclass(eq=True)
class Item:
    name: str

    def __post_init__(self) -> None:
        self.changes = CountedChanges()
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1


class CountedChanges:
    def __init__(self) -> None:
        self.subscribe_count = 0
        self.dispose_count = 0
        self.emit_on_subscribe = False
        self.emit_from_background_on_subscribe = False
        self.before_background_emit: Callable[[], None] | None = None
        self.background_thread: threading.Thread | None = None
        self._observers: list[ObserverBase[object]] = []

    @property
    def observable(self) -> Observable[object]:
        def subscribe(
            observer: ObserverBase[object], scheduler: SchedulerBase | None = None
        ) -> DisposableBase:
            del scheduler
            self.subscribe_count += 1
            self._observers.append(observer)
            if self.emit_on_subscribe:
                observer.on_next(object())
            if self.emit_from_background_on_subscribe:
                if self.before_background_emit is not None:
                    self.before_background_emit()
                started = threading.Event()

                def emit_from_background() -> None:
                    started.set()
                    observer.on_next(object())

                self.background_thread = threading.Thread(target=emit_from_background)
                self.background_thread.start()
                assert started.wait(timeout=5)
                # Release the GIL so the callback reaches the aggregate gate
                # while construction/reconciliation still owns it.
                time.sleep(0.01)

            disposed = False

            def dispose() -> None:
                nonlocal disposed
                if disposed:
                    return
                disposed = True
                self.dispose_count += 1

            return Disposable(dispose)

        return rx.create(subscribe)

    def emit(self) -> None:
        for observer in tuple(self._observers):
            observer.on_next(object())

    def complete(self) -> None:
        for observer in tuple(self._observers):
            observer.on_completed()

    def error(self, error: Exception) -> None:
        for observer in tuple(self._observers):
            observer.on_error(error)


class _TestSource:
    def __init__(self, *items: Item | None) -> None:
        self.items = list(items)
        self.handlers: list[Callable[[], None]] = []
        self.snapshot_count = 0
        self.snapshot_override: Callable[[], tuple[Item | None, ...]] | None = None
        self.callback_target: object | None = None

    def snapshot(self) -> tuple[Item | None, ...]:
        self.snapshot_count += 1
        if self.snapshot_override is not None:
            return self.snapshot_override()
        return tuple(self.items)

    def subscribe_membership(self, callback: Callable[[], None]) -> DisposableBase:
        self.callback_target = getattr(callback, "__self__", None)
        self.handlers.append(callback)
        return Disposable(
            lambda: self.handlers.remove(callback) if callback in self.handlers else None
        )

    def pulse(self) -> None:
        for handler in tuple(self.handlers):
            handler()

    def add(self, item: Item | None) -> None:
        self.items.append(item)
        self.pulse()

    def remove(self, item: Item) -> None:
        for index, current in enumerate(self.items):
            if current is item:
                del self.items[index]
                break
        self.pulse()

    def move(self, old_index: int, new_index: int) -> None:
        self.items.insert(new_index, self.items.pop(old_index))
        self.pulse()


def aggregate(source: Any) -> AggregateChangeStream[Item]:
    return AggregateChangeStream(source, lambda item: item.changes.observable)


@pytest.mark.conformance("AGCH-001")
def test_AGCH_001_initial_is_atomic_subscriber_local_and_has_no_replay() -> None:
    first = Item("first")
    source = _TestSource(first)
    sut = aggregate(source)
    plain: list[AggregateChange[Item]] = []
    seeded: list[AggregateChange[Item]] = []
    sut.observe().subscribe(plain.append)

    def receive(change: AggregateChange[Item]) -> None:
        seeded.append(change)
        if change.reason is AggregateChangeReason.INITIAL:
            source.add(Item("racing"))

    sut.observe(emit_initial=True).subscribe(receive)

    assert [change.reason for change in seeded] == [
        AggregateChangeReason.INITIAL,
        AggregateChangeReason.MEMBERSHIP,
    ]
    assert [change.reason for change in plain] == [AggregateChangeReason.MEMBERSHIP]
    sut.dispose()


@pytest.mark.conformance("AGCH-002")
def test_AGCH_002_setup_race_reconciles_and_later_staging_follows_membership() -> None:
    first, raced = Item("first"), Item("raced")
    source = _TestSource(first)
    race_once = True

    def snapshot() -> tuple[Item | None, ...]:
        nonlocal race_once
        value = tuple(source.items)
        if race_once:
            race_once = False
            source.items.append(raced)
            source.pulse()
        return value

    source.snapshot_override = snapshot
    sut = aggregate(source)
    assert source.snapshot_count == 2
    assert first.changes.subscribe_count == raced.changes.subscribe_count == 1

    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)
    synchronous = Item("synchronous")
    synchronous.changes.emit_on_subscribe = True
    source.add(synchronous)
    assert [change.reason for change in observed] == [
        AggregateChangeReason.MEMBERSHIP,
        AggregateChangeReason.ITEM,
    ]
    assert observed[1].item is synchronous
    sut.dispose()

    blocked_first, blocked_raced = Item("blocked-first"), Item("blocked-raced")
    blocked_source = _TestSource(blocked_first)
    blocked_observed: list[AggregateChange[Item]] = []
    blocked_subscription: DisposableBase | None = None
    pulse_thread: threading.Thread | None = None
    run_blocked_race = True

    def blocked_snapshot() -> tuple[Item | None, ...]:
        nonlocal blocked_subscription, pulse_thread, run_blocked_race
        value = tuple(blocked_source.items)
        if run_blocked_race:
            run_blocked_race = False
            constructing = blocked_source.callback_target
            blocked_subscription = constructing.observe().subscribe(  # type: ignore[union-attr]
                blocked_observed.append
            )
            blocked_source.items.append(blocked_raced)
            pulse_thread = threading.Thread(target=blocked_source.pulse)
            pulse_thread.start()
            deadline = time.monotonic() + 5
            aggregate_target = blocked_source.callback_target
            while (
                getattr(aggregate_target, "_structural_version", 0) == 0
                and time.monotonic() < deadline
            ):
                time.sleep(0.001)
            assert getattr(aggregate_target, "_structural_version", 0) == 1
        return value

    blocked_source.snapshot_override = blocked_snapshot
    blocked_aggregate = aggregate(blocked_source)
    assert pulse_thread is not None and pulse_thread.join(timeout=5) is None
    assert blocked_raced.changes.subscribe_count == 1
    assert blocked_observed == []
    assert blocked_subscription is not None
    blocked_subscription.dispose()
    blocked_aggregate.dispose()

    setup_item = Item("setup-item")
    setup_source = _TestSource(setup_item)
    setup_observed: list[AggregateChange[Item]] = []
    setup_subscription: DisposableBase | None = None

    def subscribe_during_setup() -> None:
        nonlocal setup_subscription
        constructing = setup_source.callback_target
        setup_subscription = constructing.observe().subscribe(  # type: ignore[union-attr]
            setup_observed.append
        )

    setup_item.changes.before_background_emit = subscribe_during_setup
    setup_item.changes.emit_from_background_on_subscribe = True
    setup_aggregate = aggregate(setup_source)
    setup_thread = setup_item.changes.background_thread
    assert setup_thread is not None and setup_thread.join(timeout=5) is None
    assert setup_observed == []
    assert setup_subscription is not None
    setup_subscription.dispose()
    setup_aggregate.dispose()

    post_item = Item("post-item")
    post_item.changes.emit_from_background_on_subscribe = True
    post_observed: list[AggregateChange[Item]] = []
    post_source = _TestSource()
    post_aggregate = aggregate(post_source)
    post_aggregate.observe().subscribe(post_observed.append)
    post_source.add(post_item)
    post_thread = post_item.changes.background_thread
    assert post_thread is not None and post_thread.join(timeout=5) is None
    assert [change.reason for change in post_observed] == [
        AggregateChangeReason.MEMBERSHIP,
        AggregateChangeReason.ITEM,
    ]
    post_aggregate.dispose()


@pytest.mark.conformance("AGCH-003")
def test_AGCH_003_selected_change_carries_identical_current_member() -> None:
    item = Item("nested")
    sut = aggregate(_TestSource(item))
    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)
    item.changes.emit()
    assert len(observed) == 1
    assert observed[0].reason is AggregateChangeReason.ITEM
    assert observed[0].item is item
    sut.dispose()


@pytest.mark.conformance("AGCH-004")
def test_AGCH_004_terminal_epoch_stays_silent_until_final_remove_and_readd() -> None:
    first, second = Item("first"), Item("second")
    source = ServicedObservableCollection[Item]()
    source.extend((first, second))
    sut = aggregate(source)
    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)

    first.changes.complete()
    second.changes.error(RuntimeError("selected"))
    first.changes.emit()
    second.changes.emit()
    assert observed == []
    source.move(0, 1)
    source.replace_all((second, first))
    source.append(first)
    assert first.changes.subscribe_count == second.changes.subscribe_count == 1
    source.remove(first)
    source.remove(first)
    source.append(first)
    assert first.changes.subscribe_count == 2
    first.changes.emit()
    assert observed[-1].item is first
    sut.dispose()


@pytest.mark.conformance("AGCH-005")
def test_AGCH_005_keyed_reset_rebuilds_transactionally_and_retains_identity() -> None:
    first, retained, added = Item("first"), Item("retained"), Item("added")
    source = KeyedServicedObservableCollection[str, Item](lambda item: item.name)
    source.extend((first, retained))
    sut = aggregate(source)
    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)
    source.replace_all((retained, added))
    assert [change.reason for change in observed] == [AggregateChangeReason.MEMBERSHIP]
    assert first.changes.dispose_count == 1
    assert retained.changes.subscribe_count == added.changes.subscribe_count == 1
    added.changes.emit()
    assert observed[-1].item is added
    sut.dispose()


@pytest.mark.conformance("AGCH-006")
def test_AGCH_006_equal_distinct_items_and_duplicate_identity_use_reference_rules() -> None:
    duplicate = Item("same")
    equal_but_distinct = Item("same")
    source = _TestSource(duplicate, duplicate, equal_but_distinct)
    sut = aggregate(source)
    assert duplicate.changes.subscribe_count == equal_but_distinct.changes.subscribe_count == 1
    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)
    duplicate.changes.emit()
    assert sum(change.reason is AggregateChangeReason.ITEM for change in observed) == 1
    source.remove(duplicate)
    assert duplicate.changes.dispose_count == 0
    source.remove(duplicate)
    assert duplicate.changes.dispose_count == 1
    sut.dispose()


@pytest.mark.conformance("AGCH-007")
def test_AGCH_007_nested_exceptional_batch_emits_once_and_preserves_body_error() -> None:
    item = Item("item")
    source = _TestSource(item)
    sut = aggregate(source)
    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)

    def fail_on_batch(change: AggregateChange[Item]) -> None:
        if change.reason is AggregateChangeReason.BATCH:
            raise DeliveryError

    sut.observe().subscribe(fail_on_batch)
    with pytest.raises(BodyError):
        with sut.batch():
            with sut.batch():
                source.add(Item("added"))
                item.changes.emit()
                raise BodyError

    assert [change.reason for change in observed] == [AggregateChangeReason.BATCH]
    source.remove(item)
    assert observed[-1].reason is AggregateChangeReason.MEMBERSHIP
    with pytest.raises(DeliveryError):
        with sut.batch():
            source.items[0].changes.emit()  # type: ignore[union-attr]
    sut.dispose()


@pytest.mark.conformance("AGCH-008")
def test_AGCH_008_empty_batch_and_move_are_stable_and_all_sources_adapt() -> None:
    first, second = Item("first"), Item("second")
    source = _TestSource(first, second)
    sut = aggregate(source)
    observed: list[AggregateChange[Item]] = []
    sut.observe().subscribe(observed.append)
    with sut.batch():
        pass
    assert observed == []
    source.move(0, 1)
    assert [change.reason for change in observed] == [AggregateChangeReason.MEMBERSHIP]
    assert first.changes.subscribe_count == 1
    assert first.changes.dispose_count == 0

    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    child = ComponentVMBuilder().name("child").services(hub, dispatcher).build()
    composite = (
        CompositeVMBuilder()
        .name("composite")
        .services(hub, dispatcher)
        .children(lambda: ())
        .build()
    )
    group = GroupVMBuilder().name("group").services(hub, dispatcher).children(lambda: ()).build()
    for container in (composite, group):
        pulses = 0

        def count_pulse() -> None:
            nonlocal pulses
            pulses += 1

        subscription = container.subscribe_membership(count_pulse)
        container.append(child)
        assert container.snapshot() == (child,)
        container.remove(child)
        assert pulses == 2
        subscription.dispose()
    sut.dispose()

    pending_item = Item("pending-item")
    pending_source = _TestSource(pending_item)
    pending = aggregate(pending_source)
    pending_observed: list[AggregateChange[Item]] = []
    run_reentrant_batch = True

    def receive_pending(change: AggregateChange[Item]) -> None:
        nonlocal run_reentrant_batch
        pending_observed.append(change)
        if run_reentrant_batch and change.reason is AggregateChangeReason.ITEM:
            run_reentrant_batch = False
            with pending.batch():
                pending_source.add(Item("pending-added"))

    pending.observe().subscribe(receive_pending)
    pending_item.changes.emit()
    assert [change.reason for change in pending_observed] == [
        AggregateChangeReason.ITEM,
        AggregateChangeReason.BATCH,
    ]
    pending_observed.clear()
    with pending.batch():
        pass
    assert pending_observed == []
    pending.dispose()

    recipient_item = Item("recipient-item")
    recipient_source = _TestSource(recipient_item)
    recipient_aggregate = aggregate(recipient_source)
    early_changes: list[AggregateChange[Item]] = []
    late_changes: list[AggregateChange[Item]] = []
    recipient_aggregate.observe().subscribe(early_changes.append)
    with recipient_aggregate.batch():
        recipient_item.changes.emit()
        recipient_aggregate.observe().subscribe(late_changes.append)
    assert [change.reason for change in early_changes] == [AggregateChangeReason.BATCH]
    assert late_changes == []
    recipient_aggregate.dispose()

    union_item = Item("union-item")
    union_source = _TestSource(union_item)
    union_aggregate = aggregate(union_source)
    union_early: list[AggregateChange[Item]] = []
    union_late: list[AggregateChange[Item]] = []
    union_aggregate.observe().subscribe(union_early.append)
    with union_aggregate.batch():
        union_item.changes.emit()
        union_aggregate.observe().subscribe(union_late.append)
        union_item.changes.emit()
    assert [change.reason for change in union_early] == [AggregateChangeReason.BATCH]
    assert [change.reason for change in union_late] == [AggregateChangeReason.BATCH]
    union_aggregate.dispose()

    inactive_item = Item("inactive-item")
    inactive_aggregate = aggregate(_TestSource(inactive_item))
    inactive_changes: list[AggregateChange[Item]] = []
    inactive_subscription = inactive_aggregate.observe().subscribe(inactive_changes.append)
    with inactive_aggregate.batch():
        inactive_item.changes.emit()
        inactive_subscription.dispose()
    assert inactive_changes == []
    inactive_aggregate.dispose()


@pytest.mark.conformance("AGCH-009")
def test_AGCH_009_reentrant_work_is_fifo_and_readd_gets_a_fresh_epoch() -> None:
    item = Item("item")
    source = _TestSource(item)
    sut = aggregate(source)
    observed: list[AggregateChange[Item]] = []

    def receive(change: AggregateChange[Item]) -> None:
        observed.append(change)
        if change.reason is AggregateChangeReason.ITEM and source.items:
            source.remove(item)
            item.changes.emit()

    sut.observe().subscribe(receive)
    item.changes.emit()
    assert [change.reason for change in observed] == [
        AggregateChangeReason.ITEM,
        AggregateChangeReason.MEMBERSHIP,
    ]
    source.add(item)
    assert item.changes.subscribe_count == 2
    item.changes.emit()
    assert sum(change.reason is AggregateChangeReason.ITEM for change in observed) == 2
    sut.dispose()


@pytest.mark.conformance("AGCH-010")
def test_AGCH_010_failures_disposal_ownership_and_observer_recovery_are_bounded() -> None:
    null_source = _TestSource(None)
    with pytest.raises(ValueError):
        aggregate(null_source)
    assert null_source.handlers == []

    valid, bad = Item("valid"), Item("bad")
    construction_source = _TestSource(valid, bad)
    with pytest.raises(SelectorError):
        AggregateChangeStream(
            construction_source,
            lambda item: (_ for _ in ()).throw(SelectorError())
            if item is bad
            else item.changes.observable,
        )
    assert construction_source.handlers == []
    assert valid.changes.dispose_count == 1

    staged, subscription_bad = Item("staged"), Item("subscription-bad")
    subscription_source = _TestSource(staged, subscription_bad)
    subscription_error = SubscriptionError()
    with pytest.raises(SubscriptionError) as raised_subscription_error:
        AggregateChangeStream(
            subscription_source,
            lambda item: _FailingSelectedStream(  # type: ignore[return-value]
                subscription_error
            )
            if item is subscription_bad
            else item.changes.observable,
        )
    assert raised_subscription_error.value is subscription_error
    assert subscription_source.handlers == []
    assert staged.changes.dispose_count == 1

    later_valid, later_bad = Item("later-valid"), Item("later-bad")
    later_source = _TestSource(later_valid)
    later = AggregateChangeStream(
        later_source,
        lambda item: (_ for _ in ()).throw(SelectorError())
        if item is later_bad
        else item.changes.observable,
    )
    errors: list[Exception] = []
    later.observe().subscribe(on_next=lambda _: None, on_error=errors.append)
    later_source.add(later_bad)
    assert len(errors) == 1 and isinstance(errors[0], SelectorError)
    assert later_source.handlers == []
    assert later_valid.changes.dispose_count == 1
    later.dispose()

    component_hub: MessageHub[object] = MessageHub()
    component = (
        ComponentVMBuilder()
        .name("component")
        .services(component_hub, RxDispatcher.immediate())
        .build()
    )
    components = ServicedObservableCollection[Any]()
    components.append(component)
    component_aggregate = AggregateChangeStream.for_components(components)
    component_changes: list[AggregateChange[Any]] = []
    completions = 0

    def complete() -> None:
        nonlocal completions
        completions += 1

    component_aggregate.observe().subscribe(component_changes.append, on_completed=complete)
    component.construct()
    assert any(change.item is component for change in component_changes)
    component_aggregate.dispose()
    component_aggregate.dispose()
    assert completions == 1
    assert component.status.value != "Disposed"

    recovery_item = Item("recovery")
    recovery_source = _TestSource(recovery_item)
    recovery = aggregate(recovery_source)
    safe: list[AggregateChange[Item]] = []
    throw_once = True

    def failing(change: AggregateChange[Item]) -> None:
        nonlocal throw_once
        if throw_once and change.reason is AggregateChangeReason.ITEM:
            throw_once = False
            recovery_source.add(Item("reentrant"))
            raise DeliveryError

    recovery.observe().subscribe(failing)
    recovery.observe().subscribe(safe.append)
    with pytest.raises(DeliveryError):
        recovery_item.changes.emit()
    recovery_source.items[-1].changes.emit()  # type: ignore[union-attr]
    assert any(change.reason is AggregateChangeReason.ITEM for change in safe)
    recovery.dispose()

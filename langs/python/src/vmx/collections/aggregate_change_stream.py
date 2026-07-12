"""Dynamic aggregate observation over live collection membership."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar, cast

import reactivex as rx
from reactivex import Observable
from reactivex.abc import DisposableBase, ObserverBase, SchedulerBase
from reactivex.disposable import Disposable

from vmx.collections.observable_membership import ObservableMembershipSource
from vmx.components.protocols import ComponentVMProto

T = TypeVar("T")
TComponent = TypeVar("TComponent", bound=ComponentVMProto)


class AggregateChangeReason(str, Enum):
    """Provenance for one aggregate notification."""

    INITIAL = "initial"
    MEMBERSHIP = "membership"
    ITEM = "item"
    BATCH = "batch"


@dataclass(frozen=True)
class AggregateChange(Generic[T]):
    """A provenance-only aggregate notification."""

    reason: AggregateChangeReason
    item: T | None = None


@dataclass
class _Entry(Generic[T]):
    item: T
    epoch: int
    refcount: int
    subscription: DisposableBase | None = None
    admitted: bool = False
    terminal: bool = False
    buffered_items: int = 0


@dataclass
class _Registration(Generic[T]):
    observer: ObserverBase[AggregateChange[T]]
    active: bool = True


@dataclass
class _PendingChange(Generic[T]):
    change: AggregateChange[T]
    entry: _Entry[T] | None = None
    epoch: int = 0


@dataclass
class _Work(Generic[T]):
    kind: str
    recipients: tuple[_Registration[T], ...] = ()
    coalesced: bool = False
    change: AggregateChange[T] | None = None
    entry: _Entry[T] | None = None
    epoch: int = 0
    error: Exception | None = None


@dataclass
class _SnapshotPlan(Generic[T]):
    counts: dict[int, tuple[T, int]]
    staged: list[_Entry[T]]


class AggregateChangeStream(Generic[T]):
    """Fan in selected changes from every distinct current member.

    Membership identity is ``id(item)`` and each entry retains a strong item
    reference for its entire admitted epoch.
    """

    def __init__(
        self,
        source: ObservableMembershipSource[T],
        observe_item: Callable[[T], Observable[object]],
    ) -> None:
        if source is None:
            raise TypeError("source cannot be None")
        if observe_item is None:
            raise TypeError("observe_item cannot be None")

        self._source = source
        self._observe_item = observe_item
        self._gate = threading.RLock()
        self._version_gate = threading.Lock()
        self._structural_version = 0
        self._setting_up = True
        self._entries: dict[int, _Entry[T]] = {}
        self._registrations: list[_Registration[T]] = []
        self._work: deque[_Work[T]] = deque()
        self._membership_subscription: DisposableBase | None = None
        self._next_epoch = 0
        self._processing = False
        self._completed = False
        self._terminal_error: Exception | None = None
        self._batch_depth = 0
        self._batch_dirty = False

        with self._gate:
            try:
                self._membership_subscription = source.subscribe_membership(
                    self._on_membership_changed
                )
                self._initialize_locked()
            except BaseException:
                self._fail_construction_locked()
                raise

    def observe(self, emit_initial: bool = False) -> Observable[AggregateChange[T]]:
        """Return the hot output with an optional atomic subscriber-local seed."""

        def subscribe(
            observer: ObserverBase[AggregateChange[T]],
            scheduler: SchedulerBase | None = None,
        ) -> DisposableBase:
            del scheduler
            return self._subscribe(observer, emit_initial)

        return rx.create(subscribe)

    @contextmanager
    def batch(self) -> Generator[None, None, None]:
        """Coalesce changes admitted inside nested scopes into one batch event."""
        with self._gate:
            if self._completed or self._terminal_error is not None:
                raise RuntimeError("AggregateChangeStream is no longer active")
            self._batch_depth += 1

        try:
            yield
        except BaseException:
            try:
                self._exit_batch()
            except BaseException:
                pass
            raise
        else:
            self._exit_batch()

    def dispose(self) -> None:
        """Detach owned subscriptions and complete output, idempotently."""
        start = False
        with self._gate:
            if self._completed or self._terminal_error is not None:
                return
            self._completed = True
            self._cleanup_subscriptions_locked()
            self._work.clear()
            recipients = self._current_registrations_locked()
            self._registrations.clear()
            if recipients:
                self._work.append(_Work("completion", recipients=recipients))
            start = self._start_processing_locked()
        if start:
            self._process_work()

    @staticmethod
    def for_components(
        source: ObservableMembershipSource[TComponent],
    ) -> AggregateChangeStream[TComponent]:
        """Observe the standard component ``property_changed`` stream."""
        return AggregateChangeStream(source, lambda item: item.property_changed)

    def _initialize_locked(self) -> None:
        while True:
            version = self._read_structural_version()
            snapshot = self._validated_snapshot()
            if version != self._read_structural_version():
                continue
            plan = self._build_plan(snapshot)
            try:
                self._stage_new_entries_locked(plan)
            except BaseException:
                self._dispose_staged_locked(plan)
                raise
            if version != self._read_structural_version():
                self._dispose_staged_locked(plan)
                continue
            self._commit_plan_locked(plan)
            if version != self._read_structural_version():
                continue
            self._discard_buffered_items_locked()
            with self._version_gate:
                if version != self._structural_version:
                    continue
                self._setting_up = False
                return

    def _on_membership_changed(self) -> None:
        with self._version_gate:
            self._structural_version += 1
            setup_activity = self._setting_up

        start = False
        with self._gate:
            if self._completed or self._terminal_error is not None or setup_activity:
                return
            coalesced = self._batch_depth > 0
            if coalesced:
                self._batch_dirty = True
            self._work.append(
                _Work(
                    "structural",
                    recipients=self._current_registrations_locked(),
                    coalesced=coalesced,
                )
            )
            start = self._start_processing_locked()
        if start:
            self._process_work()

    def _on_item(self, entry: _Entry[T]) -> None:
        # Capture setup classification before taking the aggregate gate. A
        # background callback begun during construction may block on that gate
        # until setup ends, but it remains pre-existing state and is discarded.
        with self._version_gate:
            setup_activity = self._setting_up
        start = False
        with self._gate:
            if self._completed or self._terminal_error is not None or entry.terminal:
                return
            if setup_activity:
                return
            if not entry.admitted:
                entry.buffered_items += 1
                return
            coalesced = self._batch_depth > 0
            if coalesced:
                self._batch_dirty = True
            self._work.append(
                _Work(
                    "item",
                    recipients=self._current_registrations_locked(),
                    coalesced=coalesced,
                    entry=entry,
                    epoch=entry.epoch,
                )
            )
            start = self._start_processing_locked()
        if start:
            self._process_work()

    def _on_item_terminal(self, entry: _Entry[T]) -> None:
        with self._gate:
            if self._completed or self._terminal_error is not None or entry.terminal:
                return
            entry.terminal = True
            entry.buffered_items = 0
            self._safe_dispose(entry.subscription)
            entry.subscription = None

    def _process_work(self) -> None:
        first_delivery_error: BaseException | None = None
        while True:
            current: _Work[T] | None = None
            with self._gate:
                if not self._work:
                    self._processing = False
                    break
                current = self._work.popleft()
                if current.kind == "structural":
                    self._process_structural_locked(current)
                    continue
                if current.kind == "item":
                    self._process_item_locked(current)
                    continue

            if not self._admit_guarded_delivery(current):
                continue
            try:
                self._deliver(current)
            except BaseException as error:
                if first_delivery_error is None:
                    first_delivery_error = error
        if first_delivery_error is not None:
            raise first_delivery_error

    def _process_structural_locked(self, work: _Work[T]) -> None:
        if self._completed or self._terminal_error is not None:
            return
        try:
            while True:
                version = self._read_structural_version()
                snapshot = self._validated_snapshot()
                if version != self._read_structural_version():
                    continue
                plan = self._build_plan(snapshot)
                try:
                    self._stage_new_entries_locked(plan)
                except BaseException:
                    self._dispose_staged_locked(plan)
                    raise
                if version != self._read_structural_version():
                    self._dispose_staged_locked(plan)
                    continue
                self._commit_plan_locked(plan)
                if version != self._read_structural_version():
                    continue
                changes: list[_PendingChange[T]] = [
                    _PendingChange(AggregateChange(AggregateChangeReason.MEMBERSHIP))
                ]
                self._append_buffered_items_locked(changes)
                self._prepend_changes_locked(changes, work.coalesced, work.recipients)
                return
        except Exception as error:
            self._fail_existing_locked(error)

    def _process_item_locked(self, work: _Work[T]) -> None:
        entry = cast(_Entry[T], work.entry)
        if (
            self._completed
            or self._terminal_error is not None
            or not entry.admitted
            or entry.terminal
            or entry.epoch != work.epoch
            or entry.refcount == 0
        ):
            return
        self._prepend_changes_locked(
            [
                _PendingChange(
                    AggregateChange(AggregateChangeReason.ITEM, entry.item),
                    entry,
                    work.epoch,
                )
            ],
            work.coalesced,
            work.recipients,
        )

    def _validated_snapshot(self) -> tuple[T, ...]:
        snapshot = self._source.snapshot()
        if snapshot is None:
            raise ValueError("membership source returned no snapshot")
        values = tuple(snapshot)
        if any(item is None for item in values):
            raise ValueError("membership snapshots cannot contain None")
        return values

    @staticmethod
    def _build_plan(snapshot: tuple[T, ...]) -> _SnapshotPlan[T]:
        counts: dict[int, tuple[T, int]] = {}
        for item in snapshot:
            identity = id(item)
            previous = counts.get(identity)
            counts[identity] = (item, 1 if previous is None else previous[1] + 1)
        return _SnapshotPlan(counts, [])

    def _stage_new_entries_locked(self, plan: _SnapshotPlan[T]) -> None:
        for identity, (item, count) in plan.counts.items():
            if identity in self._entries:
                continue
            self._next_epoch += 1
            entry = _Entry(item, self._next_epoch, count)
            selected = self._observe_item(item)
            if selected is None:
                raise ValueError("observe_item returned None")

            def on_next(_value: object, current: _Entry[T] = entry) -> None:
                self._on_item(current)

            def on_error(_error: Exception, current: _Entry[T] = entry) -> None:
                self._on_item_terminal(current)

            def on_completed(current: _Entry[T] = entry) -> None:
                self._on_item_terminal(current)

            subscription = selected.subscribe(
                on_next=on_next,
                on_error=on_error,
                on_completed=on_completed,
            )
            if subscription is None:
                raise ValueError("selected stream returned no subscription")
            entry.subscription = subscription
            if entry.terminal:
                self._safe_dispose(entry.subscription)
                entry.subscription = None
            plan.staged.append(entry)

    def _commit_plan_locked(self, plan: _SnapshotPlan[T]) -> None:
        for identity, existing in tuple(self._entries.items()):
            membership = plan.counts.get(identity)
            if membership is not None and membership[0] is existing.item:
                existing.refcount = membership[1]
                continue
            existing.admitted = False
            existing.refcount = 0
            existing.buffered_items = 0
            self._safe_dispose(existing.subscription)
            existing.subscription = None
            del self._entries[identity]
        for staged in plan.staged:
            staged.admitted = True
            self._entries[id(staged.item)] = staged

    def _append_buffered_items_locked(self, changes: list[_PendingChange[T]]) -> None:
        for entry in self._entries.values():
            buffered = 0 if entry.terminal else entry.buffered_items
            entry.buffered_items = 0
            for _ in range(buffered):
                changes.append(
                    _PendingChange(
                        AggregateChange(AggregateChangeReason.ITEM, entry.item),
                        entry,
                        entry.epoch,
                    )
                )

    def _discard_buffered_items_locked(self) -> None:
        for entry in self._entries.values():
            entry.buffered_items = 0

    def _dispose_staged_locked(self, plan: _SnapshotPlan[T]) -> None:
        for staged in plan.staged:
            staged.admitted = False
            staged.buffered_items = 0
            self._safe_dispose(staged.subscription)
            staged.subscription = None

    def _prepend_changes_locked(
        self,
        changes: list[_PendingChange[T]],
        coalesced: bool,
        recipients: tuple[_Registration[T], ...],
    ) -> None:
        if not changes or coalesced or not recipients:
            return
        for pending in reversed(changes):
            self._work.appendleft(
                _Work(
                    "notification",
                    recipients=recipients,
                    change=pending.change,
                    entry=pending.entry,
                    epoch=pending.epoch,
                )
            )

    def _exit_batch(self) -> None:
        start = False
        with self._gate:
            self._batch_depth -= 1
            if self._batch_depth == 0 and self._batch_dirty:
                self._batch_dirty = False
                if not self._completed and self._terminal_error is None:
                    recipients = self._current_registrations_locked()
                    if recipients:
                        self._work.append(
                            _Work(
                                "notification",
                                recipients=recipients,
                                change=AggregateChange(AggregateChangeReason.BATCH),
                            )
                        )
                        start = self._start_processing_locked()
        if start:
            self._process_work()

    def _subscribe(
        self,
        observer: ObserverBase[AggregateChange[T]],
        emit_initial: bool,
    ) -> DisposableBase:
        registration: _Registration[T] | None = None
        start = False
        with self._gate:
            terminal_error = self._terminal_error
            completed = self._completed
            if terminal_error is None and not completed:
                registration = _Registration(observer)
                self._registrations.append(registration)
                if emit_initial:
                    self._work.append(
                        _Work(
                            "notification",
                            recipients=(registration,),
                            change=AggregateChange(AggregateChangeReason.INITIAL),
                        )
                    )
                    start = self._start_processing_locked()
        if terminal_error is not None:
            observer.on_error(terminal_error)
            return Disposable()
        if completed:
            observer.on_completed()
            return Disposable()
        if start:
            try:
                self._process_work()
            except BaseException:
                self._remove_registration(cast(_Registration[T], registration))
                raise
        current = cast(_Registration[T], registration)
        return Disposable(lambda: self._remove_registration(current))

    def _remove_registration(self, registration: _Registration[T]) -> None:
        with self._gate:
            if not registration.active:
                return
            registration.active = False
            if registration in self._registrations:
                self._registrations.remove(registration)

    def _fail_construction_locked(self) -> None:
        self._cleanup_subscriptions_locked()
        self._completed = True
        self._work.clear()

    def _fail_existing_locked(self, error: Exception) -> None:
        if self._completed or self._terminal_error is not None:
            return
        self._terminal_error = error
        self._cleanup_subscriptions_locked()
        self._work.clear()
        recipients = self._current_registrations_locked()
        self._registrations.clear()
        if recipients:
            self._work.appendleft(_Work("error", recipients=recipients, error=error))

    def _cleanup_subscriptions_locked(self) -> None:
        self._safe_dispose(self._membership_subscription)
        self._membership_subscription = None
        for entry in self._entries.values():
            entry.admitted = False
            entry.refcount = 0
            entry.buffered_items = 0
            self._safe_dispose(entry.subscription)
            entry.subscription = None
        self._entries.clear()

    def _current_registrations_locked(self) -> tuple[_Registration[T], ...]:
        return tuple(registration for registration in self._registrations if registration.active)

    def _start_processing_locked(self) -> bool:
        if self._processing or not self._work:
            return False
        self._processing = True
        return True

    def _admit_guarded_delivery(self, work: _Work[T]) -> bool:
        entry = work.entry
        if entry is None:
            return True
        with self._gate:
            if (
                self._completed
                or self._terminal_error is not None
                or not entry.admitted
                or entry.terminal
                or entry.epoch != work.epoch
                or entry.refcount == 0
            ):
                return False
            work.entry = None
            return True

    @staticmethod
    def _deliver(work: _Work[T]) -> None:
        for registration in work.recipients:
            if not registration.active:
                continue
            if work.kind == "notification":
                registration.observer.on_next(cast(AggregateChange[T], work.change))
            elif work.kind == "error":
                registration.active = False
                registration.observer.on_error(cast(Exception, work.error))
            elif work.kind == "completion":
                registration.active = False
                registration.observer.on_completed()

    def _read_structural_version(self) -> int:
        with self._version_gate:
            return self._structural_version

    @staticmethod
    def _safe_dispose(disposable: DisposableBase | None) -> None:
        if disposable is None:
            return
        try:
            disposable.dispose()
        except BaseException:
            pass

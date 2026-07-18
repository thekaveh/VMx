"""_ComponentVMBase — abstract base for all ComponentVM variants.

Manages:
- Status state machine (Construct / Destruct / Reconstruct / Dispose)
- Hub publishing (ConstructionStatusChangedMessage, PropertyChangedMessage)
- Built-in RelayCommands (select, deselect, select_next, select_previous, reconstruct)
- Selection predicates and delegation to parent
- INPC-equivalent: property_changed Observable

See spec/05-component-vm.md and spec/02-lifecycle.md.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from typing import TYPE_CHECKING, Protocol

import reactivex as rx
from reactivex import operators as ops
from reactivex.abc import SchedulerBase
from reactivex.subject import Subject

from vmx.commands.relay_command import RelayCommand
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import require
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHubProto

if TYPE_CHECKING:
    from vmx.components.protocols import ComponentVMProto, ViewModelType


# Ownership tokens retain their child reservation through construction and
# commit/rollback. A process-wide re-entrant coordinator prevents bulk
# populations that enumerate the same children in reverse order from each
# retaining one child lock and waiting forever for the other.
_OWNERSHIP_TRANSACTION_GATE = threading.RLock()


class _Disposable(Protocol):
    def dispose(self) -> None: ...


class _LifecyclePublication:
    """One admitted status publication drained without holding lifecycle state."""

    def __init__(
        self,
        status: ConstructionStatus | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self.status = status
        self.action = action
        self.error: BaseException | None = None
        self.completed = threading.Event()


_lifecycle_wait_graph_gate = threading.RLock()
_lifecycle_thread_waits_for: dict[int, int] = {}


def _register_lifecycle_wait(waiter: int, owner: int) -> bool:
    """Register a lifecycle wait edge; return true if it closes a cycle."""
    with _lifecycle_wait_graph_gate:
        _lifecycle_thread_waits_for[waiter] = owner
        cursor = owner
        visited: set[int] = set()
        while cursor not in visited:
            if cursor == waiter:
                _lifecycle_thread_waits_for.pop(waiter, None)
                return True
            visited.add(cursor)
            next_owner = _lifecycle_thread_waits_for.get(cursor)
            if next_owner is None:
                return False
            cursor = next_owner
        return False


def _unregister_lifecycle_wait(waiter: int) -> None:
    with _lifecycle_wait_graph_gate:
        _lifecycle_thread_waits_for.pop(waiter, None)


def _dispose_children_then_self(
    children: Iterable[_Disposable | None], dispose_self: Callable[[], None]
) -> None:
    """Finish a LIFE-013 cascade and then re-raise its first failure."""
    first_error: BaseException | None = None
    for child in children:
        if child is None:
            continue
        try:
            child.dispose()
        except BaseException as error:
            if first_error is None:
                first_error = error

    try:
        dispose_self()
    except BaseException as error:
        if first_error is None:
            first_error = error

    if first_error is not None:
        raise first_error


# ---------------------------------------------------------------------------
# Internal parent interface (mirrors C# IParentCompositeVM)
# ---------------------------------------------------------------------------


class _ParentCompositeVM(ABC):
    """Minimal parent interface used by a child VM for selection delegation.

    Implemented by composite and group base classes. Not part of the public API.
    """

    @property
    @abstractmethod
    def owner(self) -> _ComponentVMBase: ...

    @property
    @abstractmethod
    def owner_parent(self) -> _ParentCompositeVM | None: ...

    @property
    @abstractmethod
    def current_child(self) -> object | None: ...

    @property
    def supports_child_selection(self) -> bool:
        """Whether a child of this parent can meaningfully be selected.

        ``True`` for composites (which own a Current slot); ``False`` for
        groups, whose children are peers with no selection slot. A child uses
        this to keep ``can_select`` honest — a group child reported
        ``can_select == True`` while ``select()`` was an inert no-op (VMX-077).
        """
        return True

    @abstractmethod
    def select_child(self, vm: _ComponentVMBase) -> None: ...

    @abstractmethod
    def deselect_child(self, vm: _ComponentVMBase) -> None: ...

    @abstractmethod
    def contains_child(self, vm: _ComponentVMBase) -> bool: ...

    @abstractmethod
    def detach_for_transfer(self, vm: _ComponentVMBase) -> _ParentTransfer: ...


class _ParentTransfer:
    """One-shot staged removal that can be committed or rolled back."""

    def __init__(self, commit: Callable[[], None], rollback: Callable[[], None]) -> None:
        self._commit = commit
        self._rollback = rollback
        self._finished = False

    def commit(self) -> None:
        if self._finished:
            raise RuntimeError("parent transfer is already finished")
        self._finished = True
        self._commit()

    def rollback(self) -> None:
        if self._finished:
            raise RuntimeError("parent transfer is already finished")
        self._finished = True
        self._rollback()


def _commit_parent_transfer(transfer: _ParentTransfer | None) -> BaseException | None:
    """Commit ownership, retaining a late failure until destination publication."""
    if transfer is None:
        return None
    try:
        transfer.commit()
    except BaseException as error:
        return error
    return None


def _begin_parent_transfer(
    child: _ComponentVMBase, destination: _ParentCompositeVM
) -> _ParentTransfer:
    """Validate exclusive ownership/cycles and stage any old-parent removal."""
    identity = child._ownership_identity
    _OWNERSHIP_TRANSACTION_GATE.acquire()
    identity._ownership_lock.acquire()
    if identity._ownership_in_progress:
        identity._ownership_lock.release()
        _OWNERSHIP_TRANSACTION_GATE.release()
        raise RuntimeError(f"Cannot transfer {child.name!r}: ownership transaction is in progress")
    identity._ownership_in_progress = True
    try:
        if destination.contains_child(child):
            raise ValueError(
                f"Cannot add {child.name!r}: destination already contains that identity"
            )

        cursor: _ParentCompositeVM | None = destination
        while cursor is not None:
            if cursor.owner._ownership_identity is identity:
                raise ValueError(
                    f"Cannot add {child.name!r}: operation would create a parent cycle"
                )
            cursor = cursor.owner_parent

        ownership_parent = child._ownership_parent
        staged = None if ownership_parent is None else ownership_parent.detach_for_transfer(child)
    except BaseException:
        identity._ownership_in_progress = False
        identity._ownership_lock.release()
        _OWNERSHIP_TRANSACTION_GATE.release()
        raise

    def finish(commit: bool) -> None:
        try:
            if staged is not None:
                (staged.commit if commit else staged.rollback)()
        finally:
            identity._ownership_in_progress = False
            identity._ownership_lock.release()
            _OWNERSHIP_TRANSACTION_GATE.release()

    return _ParentTransfer(lambda: finish(True), lambda: finish(False))


# ---------------------------------------------------------------------------
# _ComponentVMBase
# ---------------------------------------------------------------------------


class _ComponentVMBase(ABC):
    """Abstract base class for all ComponentVM variants.

    Subclasses must implement the ``type`` property (returns ViewModelType) and
    may override ``_on_construct`` / ``_on_destruct`` / ``_on_dispose`` to layer
    container-specific behaviour onto the lifecycle. Do NOT instantiate
    directly — use a builder.
    """

    # ── Constructor ──────────────────────────────────────────────────────────
    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        background: bool = False,
    ) -> None:
        self._name: str = name
        self._hint: str = hint
        self._hub: MessageHubProto[Message] = hub
        self._dispatcher: Dispatcher = dispatcher
        self._on_construct_cb: Callable[[], None] | None = on_construct
        self._on_destruct_cb: Callable[[], None] | None = on_destruct
        self._background: bool = background
        self._owned_resources: list[Callable[[], None] | _Disposable] = []

        # ── Lifecycle state ──────────────────────────────────────────────────
        self._status: ConstructionStatus = ConstructionStatus.DESTRUCTED
        self._in_flight: bool = False
        self._lifecycle_waiters: list[Future[None]] = []
        self._deferred_lifecycle_future: Future[None] | None = None

        # Serializes every lifecycle state transition — the ``_status`` RMW, the
        # hub publish, and the status-trigger emission inside ``_set_status`` —
        # against ``dispose()``. A background completion (construct/destruct
        # dispatched on the background scheduler) therefore cannot interleave with
        # disposal: it observes the terminal Disposed state under the lock and
        # aborts instead of resurrecting the VM, publishing a post-dispose status
        # message, or calling ``on_next`` on a disposed Subject (VMX-004; spec/02
        # invariant 3 — Disposed is terminal). Reentrant so a re-entrant lifecycle
        # call from a same-thread subscriber cannot self-deadlock.
        self._lifecycle_lock = threading.RLock()
        self._lifecycle_publications: deque[_LifecyclePublication] = deque()
        self._lifecycle_drainer_thread: int | None = None
        self._terminal_publication_pending = False

        # ── Selection state ──────────────────────────────────────────────────
        self._is_current: bool = False
        self._parent: _ParentCompositeVM | None = None
        # A child owns its membership transaction from preflight through
        # commit/rollback. The recursive lock serializes competing threads;
        # the flag rejects same-thread reparenting from an auto-construct hook.
        self._ownership_lock = threading.RLock()
        self._ownership_in_progress = False

        # ── property_changed subject ────────────────────────────────────────
        # Mimics INotifyPropertyChanged — emits property name strings.
        self._property_changed_subject: Subject[str] = Subject()
        self._trigger_disposed: bool = False
        self._active_property_notifications: int = 0
        self._property_notification_teardown_pending: bool = False

        # ── Status-change trigger (drives command CanExecute re-eval) ────────
        self._status_trigger: Subject[None] = Subject()

        # ── Built-in commands (lazily built on first access) ─────────────────
        # Building all five RelayCommands eagerly here allocated five commands
        # plus five status-trigger subscriptions per VM, four of which are
        # permanently inert on a leaf VM (no parent → can_select/can_deselect
        # are False; select_next/select_previous are hardcoded False).  They are
        # now constructed on first property access and cached, so a VM whose
        # navigation commands are never bound pays nothing (VMX-018).  The
        # status-trigger wiring is preserved so a bound command's
        # can_execute_changed still fires on lifecycle transitions (VMX-104).
        self._select_command: RelayCommand | None = None
        self._deselect_command: RelayCommand | None = None
        self._select_next_command: RelayCommand | None = None
        self._select_previous_command: RelayCommand | None = None
        self._reconstruct_command: RelayCommand | None = None

    # ── Identity (read-only) ─────────────────────────────────────────────────
    @property
    def name(self) -> str:
        """Human-readable identifier; immutable post-construction."""
        return self._name

    @property
    def hint(self) -> str:
        """Optional descriptive hint; immutable post-construction."""
        return self._hint

    @property
    def hub(self) -> MessageHubProto[Message]:
        """Injected shared message hub; the VM does not own its lifetime."""
        return self._hub

    @property
    @abstractmethod
    def type(self) -> ViewModelType: ...

    # ── Status / IsConstructed ───────────────────────────────────────────────
    @property
    def status(self) -> ConstructionStatus:
        """Current lifecycle state."""
        return self._status

    @property
    def is_constructed(self) -> bool:
        """True when Status == Constructed (invariant per spec/02-lifecycle.md)."""
        return self._status == ConstructionStatus.CONSTRUCTED

    # ── IsCurrent / Parent ───────────────────────────────────────────────────
    @property
    def is_current(self) -> bool:
        """True when this VM is the current selection of its parent."""
        return self._is_current

    def _set_is_current(self, value: bool) -> None:
        """Called by the parent composite when selection changes."""
        if self._commit_is_current(value):
            self._publish_is_current()

    def _commit_is_current(self, value: bool) -> bool:
        """Commit the current flag without invoking consumer notification code."""
        # Post-dispose guard: spec/02 invariant 3 — Disposed is terminal. A
        # selection change on an already-disposed VM is a silent no-op (no
        # property_changed emit, no hub PropertyChangedMessage), mirroring Swift
        # (VMX-006). Reads the terminal state under the same lock the
        # lifecycle-race guards use.
        if self._is_disposed():
            return False
        if self._is_current == value:
            return False
        self._is_current = value
        return True

    def _publish_is_current(self) -> None:
        """Publish a current-flag commit after container coordination is released."""
        self._notify_property_changed("is_current")

    def _set_parent(self, parent: _ParentCompositeVM | None) -> None:
        """Called by CompositeVMBase when this child is added/removed."""
        self._parent = parent

    @property
    def _ownership_identity(self) -> _ComponentVMBase:
        """Canonical component shared by every forwarding alias."""
        return self

    @property
    def _ownership_parent(self) -> _ParentCompositeVM | None:
        """Parent consulted by ownership transfer preflight."""
        return self._parent

    # ── property_changed observable ──────────────────────────────────────────
    @property
    def property_changed(self) -> rx.Observable[str]:
        """Observable that emits property name strings when properties change.

        Equivalent to .NET INotifyPropertyChanged — subscribers receive the
        property name (snake_case) on each change.

        The backing :class:`~reactivex.subject.Subject` is sealed behind
        ``as_observable`` so external subscribers cannot ``on_next``/``dispose``
        the internal stream and corrupt other subscribers (VMX-013).
        """
        return self._property_changed_subject.pipe(ops.as_observable())

    def _raise_property_changed(self, property_name: str) -> None:
        """Emit *property_name* only on the VM-local property_changed subject."""
        if not self._trigger_disposed:
            self._property_changed_subject.on_next(property_name)

    def _notify_property_changed(self, property_name: str) -> None:
        """Publish one hub message, then one VM-local property notification."""
        with self._lifecycle_lock:
            if self._status == ConstructionStatus.DISPOSED or self._trigger_disposed:
                return
            self._active_property_notifications += 1
        try:
            try:
                self._hub.send(PropertyChangedMessage.create(self, self._name, property_name))
            finally:
                # This call was admitted before disposal. Its local half must
                # still run if a hub observer disposes the VM re-entrantly.
                self._property_changed_subject.on_next(property_name)
        finally:
            with self._lifecycle_lock:
                self._active_property_notifications -= 1
                if (
                    self._active_property_notifications == 0
                    and self._property_notification_teardown_pending
                ):
                    self._property_notification_teardown_pending = False
                    self._property_changed_subject.on_completed()
                    self._property_changed_subject.dispose()

    # ── Built-in commands (lazily built + cached — VMX-018) ──────────────────
    def _build_command(
        self,
        predicate: Callable[[], bool],
        task: Callable[[], None],
    ) -> RelayCommand:
        """Build a built-in RelayCommand, wiring the status trigger when live.

        The status trigger re-fires ``can_execute_changed`` on every lifecycle
        transition (VMX-104).  After the VM is disposed the trigger Subject is
        completed/disposed, so a command built post-dispose is built without it
        rather than subscribing to a disposed Subject.
        """
        builder = RelayCommand.builder().predicate(predicate).task(task)
        if not self._trigger_disposed:
            trigger_obs: rx.Observable[object] = self._status_trigger
            builder = builder.triggers(trigger_obs)
        return builder.build()

    @property
    def select_command(self) -> RelayCommand:
        if self._select_command is None:
            self._select_command = self._build_command(self.can_select, self.select)
        return self._select_command

    @property
    def deselect_command(self) -> RelayCommand:
        if self._deselect_command is None:
            self._deselect_command = self._build_command(self.can_deselect, self.deselect)
        return self._deselect_command

    @property
    def select_next_command(self) -> RelayCommand:
        if self._select_next_command is None:
            self._select_next_command = self._build_command(
                self._can_select_next, self._select_next
            )
        return self._select_next_command

    @property
    def select_previous_command(self) -> RelayCommand:
        if self._select_previous_command is None:
            self._select_previous_command = self._build_command(
                self._can_select_previous, self._select_previous
            )
        return self._select_previous_command

    @property
    def reconstruct_command(self) -> RelayCommand:
        if self._reconstruct_command is None:
            self._reconstruct_command = self._build_command(self.can_reconstruct, self.reconstruct)
        return self._reconstruct_command

    # ── Lifecycle: can_* predicates ──────────────────────────────────────────
    def can_construct(self) -> bool:
        """True iff Status ∈ {Destructed, Constructed}."""
        return self._status in (
            ConstructionStatus.DESTRUCTED,
            ConstructionStatus.CONSTRUCTED,
        )

    def can_destruct(self) -> bool:
        """True iff Status ∈ {Constructed, Destructed}."""
        return self._status in (
            ConstructionStatus.CONSTRUCTED,
            ConstructionStatus.DESTRUCTED,
        )

    def can_reconstruct(self) -> bool:
        """True iff Status == Constructed."""
        return self._status == ConstructionStatus.CONSTRUCTED

    # ── Lifecycle: construct ─────────────────────────────────────────────────
    def construct(self) -> None:
        """Transitions Destructed → Constructing → Constructed.

        Idempotent from Constructed (no-op, no message emitted).
        """
        with self._lifecycle_lock:
            # Idempotent: already Constructed → no-op (no message).
            if self._status == ConstructionStatus.CONSTRUCTED:
                return

            # Validate transition (raises StatusTransitionError for illegal states).
            require(self._status, "construct")

            # Concurrency guard.
            if self._in_flight:
                raise StatusTransitionError(self._status, "construct")
            self._in_flight = True

        if not self._set_status(ConstructionStatus.CONSTRUCTING):
            self._clear_in_flight()
            return

        if self._background:
            # Emit Constructing synchronously so subscribers immediately see
            # the transition starting, then schedule work on background.
            def _bg_construct(scheduler: SchedulerBase, state: object | None) -> None:
                # dispose() may have run between scheduling and execution.
                # Re-check the terminal state under the lock and abort if disposed
                # (spec/02 invariant 3): no _on_construct(), no marshalled emission.
                if self._is_disposed():
                    self._clear_in_flight()
                    return

                try:
                    self._on_construct()
                except BaseException:
                    # VMX-007: a throwing background construct hook must not wedge
                    # the VM in the transient Constructing state. Roll _status back
                    # to the prior settled state (Destructed) — marshalled onto the
                    # foreground per VMX-025 and re-checking Disposed under the lock
                    # inside _set_status — and clear the in-flight guard so the VM is
                    # recoverable, then re-raise. Under the immediate dispatcher the
                    # rollback runs inline and the exception surfaces to the caller;
                    # on a real background scheduler it is unobserved on the pool
                    # thread (delivering it to an awaiter is tracked by VMX-049).
                    def _fg_rollback(_scheduler: SchedulerBase, _state: object | None) -> None:
                        try:
                            self._set_status(ConstructionStatus.DESTRUCTED)
                        finally:
                            self._clear_in_flight()

                    self._dispatcher.foreground.schedule(_fg_rollback)
                    raise

                deferred = self._take_deferred_lifecycle_future()
                if deferred is not None:
                    self._complete_deferred_lifecycle(
                        deferred,
                        success=ConstructionStatus.CONSTRUCTED,
                        rollback=ConstructionStatus.DESTRUCTED,
                    )
                    return

                # VMX-025: marshal the terminal Constructed emission onto the
                # foreground scheduler so subscribers observe the status change on
                # the foreground (UI) thread, not the background (pool) thread.
                # _set_status re-checks DISPOSED under the lock, so a dispose()
                # landing before this marshalled emission runs still aborts the
                # transition — no resurrection, no post-dispose publish, no on_next
                # on a disposed Subject (VMX-004).
                def _fg_construct(_scheduler: SchedulerBase, _state: object | None) -> None:
                    try:
                        self._set_status(ConstructionStatus.CONSTRUCTED)
                    finally:
                        self._clear_in_flight()

                self._dispatcher.foreground.schedule(_fg_construct)

            self._dispatcher.background.schedule(_bg_construct)
        else:
            completion_deferred = False
            try:
                if self._is_disposed():
                    return
                try:
                    self._on_construct()
                except BaseException:
                    # VMX-007: roll _status back to the prior settled state
                    # (Destructed) under the same lock _set_status uses, then
                    # re-raise so the caller sees the original failure. The VM is
                    # left recoverable instead of wedged in Constructing.
                    self._set_status(ConstructionStatus.DESTRUCTED)
                    raise
                deferred = self._take_deferred_lifecycle_future()
                if deferred is not None:
                    completion_deferred = True
                    self._complete_deferred_lifecycle(
                        deferred,
                        success=ConstructionStatus.CONSTRUCTED,
                        rollback=ConstructionStatus.DESTRUCTED,
                    )
                    return
                self._set_status(ConstructionStatus.CONSTRUCTED)
            finally:
                if not completion_deferred:
                    self._clear_in_flight()

    # ── Lifecycle: destruct ──────────────────────────────────────────────────
    def destruct(self) -> None:
        """Transitions Constructed → Destructing → Destructed.

        Idempotent from Destructed (no-op, no message emitted).
        """
        with self._lifecycle_lock:
            if self._status == ConstructionStatus.DESTRUCTED:
                return

            require(self._status, "destruct")

            if self._in_flight:
                raise StatusTransitionError(self._status, "destruct")
            self._in_flight = True

        if not self._set_status(ConstructionStatus.DESTRUCTING):
            self._clear_in_flight()
            return

        if self._background:

            def _bg_destruct(scheduler: SchedulerBase, state: object | None) -> None:
                # dispose() may have run between scheduling and execution.
                # Re-check the terminal state under the lock and abort if disposed
                # (spec/02 invariant 3): no _on_destruct(), no marshalled emission.
                if self._is_disposed():
                    self._clear_in_flight()
                    return

                try:
                    self._on_destruct()
                except BaseException:
                    # VMX-007: a throwing background destruct hook must not wedge
                    # the VM in the transient Destructing state. Roll _status back
                    # to the prior settled state (Constructed) — marshalled onto the
                    # foreground per VMX-025 and re-checking Disposed under the lock
                    # inside _set_status — and clear the in-flight guard so the VM is
                    # recoverable, then re-raise (unobserved on a real pool thread;
                    # VMX-049 tracks delivering it to an awaiter).
                    def _fg_rollback(_scheduler: SchedulerBase, _state: object | None) -> None:
                        try:
                            self._set_status(ConstructionStatus.CONSTRUCTED)
                        finally:
                            self._clear_in_flight()

                    self._dispatcher.foreground.schedule(_fg_rollback)
                    raise

                deferred = self._take_deferred_lifecycle_future()
                if deferred is not None:
                    self._complete_deferred_lifecycle(
                        deferred,
                        success=ConstructionStatus.DESTRUCTED,
                        rollback=ConstructionStatus.CONSTRUCTED,
                    )
                    return

                # VMX-025: marshal the terminal Destructed emission onto the
                # foreground scheduler so subscribers observe the status change on
                # the foreground (UI) thread, not the background (pool) thread.
                # _set_status re-checks DISPOSED under the lock, so a dispose()
                # landing before this marshalled emission runs still aborts the
                # transition — no resurrection, no post-dispose publish, no on_next
                # on a disposed Subject (VMX-004).
                def _fg_destruct(_scheduler: SchedulerBase, _state: object | None) -> None:
                    try:
                        self._set_status(ConstructionStatus.DESTRUCTED)
                    finally:
                        self._clear_in_flight()

                self._dispatcher.foreground.schedule(_fg_destruct)

            self._dispatcher.background.schedule(_bg_destruct)
        else:
            completion_deferred = False
            try:
                if self._is_disposed():
                    return
                try:
                    self._on_destruct()
                except BaseException:
                    # VMX-007: roll _status back to the prior settled state
                    # (Constructed) under the lock, then re-raise. The VM is left
                    # recoverable instead of wedged in Destructing.
                    self._set_status(ConstructionStatus.CONSTRUCTED)
                    raise
                deferred = self._take_deferred_lifecycle_future()
                if deferred is not None:
                    completion_deferred = True
                    self._complete_deferred_lifecycle(
                        deferred,
                        success=ConstructionStatus.DESTRUCTED,
                        rollback=ConstructionStatus.CONSTRUCTED,
                    )
                    return
                self._set_status(ConstructionStatus.DESTRUCTED)
            finally:
                if not completion_deferred:
                    self._clear_in_flight()

    # ── Lifecycle: reconstruct ───────────────────────────────────────────────
    def reconstruct(self) -> None:
        """Destructs then re-constructs this VM atomically.

        Emits four messages: Destructing, Destructed, Constructing, Constructed.
        """
        with self._lifecycle_lock:
            require(self._status, "reconstruct")

            if self._in_flight:
                raise StatusTransitionError(self._status, "reconstruct")
            self._in_flight = True

        # Destruct phase. Publication must happen after releasing the state
        # lock so opposing lifecycle observers cannot retain two VM locks.
        if not self._set_status(ConstructionStatus.DESTRUCTING):
            self._clear_in_flight()
            return

        completion_deferred = False
        try:
            if self._is_disposed():
                return
            try:
                self._on_destruct()
            except BaseException:
                # VMX-007: a failed destruct phase rolls back to Constructed
                # (the state reconstruct started from) so the VM stays recoverable.
                self._set_status(ConstructionStatus.CONSTRUCTED)
                raise
            deferred_destruct = self._take_deferred_lifecycle_future()
            if deferred_destruct is not None:
                completion_deferred = True
                self._continue_reconstruct_after_deferred_destruct(deferred_destruct)
                return

            completion_deferred = self._continue_reconstruct_with_construct_phase()
        finally:
            if not completion_deferred:
                self._clear_in_flight()

    def _continue_reconstruct_with_construct_phase(self) -> bool:
        self._set_status(ConstructionStatus.DESTRUCTED)
        self._set_status(ConstructionStatus.CONSTRUCTING)
        try:
            self._on_construct()
        except BaseException:
            self._set_status(ConstructionStatus.DESTRUCTED)
            raise

        deferred_construct = self._take_deferred_lifecycle_future()
        if deferred_construct is not None:
            self._complete_deferred_lifecycle(
                deferred_construct,
                success=ConstructionStatus.CONSTRUCTED,
                rollback=ConstructionStatus.DESTRUCTED,
            )
            return True

        self._set_status(ConstructionStatus.CONSTRUCTED)
        return False

    def _continue_reconstruct_after_deferred_destruct(self, future: Future[None]) -> None:
        def settled(completed: Future[None]) -> None:
            def resume(_scheduler: SchedulerBase, _state: object | None) -> None:
                if self._is_disposed():
                    self._clear_in_flight()
                    return
                try:
                    completed.result()
                except BaseException:
                    self._set_status(ConstructionStatus.CONSTRUCTED)
                    self._clear_in_flight()
                    return

                try:
                    if not self._continue_reconstruct_with_construct_phase():
                        self._clear_in_flight()
                except BaseException:
                    self._clear_in_flight()

            self._dispatcher.foreground.schedule(resume)

        future.add_done_callback(settled)

    # ── Lifecycle: dispose ───────────────────────────────────────────────────
    def dispose(self) -> None:
        """Transition to Disposed from any state. Terminal; idempotent.

        Disposes commands and completes the status trigger / property_changed
        subjects.
        """
        first_error: BaseException | None = None

        def attempt(action: Callable[[], None]) -> None:
            nonlocal first_error
            try:
                action()
            except BaseException as error:
                if first_error is None:
                    first_error = error

        with self._lifecycle_lock:
            if self._status == ConstructionStatus.DISPOSED:
                return

            # Terminal notification is best-effort: an observer failure must not
            # prevent the remaining channels or mandatory cleanup from running.
            self._status = ConstructionStatus.DISPOSED
            publication, should_drain = self._enqueue_lifecycle_publication_locked(
                ConstructionStatus.DISPOSED
            )
            self._terminal_publication_pending = True
            waiters = self._take_lifecycle_waiters_locked()
            _waiter_publication, waiter_should_drain = self._enqueue_waiter_completion_locked(
                waiters
            )
            should_drain |= waiter_should_drain

        attempt(lambda: self._await_lifecycle_publication(publication, should_drain))
        attempt(self._on_dispose)
        attempt(self._dispose_owned_resources)

        with self._lifecycle_lock:
            teardown, should_drain = self._enqueue_lifecycle_action_locked(
                self._finish_terminal_publication
            )
        attempt(lambda: self._await_lifecycle_publication(teardown, should_drain))

        # Only commands that were actually accessed (lazily built — VMX-018)
        # need disposal; un-built slots are still None.
        for command in (
            self._select_command,
            self._deselect_command,
            self._select_next_command,
            self._select_previous_command,
            self._reconstruct_command,
        ):
            if command is not None:
                attempt(command.dispose)

        if first_error is not None:
            raise first_error

    # ── Selection predicates ─────────────────────────────────────────────────
    def can_select(self) -> bool:
        """True iff parent supports selection, this is not current, and Constructed.

        A parent that owns no selection slot (e.g. a group — see
        ``supports_child_selection``) yields ``False`` so the inherited
        ``select_command`` is not enabled-but-inert (VMX-077).
        """
        return (
            self._parent is not None
            and self._parent.supports_child_selection
            and self._parent.current_child is not self
            and self._status == ConstructionStatus.CONSTRUCTED
        )

    def select(self) -> None:
        """Select this VM in its parent composite."""
        if self._parent is not None:
            self._parent.select_child(self)

    def can_deselect(self) -> bool:
        """True iff parent is not None and this VM is the current child."""
        return self._parent is not None and self._parent.current_child is self

    def deselect(self) -> None:
        """Deselect this VM in its parent composite."""
        if self._parent is not None:
            self._parent.deselect_child(self)

    # ── Overridable lifecycle hooks (for composites/groups) ──────────────────
    def _on_construct(self) -> None:
        """Called between Constructing and Constructed transitions.

        Override in subclasses (e.g. composites). Base invokes the builder's
        on_construct callback.
        """
        if self._on_construct_cb is not None:
            self._on_construct_cb()

    def _on_destruct(self) -> None:
        """Called between Destructing and Destructed transitions.

        Override in subclasses. Base invokes the builder's on_destruct callback.
        """
        if self._on_destruct_cb is not None:
            self._on_destruct_cb()

    def _complete_lifecycle_hook_after(self, future: Future[None]) -> None:
        """Keep the parent transient until asynchronous child work settles."""
        if future.done():
            future.result()
            return
        with self._lifecycle_lock:
            if self._deferred_lifecycle_future is not None:
                raise RuntimeError("a lifecycle hook already deferred completion")
            self._deferred_lifecycle_future = future

    @staticmethod
    def _transition_children(
        children: Iterable[ComponentVMProto],
        *,
        construct: bool,
        after: Callable[[], None] | None = None,
    ) -> Future[None]:
        """Transition children sequentially and validate each settled state."""
        result: Future[None] = Future()
        iterator = iter(children)

        def advance() -> None:
            while not result.done():
                try:
                    child = next(iterator)
                except StopIteration:
                    try:
                        if after is not None:
                            after()
                    except BaseException as error:
                        result.set_exception(error)
                    else:
                        result.set_result(None)
                    return

                try:
                    if isinstance(child, _ComponentVMBase):
                        pending = (
                            child._construct_future() if construct else child._destruct_future()
                        )
                    else:
                        pending = Future()
                        if construct:
                            child.construct()
                        else:
                            child.destruct()
                        pending.set_result(None)
                except BaseException as error:
                    result.set_exception(error)
                    return

                def child_settled(
                    completed: Future[None],
                    current: ComponentVMProto = child,
                ) -> None:
                    try:
                        completed.result()
                        expected = (
                            ConstructionStatus.CONSTRUCTED
                            if construct
                            else ConstructionStatus.DESTRUCTED
                        )
                        if current.status is not expected:
                            raise RuntimeError(
                                f"child '{current.name}' did not reach {expected.name}"
                            )
                    except BaseException as error:
                        if not result.done():
                            result.set_exception(error)
                    else:
                        advance()

                if pending.done():
                    child_settled(pending)
                    if result.done():
                        return
                    continue

                pending.add_done_callback(child_settled)
                return

        advance()
        return result

    def _on_dispose(self) -> None:  # noqa: B027  — intentional override hook
        """Called by dispose() after status reaches Disposed. Override for cleanup."""

    def _own(self, resource: Callable[[], None] | _Disposable) -> Callable[[], None] | _Disposable:
        """Register a callable or ``dispose()`` resource for terminal cleanup."""
        with self._lifecycle_lock:
            dispose_now = self._status == ConstructionStatus.DISPOSED
            if not dispose_now:
                self._owned_resources.append(resource)
        if dispose_now:
            self._dispose_owned_resource(resource)
        return resource

    @staticmethod
    def _dispose_owned_resource(resource: Callable[[], None] | _Disposable) -> None:
        try:
            if callable(resource):
                resource()
            else:
                resource.dispose()
        except BaseException:
            # Terminal cleanup is best-effort; one failure must not block the rest.
            pass

    def _dispose_owned_resources(self) -> None:
        with self._lifecycle_lock:
            resources = self._owned_resources
            self._owned_resources = []
        for resource in reversed(resources):
            self._dispose_owned_resource(resource)

    # -- SelectNext / SelectPrevious ----------------------------------------
    # Parent enumeration (sibling navigation) is intentionally not implemented
    # in the base; subclasses with a known parent override these. The empty
    # bodies below are intentional (B027 silenced).
    def _can_select_next(self) -> bool:
        return False

    def _select_next(self) -> None:  # noqa: B027
        pass

    def _can_select_previous(self) -> bool:
        return False

    def _select_previous(self) -> None:  # noqa: B027
        pass

    # ── Internal helpers ─────────────────────────────────────────────────────
    def _is_disposed(self) -> bool:
        """Read the terminal-state flag under the lock.

        Lets a background completion observe a concurrently in-progress
        ``dispose()`` and abort its transition rather than resurrecting the VM
        (VMX-004).
        """
        with self._lifecycle_lock:
            return self._status is ConstructionStatus.DISPOSED

    def _clear_in_flight(self) -> None:
        """Clear the lifecycle in-flight guard under the lifecycle lock."""
        with self._lifecycle_lock:
            self._in_flight = False
            waiters = self._take_lifecycle_waiters_locked()
            publication, should_drain = self._enqueue_waiter_completion_locked(waiters)
        if publication is not None:
            self._await_lifecycle_publication(publication, should_drain)

    def _construct_future(self) -> Future[None]:
        with self._lifecycle_lock:
            if self._status is ConstructionStatus.CONSTRUCTED:
                completed: Future[None] = Future()
                completed.set_result(None)
                return completed
            if self._status is ConstructionStatus.CONSTRUCTING:
                waiter: Future[None] = Future()
                self._lifecycle_waiters.append(waiter)
                return waiter
        return self._start_lifecycle_future(self.construct)

    def _destruct_future(self) -> Future[None]:
        with self._lifecycle_lock:
            if self._status is ConstructionStatus.DESTRUCTED:
                completed: Future[None] = Future()
                completed.set_result(None)
                return completed
            if self._status is ConstructionStatus.DESTRUCTING:
                waiter: Future[None] = Future()
                self._lifecycle_waiters.append(waiter)
                return waiter
        return self._start_lifecycle_future(self.destruct)

    def _start_lifecycle_future(self, operation: Callable[[], None]) -> Future[None]:
        waiter: Future[None] = Future()
        with self._lifecycle_lock:
            self._lifecycle_waiters.append(waiter)
        try:
            operation()
        except BaseException:
            with self._lifecycle_lock:
                if waiter in self._lifecycle_waiters:
                    self._lifecycle_waiters.remove(waiter)
            raise
        with self._lifecycle_lock:
            if not self._in_flight and self._is_settled(self._status):
                if waiter in self._lifecycle_waiters:
                    self._lifecycle_waiters.remove(waiter)
                publication, should_drain = self._enqueue_waiter_completion_locked([waiter])
            else:
                publication = None
                should_drain = False
        if publication is not None:
            self._await_lifecycle_publication(publication, should_drain)
        return waiter

    @staticmethod
    def _is_settled(status: ConstructionStatus) -> bool:
        return status in (
            ConstructionStatus.CONSTRUCTED,
            ConstructionStatus.DESTRUCTED,
            ConstructionStatus.DISPOSED,
        )

    def _take_lifecycle_waiters_locked(self) -> list[Future[None]]:
        if not self._is_settled(self._status):
            return []
        waiters = self._lifecycle_waiters
        self._lifecycle_waiters = []
        return waiters

    def _take_deferred_lifecycle_future(self) -> Future[None] | None:
        with self._lifecycle_lock:
            future = self._deferred_lifecycle_future
            self._deferred_lifecycle_future = None
            return future

    def _complete_deferred_lifecycle(
        self,
        future: Future[None],
        *,
        success: ConstructionStatus,
        rollback: ConstructionStatus,
    ) -> None:
        def settled(completed: Future[None]) -> None:
            def finalize(_scheduler: SchedulerBase, _state: object | None) -> None:
                try:
                    try:
                        completed.result()
                    except BaseException:
                        self._set_status(rollback)
                    else:
                        self._set_status(success)
                finally:
                    self._clear_in_flight()

            self._dispatcher.foreground.schedule(finalize)

        future.add_done_callback(settled)

    def _set_status(self, new_status: ConstructionStatus) -> bool:
        """Admit a state change atomically, then publish it outside the state lock."""
        with self._lifecycle_lock:
            if self._status is ConstructionStatus.DISPOSED:
                return False

            self._status = new_status
            publication, should_drain = self._enqueue_lifecycle_publication_locked(new_status)

        self._await_lifecycle_publication(publication, should_drain)
        return True

    def _enqueue_lifecycle_publication_locked(
        self, status: ConstructionStatus
    ) -> tuple[_LifecyclePublication, bool]:
        publication = _LifecyclePublication(status)
        self._lifecycle_publications.append(publication)
        if self._lifecycle_drainer_thread is None:
            self._lifecycle_drainer_thread = threading.get_ident()
            return publication, True
        return publication, False

    def _enqueue_lifecycle_action_locked(
        self, action: Callable[[], None]
    ) -> tuple[_LifecyclePublication, bool]:
        publication = _LifecyclePublication(action=action)
        self._lifecycle_publications.append(publication)
        if self._lifecycle_drainer_thread is None:
            self._lifecycle_drainer_thread = threading.get_ident()
            return publication, True
        return publication, False

    def _enqueue_waiter_completion_locked(
        self, waiters: list[Future[None]]
    ) -> tuple[_LifecyclePublication | None, bool]:
        if not waiters:
            return None, False

        def complete() -> None:
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(None)

        return self._enqueue_lifecycle_action_locked(complete)

    def _drain_lifecycle_publications(self) -> None:
        """Deliver admitted transitions in order without retaining lifecycle state."""
        while True:
            with self._lifecycle_lock:
                if not self._lifecycle_publications:
                    self._lifecycle_drainer_thread = None
                    return
                publication = self._lifecycle_publications.popleft()

            try:
                if publication.action is not None:
                    publication.action()
                else:
                    status = publication.status
                    assert status is not None
                    self._hub.send(
                        ConstructionStatusChangedMessage.create(self, self._name, status)
                    )

                    # Computed/read-only properties raise only the local equivalent
                    # of INPC; setter-assigned properties alone publish hub messages.
                    self._raise_property_changed("status")
                    self._raise_property_changed("is_constructed")

                    if not self._trigger_disposed:
                        self._status_trigger.on_next(None)
            except BaseException as error:
                publication.error = error
            finally:
                publication.completed.set()

    def _await_lifecycle_publication(
        self, publication: _LifecyclePublication, should_drain: bool
    ) -> None:
        """Drain or wait, escaping only an actual cross-VM thread cycle."""
        if should_drain:
            self._drain_lifecycle_publications()
        elif not publication.completed.is_set():
            caller = threading.get_ident()
            with self._lifecycle_lock:
                owner = self._lifecycle_drainer_thread
            if owner not in (None, caller):
                if not _register_lifecycle_wait(caller, owner):
                    try:
                        publication.completed.wait()
                    finally:
                        _unregister_lifecycle_wait(caller)

        if publication.completed.is_set() and publication.error is not None:
            raise publication.error

    def _finish_terminal_publication(self) -> None:
        """Complete subjects only after the queued Disposed event was delivered."""
        with self._lifecycle_lock:
            if not self._terminal_publication_pending or self._trigger_disposed:
                return
            self._terminal_publication_pending = False
            self._trigger_disposed = True
            active_property_notifications = self._active_property_notifications
            if active_property_notifications:
                self._property_notification_teardown_pending = True

        try:
            self._status_trigger.on_completed()
        except BaseException:
            pass
        try:
            self._status_trigger.dispose()
        except BaseException:
            pass
        if active_property_notifications == 0:
            try:
                self._property_changed_subject.on_completed()
            except BaseException:
                pass
            try:
                self._property_changed_subject.dispose()
            except BaseException:
                pass

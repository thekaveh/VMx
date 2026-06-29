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
from collections.abc import Callable
from typing import TYPE_CHECKING

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
    from vmx.components.protocols import ViewModelType


# ---------------------------------------------------------------------------
# Internal parent interface (mirrors C# IParentCompositeVM)
# ---------------------------------------------------------------------------


class _ParentCompositeVM(ABC):
    """Minimal parent interface used by a child VM for selection delegation.

    Implemented by composite and group base classes. Not part of the public API.
    """

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

        # ── Lifecycle state ──────────────────────────────────────────────────
        self._status: ConstructionStatus = ConstructionStatus.DESTRUCTED
        self._in_flight: bool = False

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

        # ── Selection state ──────────────────────────────────────────────────
        self._is_current: bool = False
        self._parent: _ParentCompositeVM | None = None

        # ── property_changed subject ────────────────────────────────────────
        # Mimics INotifyPropertyChanged — emits property name strings.
        self._property_changed_subject: Subject[str] = Subject()
        self._trigger_disposed: bool = False

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
        # Post-dispose guard: spec/02 invariant 3 — Disposed is terminal. A
        # selection change on an already-disposed VM is a silent no-op (no
        # property_changed emit, no hub PropertyChangedMessage), mirroring Swift
        # (VMX-006). Reads the terminal state under the same lock the
        # lifecycle-race guards use.
        if self._is_disposed():
            return
        if self._is_current == value:
            return
        self._is_current = value
        self._raise_property_changed("is_current")
        self._hub.send(PropertyChangedMessage.create(self, self._name, "is_current"))

    def _set_parent(self, parent: _ParentCompositeVM | None) -> None:
        """Called by CompositeVMBase when this child is added/removed."""
        self._parent = parent

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
        """Emit *property_name* on the property_changed subject."""
        if not self._trigger_disposed:
            self._property_changed_subject.on_next(property_name)

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
        # Idempotent: already Constructed → no-op (no message).
        if self._status == ConstructionStatus.CONSTRUCTED:
            return

        # Validate transition (raises StatusTransitionError for illegal states).
        require(self._status, "construct")

        # Concurrency guard.
        if self._in_flight:
            raise StatusTransitionError(self._status, "construct")
        self._in_flight = True

        if self._background:
            # Emit Constructing synchronously so subscribers immediately see
            # the transition starting, then schedule work on background.
            self._set_status(ConstructionStatus.CONSTRUCTING)

            def _bg_construct(scheduler: SchedulerBase, state: object | None) -> None:
                # dispose() may have run between scheduling and execution.
                # Re-check the terminal state under the lock and abort if disposed
                # (spec/02 invariant 3): no _on_construct(), no marshalled emission.
                if self._is_disposed():
                    self._in_flight = False
                    return

                try:
                    self._on_construct()
                except Exception:
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
                            self._in_flight = False

                    self._dispatcher.foreground.schedule(_fg_rollback)
                    raise

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
                        self._in_flight = False

                self._dispatcher.foreground.schedule(_fg_construct)

            self._dispatcher.background.schedule(_bg_construct)
        else:
            try:
                self._set_status(ConstructionStatus.CONSTRUCTING)
                try:
                    self._on_construct()
                except Exception:
                    # VMX-007: roll _status back to the prior settled state
                    # (Destructed) under the same lock _set_status uses, then
                    # re-raise so the caller sees the original failure. The VM is
                    # left recoverable instead of wedged in Constructing.
                    self._set_status(ConstructionStatus.DESTRUCTED)
                    raise
                self._set_status(ConstructionStatus.CONSTRUCTED)
            finally:
                self._in_flight = False

    # ── Lifecycle: destruct ──────────────────────────────────────────────────
    def destruct(self) -> None:
        """Transitions Constructed → Destructing → Destructed.

        Idempotent from Destructed (no-op, no message emitted).
        """
        if self._status == ConstructionStatus.DESTRUCTED:
            return

        require(self._status, "destruct")

        if self._in_flight:
            raise StatusTransitionError(self._status, "destruct")
        self._in_flight = True

        if self._background:
            self._set_status(ConstructionStatus.DESTRUCTING)

            def _bg_destruct(scheduler: SchedulerBase, state: object | None) -> None:
                # dispose() may have run between scheduling and execution.
                # Re-check the terminal state under the lock and abort if disposed
                # (spec/02 invariant 3): no _on_destruct(), no marshalled emission.
                if self._is_disposed():
                    self._in_flight = False
                    return

                try:
                    self._on_destruct()
                except Exception:
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
                            self._in_flight = False

                    self._dispatcher.foreground.schedule(_fg_rollback)
                    raise

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
                        self._in_flight = False

                self._dispatcher.foreground.schedule(_fg_destruct)

            self._dispatcher.background.schedule(_bg_destruct)
        else:
            try:
                self._set_status(ConstructionStatus.DESTRUCTING)
                try:
                    self._on_destruct()
                except Exception:
                    # VMX-007: roll _status back to the prior settled state
                    # (Constructed) under the lock, then re-raise. The VM is left
                    # recoverable instead of wedged in Destructing.
                    self._set_status(ConstructionStatus.CONSTRUCTED)
                    raise
                self._set_status(ConstructionStatus.DESTRUCTED)
            finally:
                self._in_flight = False

    # ── Lifecycle: reconstruct ───────────────────────────────────────────────
    def reconstruct(self) -> None:
        """Destructs then re-constructs this VM atomically.

        Emits four messages: Destructing, Destructed, Constructing, Constructed.
        """
        require(self._status, "reconstruct")

        if self._in_flight:
            raise StatusTransitionError(self._status, "reconstruct")
        self._in_flight = True

        try:
            # Destruct phase
            self._set_status(ConstructionStatus.DESTRUCTING)
            try:
                self._on_destruct()
            except Exception:
                # VMX-007: a failed destruct phase rolls back to Constructed
                # (the state reconstruct started from) so the VM stays recoverable.
                self._set_status(ConstructionStatus.CONSTRUCTED)
                raise
            self._set_status(ConstructionStatus.DESTRUCTED)

            # Construct phase
            self._set_status(ConstructionStatus.CONSTRUCTING)
            try:
                self._on_construct()
            except Exception:
                # VMX-007: a failed construct phase rolls back to Destructed (the
                # destruct phase already completed) so the VM stays recoverable.
                self._set_status(ConstructionStatus.DESTRUCTED)
                raise
            self._set_status(ConstructionStatus.CONSTRUCTED)
        finally:
            self._in_flight = False

    # ── Lifecycle: dispose ───────────────────────────────────────────────────
    def dispose(self) -> None:
        """Transition to Disposed from any state. Terminal; idempotent.

        Disposes commands and completes the status trigger / property_changed
        subjects.
        """
        if self._status == ConstructionStatus.DISPOSED:
            return

        # _set_status flips _status to Disposed atomically under _lifecycle_lock.
        self._set_status(ConstructionStatus.DISPOSED)
        self._on_dispose()

        # Tear down the status trigger / property_changed subjects under the lock
        # so the flag flip and the Subject disposal cannot interleave with an
        # in-flight background _set_status: that transition either completes its
        # guarded on_next before this runs, or observes Disposed/_trigger_disposed
        # under the same lock and skips it — never an on_next on a disposed
        # Subject (VMX-004).
        with self._lifecycle_lock:
            if not self._trigger_disposed:
                self._trigger_disposed = True
                self._status_trigger.on_completed()
                self._status_trigger.dispose()
                self._property_changed_subject.on_completed()
                self._property_changed_subject.dispose()

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
                command.dispose()

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

    def _on_dispose(self) -> None:  # noqa: B027  — intentional override hook
        """Called by dispose() after status reaches Disposed. Override for cleanup."""

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

    def _set_status(self, new_status: ConstructionStatus) -> None:
        """Update status, emit hub message, and fire command trigger."""
        # The terminal check, the _status write, the hub publish and the
        # status-trigger on_next all run under _lifecycle_lock so the whole
        # transition is atomic with respect to dispose() — a background transition
        # racing dispose() can neither resurrect the VM, publish a post-dispose
        # status message, nor on_next a disposed Subject (VMX-004; spec/02
        # invariant 3: Disposed is terminal).
        with self._lifecycle_lock:
            if self._status is ConstructionStatus.DISPOSED:
                return

            self._status = new_status

            self._hub.send(ConstructionStatusChangedMessage.create(self, self._name, new_status))

            # status and is_constructed are computed/read-only, so they raise INPC-equivalent
            # property_changed only — no PropertyChangedMessage on the hub (spec 03-messages.md
            # publishes only on setter-assigned properties).
            self._raise_property_changed("status")
            self._raise_property_changed("is_constructed")

            if not self._trigger_disposed:
                self._status_trigger.on_next(None)

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

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

import reactivex as rx
from reactivex.abc import SchedulerBase
from reactivex.subject import Subject

from vmx.commands.relay_command import RelayCommand
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import require
from vmx.messages.construction_status import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHub

if TYPE_CHECKING:
    from vmx.components.protocols import ViewModelType


# ---------------------------------------------------------------------------
# Internal parent interface (mirrors C# IParentCompositeVM)
# ---------------------------------------------------------------------------


class _ParentCompositeVM(ABC):
    """Minimal parent interface used by a child VM for selection delegation.

    Implemented by all composite / group base classes (Tasks 7-8).
    Not part of the public API.
    """

    @property
    @abstractmethod
    def current_child(self) -> object | None: ...

    @abstractmethod
    def select_child(self, vm: _ComponentVMBase) -> None: ...

    @abstractmethod
    def deselect_child(self, vm: _ComponentVMBase) -> None: ...


# ---------------------------------------------------------------------------
# _ComponentVMBase
# ---------------------------------------------------------------------------


class _ComponentVMBase(ABC):
    """Abstract base class for all ComponentVM variants.

    Subclasses must implement:
    - ``type`` property (returns ViewModelType)
    - Override ``_on_construct()`` / ``_on_destruct()`` / ``_on_dispose()`` for
      additional lifecycle behaviour (used by composite/group in Tasks 7-8).

    Do NOT instantiate directly — use a builder.
    """

    # ── Constructor ──────────────────────────────────────────────────────────
    def __init__(
        self,
        *,
        name: str,
        hint: str,
        hub: MessageHub[Message],
        dispatcher: Dispatcher,
        on_construct: Callable[[], None] | None = None,
        on_destruct: Callable[[], None] | None = None,
        background: bool = False,
    ) -> None:
        self._name: str = name
        self._hint: str = hint
        self._hub: MessageHub[Message] = hub
        self._dispatcher: Dispatcher = dispatcher
        self._on_construct_cb: Callable[[], None] | None = on_construct
        self._on_destruct_cb: Callable[[], None] | None = on_destruct
        self._background: bool = background

        # ── Lifecycle state ──────────────────────────────────────────────────
        self._status: ConstructionStatus = ConstructionStatus.DESTRUCTED
        self._in_flight: bool = False

        # ── Selection state ──────────────────────────────────────────────────
        self._is_current: bool = False
        self._parent: _ParentCompositeVM | None = None

        # ── property_changed subject ────────────────────────────────────────
        # Mimics INotifyPropertyChanged — emits property name strings.
        self._property_changed_subject: Subject[str] = Subject()
        self._trigger_disposed: bool = False

        # ── Status-change trigger (drives command CanExecute re-eval) ────────
        self._status_trigger: Subject[None] = Subject()

        # ── Build built-in commands ─────────────────────────────────────────
        trigger_obs: rx.Observable[object] = self._status_trigger

        self._select_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(self.can_select)
            .task(self.select)
            .triggers(trigger_obs)
            .build()
        )
        self._deselect_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(self.can_deselect)
            .task(self.deselect)
            .triggers(trigger_obs)
            .build()
        )
        self._select_next_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(self._can_select_next)
            .task(self._select_next)
            .triggers(trigger_obs)
            .build()
        )
        self._select_previous_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(self._can_select_previous)
            .task(self._select_previous)
            .triggers(trigger_obs)
            .build()
        )
        self._reconstruct_command: RelayCommand = (
            RelayCommand.builder()
            .predicate(self.can_reconstruct)
            .task(self.reconstruct)
            .triggers(trigger_obs)
            .build()
        )

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
        """
        return self._property_changed_subject

    def _raise_property_changed(self, property_name: str) -> None:
        """Emit *property_name* on the property_changed subject."""
        if not self._trigger_disposed:
            self._property_changed_subject.on_next(property_name)

    # ── Built-in commands ────────────────────────────────────────────────────
    @property
    def select_command(self) -> RelayCommand:
        return self._select_command

    @property
    def deselect_command(self) -> RelayCommand:
        return self._deselect_command

    @property
    def select_next_command(self) -> RelayCommand:
        return self._select_next_command

    @property
    def select_previous_command(self) -> RelayCommand:
        return self._select_previous_command

    @property
    def reconstruct_command(self) -> RelayCommand:
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
                try:
                    self._on_construct()
                    self._set_status(ConstructionStatus.CONSTRUCTED)
                finally:
                    self._in_flight = False

            self._dispatcher.background.schedule(_bg_construct)
        else:
            try:
                self._set_status(ConstructionStatus.CONSTRUCTING)
                self._on_construct()
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
                try:
                    self._on_destruct()
                    self._set_status(ConstructionStatus.DESTRUCTED)
                finally:
                    self._in_flight = False

            self._dispatcher.background.schedule(_bg_destruct)
        else:
            try:
                self._set_status(ConstructionStatus.DESTRUCTING)
                self._on_destruct()
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
            self._on_destruct()
            self._set_status(ConstructionStatus.DESTRUCTED)

            # Construct phase
            self._set_status(ConstructionStatus.CONSTRUCTING)
            self._on_construct()
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

        self._set_status(ConstructionStatus.DISPOSED)
        self._on_dispose()

        # Complete and dispose subjects.
        if not self._trigger_disposed:
            self._trigger_disposed = True
            self._status_trigger.on_completed()
            self._status_trigger.dispose()
            self._property_changed_subject.on_completed()
            self._property_changed_subject.dispose()

        # Dispose commands.
        self._select_command.dispose()
        self._deselect_command.dispose()
        self._select_next_command.dispose()
        self._select_previous_command.dispose()
        self._reconstruct_command.dispose()

    # ── Selection predicates ─────────────────────────────────────────────────
    def can_select(self) -> bool:
        """True iff parent is not None, this is not current, and Constructed."""
        return (
            self._parent is not None
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

    def _on_dispose(self) -> None:  # noqa: B027
        """Called by dispose() after status reaches Disposed. Override for cleanup."""

    # -- SelectNext / SelectPrevious (not implemented in v1.0) ---------------
    # Parent enumeration (sibling navigation) is not implemented in v1.0 — always returns False.
    def _can_select_next(self) -> bool:
        return False

    def _select_next(self) -> None:  # noqa: B027
        pass

    def _can_select_previous(self) -> bool:
        return False

    def _select_previous(self) -> None:  # noqa: B027
        pass

    # ── Internal helpers ─────────────────────────────────────────────────────
    def _set_status(self, new_status: ConstructionStatus) -> None:
        """Update status, emit hub message, and fire command trigger."""
        self._status = new_status

        # Emit on hub.
        self._hub.send(ConstructionStatusChangedMessage.create(self, self._name, new_status))

        # Raise property_changed for status and is_constructed (INPC-equivalent only;
        # these are computed/read-only properties so no PropertyChangedMessage is
        # published on the hub — spec 03-messages.md: only setter-assigned properties
        # emit PropertyChangedMessage).
        self._raise_property_changed("status")
        self._raise_property_changed("is_constructed")

        # Fire command trigger so predicates are re-evaluated.
        if not self._trigger_disposed:
            self._status_trigger.on_next(None)

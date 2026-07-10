"""RelayCommand and RelayCommandOf — concrete Command Protocol implementations.

Spec: spec/04-commands.md

Naming
------
The parameterised command is ``RelayCommandOf`` (parity with the C#
``RelayCommand<T>`` / TypeScript ``RelayCommandOf`` surface). The legacy v1.0.0
``RelayCommandOfT`` / ``RelayCommandOfTBuilder`` identity aliases were removed in
vmx v3.0.0 (ADR-0052; deferral originally recorded in ADR-0009).

Behavior contract:
- Predicate null → can_execute returns True unconditionally.
- Task null → execute is a no-op (no exception raised).
- Execute is GATED on can_execute: if can_execute() returns False, execute returns
  immediately without invoking the task (matches fixture row "predicate-false").
- Predicate that raises → treated as False (exception does NOT propagate).
- Task that raises → exception propagates to the caller of execute.
- Trigger emissions fire can_execute_changed.
- raise_can_execute_changed emits one imperative re-evaluation notification.
- Disposed commands are inert: can_execute returns False and execute is a no-op.
- Builder is IMMUTABLE (BLD-001): every setter returns a NEW builder instance.
- Triggers are additive: multiple .triggers(obs) calls combine into the trigger set.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

T = TypeVar("T")


# ---------------------------------------------------------------------------
# RelayCommand (non-parameterized)
# ---------------------------------------------------------------------------


class RelayCommand:
    """Non-parameterized command built via an immutable fluent builder.

    Use ``RelayCommand.builder()`` to start a build.
    """

    def __init__(
        self,
        task: Callable[[], None] | None,
        predicate: Callable[[], bool] | None,
        triggers: list[rx.Observable[object]],
    ) -> None:
        self._task = task
        self._predicate = predicate
        self._can_execute_changed_subject: Subject[None] = Subject()
        self._disposed = False
        self._subscriptions = [
            t.subscribe(lambda _: self.raise_can_execute_changed()) for t in triggers
        ]

    # ------------------------------------------------------------------
    # Command protocol implementation
    # ------------------------------------------------------------------

    def can_execute(self, parameter: object = None) -> bool:
        """Return True if the predicate is absent or returns True.

        If the predicate raises, returns False (defensive — exception does not
        propagate).
        """
        if self._disposed:
            return False
        if self._predicate is None:
            return True
        try:
            return self._predicate()
        except Exception:
            return False

    def execute(self, parameter: object = None) -> None:
        """Invoke the task if and only if ``can_execute()`` is True.

        If no task was configured, this is a no-op.
        If the task raises, the exception propagates to the caller.
        """
        if not self.can_execute(parameter):
            return
        if self._task is not None:
            self._task()

    @property
    def can_execute_changed(self) -> rx.Observable[None]:
        """Observable that emits ``None`` on each trigger emission.

        The backing Subject is sealed behind ``as_observable`` so callers can
        only subscribe — never ``on_next``/``dispose`` the internal stream
        (VMX-013).
        """
        return self._can_execute_changed_subject.pipe(ops.as_observable())

    def raise_can_execute_changed(self) -> None:
        """Emit one re-evaluation notification without invoking user delegates.

        Repeated calls are additive. Calls after :meth:`dispose` are no-ops.
        """
        if self._disposed:
            return
        self._can_execute_changed_subject.on_next(None)

    def dispose(self) -> None:
        """Dispose all trigger subscriptions and complete the subject.

        Idempotent: subsequent calls are a no-op rather than raising
        :class:`reactivex.internal.exceptions.DisposedException`.
        """
        if self._disposed:
            return
        self._disposed = True
        self._can_execute_changed_subject.on_next(None)
        for sub in self._subscriptions:
            sub.dispose()
        self._can_execute_changed_subject.on_completed()
        self._can_execute_changed_subject.dispose()

    # ------------------------------------------------------------------
    # Builder entry-point
    # ------------------------------------------------------------------

    @staticmethod
    def builder() -> RelayCommandBuilder:
        """Return a new immutable builder for ``RelayCommand``."""
        return RelayCommandBuilder()


@dataclasses.dataclass(frozen=True)
class RelayCommandBuilder:
    """Immutable fluent builder for :class:`RelayCommand`.

    Each setter returns a NEW builder instance via ``dataclasses.replace``
    (satisfies BLD-001).
    """

    _task: Callable[[], None] | None = dataclasses.field(default=None)
    _predicate: Callable[[], bool] | None = dataclasses.field(default=None)
    _triggers: tuple[rx.Observable[object], ...] = dataclasses.field(default_factory=tuple)

    def task(self, callable_: Callable[[], None]) -> RelayCommandBuilder:
        """Set the task to invoke on execute. Returns a new builder."""
        return dataclasses.replace(self, _task=callable_)

    def predicate(self, callable_: Callable[[], bool]) -> RelayCommandBuilder:
        """Set the predicate that gates can_execute. Returns a new builder."""
        return dataclasses.replace(self, _predicate=callable_)

    def triggers(self, observable: rx.Observable[object]) -> RelayCommandBuilder:
        """Add a trigger observable (additive). Returns a new builder."""
        return dataclasses.replace(self, _triggers=(*self._triggers, observable))

    def build(self) -> RelayCommand:
        """Build and return the :class:`RelayCommand`.

        Succeeds even with no task, predicate, or triggers.
        """
        return RelayCommand(self._task, self._predicate, list(self._triggers))


# ---------------------------------------------------------------------------
# RelayCommandOf (parameterized)
# ---------------------------------------------------------------------------


class RelayCommandOf(Generic[T]):
    """Parameterized command built via an immutable fluent builder.

    Use ``RelayCommandOf.builder()`` to start a build.
    """

    def __init__(
        self,
        task: Callable[[T | None], None] | None,
        predicate: Callable[[T | None], bool] | None,
        triggers: list[rx.Observable[object]],
    ) -> None:
        self._task = task
        self._predicate = predicate
        self._can_execute_changed_subject: Subject[None] = Subject()
        self._disposed = False
        self._subscriptions = [
            t.subscribe(lambda _: self.raise_can_execute_changed()) for t in triggers
        ]

    # ------------------------------------------------------------------
    # Command protocol implementation
    # ------------------------------------------------------------------

    def can_execute(self, parameter: T | None = None) -> bool:
        """Return True if the predicate is absent or returns True for *parameter*.

        If the predicate raises, returns False (defensive).
        """
        if self._disposed:
            return False
        if self._predicate is None:
            return True
        try:
            return self._predicate(parameter)
        except Exception:
            return False

    def execute(self, parameter: T | None = None) -> None:
        """Invoke the task with *parameter* if and only if ``can_execute()`` is True.

        If no task was configured, this is a no-op.
        If the task raises, the exception propagates to the caller.
        """
        if not self.can_execute(parameter):
            return
        if self._task is not None:
            self._task(parameter)

    @property
    def can_execute_changed(self) -> rx.Observable[None]:
        """Observable that emits ``None`` on each trigger emission.

        The backing Subject is sealed behind ``as_observable`` so callers can
        only subscribe — never ``on_next``/``dispose`` the internal stream
        (VMX-013).
        """
        return self._can_execute_changed_subject.pipe(ops.as_observable())

    def raise_can_execute_changed(self) -> None:
        """Emit one re-evaluation notification without invoking user delegates.

        Repeated calls are additive. Calls after :meth:`dispose` are no-ops.
        """
        if self._disposed:
            return
        self._can_execute_changed_subject.on_next(None)

    def dispose(self) -> None:
        """Dispose all trigger subscriptions and complete the subject.

        Idempotent: subsequent calls are a no-op rather than raising
        :class:`reactivex.internal.exceptions.DisposedException`.
        """
        if self._disposed:
            return
        self._disposed = True
        self._can_execute_changed_subject.on_next(None)
        for sub in self._subscriptions:
            sub.dispose()
        self._can_execute_changed_subject.on_completed()
        self._can_execute_changed_subject.dispose()

    # ------------------------------------------------------------------
    # Builder entry-point
    # ------------------------------------------------------------------

    @staticmethod
    def builder() -> RelayCommandOfBuilder[T]:
        """Return a new immutable builder for ``RelayCommandOf``."""
        return RelayCommandOfBuilder()


@dataclasses.dataclass(frozen=True)
class RelayCommandOfBuilder(Generic[T]):
    """Immutable fluent builder for :class:`RelayCommandOf`.

    Each setter returns a NEW builder instance via ``dataclasses.replace``
    (satisfies BLD-001).
    """

    _task: Callable[[T | None], None] | None = dataclasses.field(default=None)
    _predicate: Callable[[T | None], bool] | None = dataclasses.field(default=None)
    _triggers: tuple[rx.Observable[object], ...] = dataclasses.field(default_factory=tuple)

    def task(self, callable_: Callable[[T | None], None]) -> RelayCommandOfBuilder[T]:
        """Set the parameterized task. Returns a new builder."""
        return dataclasses.replace(self, _task=callable_)

    def predicate(self, callable_: Callable[[T | None], bool]) -> RelayCommandOfBuilder[T]:
        """Set the parameterized predicate. Returns a new builder."""
        return dataclasses.replace(self, _predicate=callable_)

    def triggers(self, observable: rx.Observable[object]) -> RelayCommandOfBuilder[T]:
        """Add a trigger observable (additive). Returns a new builder."""
        return dataclasses.replace(self, _triggers=(*self._triggers, observable))

    def build(self) -> RelayCommandOf[T]:
        """Build and return the :class:`RelayCommandOf`.

        Succeeds even with no task, predicate, or triggers.
        """
        return RelayCommandOf(self._task, self._predicate, list(self._triggers))

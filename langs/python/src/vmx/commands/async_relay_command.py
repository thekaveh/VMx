"""AsyncRelayCommand — a cancellable async command.

Spec: spec/04-commands.md §10 (async command cancellation), ADR-0056.

Behavior contract:
- ``task`` is a coroutine function (``() -> Awaitable[None]``). asyncio delivers
  cancellation by raising ``CancelledError`` at the task's next await point — no
  explicit token is threaded through, matching idiomatic asyncio.
- ``can_execute`` returns False while an execution is in flight, so the command
  cannot double-run; it fires ``can_execute_changed`` when the in-flight state
  flips on start and on completion.
- ``cancel()`` cancels the in-flight task. Cancellation is NON-THROWING by default
  (alignment with the dialog cancellation contract, DIA-007 / spec ch.19 §7):
  the awaited ``execute_async`` returns normally on cancel. Opt into the throwing
  mode with ``throw_on_cancel=True``.
- A faulting task (non-cancellation) propagates to the awaiter of
  ``execute_async``; on the fire-and-forget ``execute()`` path — which has no
  caller to propagate to — it is routed to the :attr:`errors` channel instead of
  being swallowed (mirrors ``ConfirmationDecoratorCommand``, VMX-009 / ADR-0049).
- Builder is IMMUTABLE (BLD-001): every setter returns a NEW builder instance.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from threading import RLock

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx._asyncio_runner import submit_background


class AsyncRelayCommand:
    """Cancellable async command built via an immutable fluent builder.

    Use ``AsyncRelayCommand.builder()`` to start a build.
    """

    def __init__(
        self,
        task: Callable[[], Awaitable[None]] | None,
        predicate: Callable[[], bool] | None,
        triggers: list[rx.Observable[object]],
        *,
        throw_on_cancel: bool = False,
    ) -> None:
        self._task = task
        self._predicate = predicate
        self._throw_on_cancel = throw_on_cancel
        self._gate = RLock()
        self._can_execute_changed_subject: Subject[None] = Subject()
        self._errors: Subject[BaseException] = Subject()
        self._current_task: asyncio.Task[None] | None = None
        self._current_loop: asyncio.AbstractEventLoop | None = None
        self._cancel_requested = False
        self._is_executing = False
        self._disposed = False
        self._subscriptions = [
            t.subscribe(lambda _: self.raise_can_execute_changed()) for t in triggers
        ]

    # ------------------------------------------------------------------
    # Command protocol implementation
    # ------------------------------------------------------------------

    @property
    def is_executing(self) -> bool:
        """True while an execution is in flight; False when idle."""
        with self._gate:
            return self._is_executing

    def can_execute(self, parameter: object = None) -> bool:
        """Return False while in flight; otherwise the predicate result (or True).

        A predicate that raises is treated as False (defensive).
        """
        with self._gate:
            if self._disposed or self._is_executing:
                return False
        if self._predicate is None:
            return True
        try:
            allowed = self._predicate()
        except Exception:
            return False
        with self._gate:
            return allowed and not self._disposed and not self._is_executing

    async def execute_async(self, parameter: object = None) -> None:
        """Run the async task once, observing cancellation.

        No-op when ``can_execute()`` is False or no task is configured. By default
        a cancellation requested via :meth:`cancel` is swallowed and this coroutine
        returns normally; with ``throw_on_cancel=True`` the ``CancelledError`` is
        re-raised to the awaiter.
        """
        task_factory = self._task
        if task_factory is None:
            return
        with self._gate:
            if self._disposed or self._is_executing:
                return
        if self._predicate is not None:
            try:
                if not self._predicate():
                    return
            except Exception:
                return
        with self._gate:
            if self._disposed or self._is_executing:
                return
            self._cancel_requested = False
            self._is_executing = True
        self.raise_can_execute_changed()
        inner: asyncio.Task[None] = asyncio.ensure_future(task_factory())
        with self._gate:
            self._current_task = inner
            self._current_loop = asyncio.get_running_loop()
            cancel_immediately = self._cancel_requested or self._disposed
        if cancel_immediately:
            inner.cancel()
        try:
            await inner
        except asyncio.CancelledError:
            # Non-throwing default (DIA-007 alignment): swallow only the
            # cancellation WE requested via cancel(); re-raise an external one so
            # asyncio cancellation semantics are preserved.
            with self._gate:
                cancel_requested = self._cancel_requested
            if self._throw_on_cancel or not cancel_requested:
                raise
        finally:
            with self._gate:
                self._is_executing = False
                self._current_task = None
                self._current_loop = None
            self.raise_can_execute_changed()

    def execute(self, parameter: object = None) -> None:
        """Fire-and-forget. Schedules ``execute_async`` on the current event loop.

        A faulting task is routed to the :attr:`errors` channel instead of being
        swallowed; a cancellation is already swallowed by the non-throwing default.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            future = submit_background(self.execute_async(parameter))
            future.add_done_callback(self._on_done)
            return
        task = loop.create_task(self.execute_async(parameter))
        task.add_done_callback(self._on_done)

    def cancel(self) -> None:
        """Request cancellation of the in-flight task; a no-op when idle."""
        with self._gate:
            self._cancel_requested = True
            task = self._current_task
            loop = self._current_loop
        if task is not None and not task.done():
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(task.cancel)
            else:
                task.cancel()

    @property
    def can_execute_changed(self) -> rx.Observable[None]:
        """Observable that emits ``None`` on each trigger and in-flight state flip.

        The backing Subject is sealed behind ``as_observable`` so callers can only
        subscribe — never ``on_next``/``dispose`` the internal stream (VMX-013).
        """
        return self._can_execute_changed_subject.pipe(ops.as_observable())

    @property
    def errors(self) -> rx.Observable[BaseException]:
        """Observable surfacing a fault from the fire-and-forget :meth:`execute`.

        ``execute()`` returns immediately, so a throwing task cannot propagate to
        the caller; instead of swallowing it the error is emitted here. Await
        :meth:`execute_async` to observe it inline. Cancellations never reach this
        channel. Completes on :meth:`dispose`.
        """
        return self._errors.pipe(ops.as_observable())

    def _on_done(self, task: asyncio.Future[None] | Future[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._emit_error(exc)

    def _emit_error(self, exc: BaseException) -> None:
        with self._gate:
            if self._disposed:
                return
        self._errors.on_next(exc)

    def raise_can_execute_changed(self) -> None:
        """Emit one re-evaluation notification without invoking user delegates.

        Valid while idle or in flight; repeated calls are additive. Calls after
        :meth:`dispose` are no-ops.
        """
        with self._gate:
            if self._disposed:
                return
        self._can_execute_changed_subject.on_next(None)

    def dispose(self) -> None:
        """Cancel any in-flight task, release subscriptions, complete the subjects.

        Idempotent: subsequent calls are a no-op.
        """
        with self._gate:
            if self._disposed:
                return
            self._disposed = True
        self.cancel()
        for sub in self._subscriptions:
            sub.dispose()
        self._can_execute_changed_subject.on_completed()
        self._can_execute_changed_subject.dispose()
        self._errors.on_completed()
        self._errors.dispose()

    # ------------------------------------------------------------------
    # Builder entry-point
    # ------------------------------------------------------------------

    @staticmethod
    def builder() -> AsyncRelayCommandBuilder:
        """Return a new immutable builder for ``AsyncRelayCommand``."""
        return AsyncRelayCommandBuilder()


@dataclasses.dataclass(frozen=True)
class AsyncRelayCommandBuilder:
    """Immutable fluent builder for :class:`AsyncRelayCommand`.

    Each setter returns a NEW builder instance via ``dataclasses.replace``
    (satisfies BLD-001).
    """

    _task: Callable[[], Awaitable[None]] | None = dataclasses.field(default=None)
    _predicate: Callable[[], bool] | None = dataclasses.field(default=None)
    _triggers: tuple[rx.Observable[object], ...] = dataclasses.field(default_factory=tuple)
    _throw_on_cancel: bool = dataclasses.field(default=False)

    def task(self, callable_: Callable[[], Awaitable[None]]) -> AsyncRelayCommandBuilder:
        """Set the cancellable async task. Returns a new builder."""
        return dataclasses.replace(self, _task=callable_)

    def predicate(self, callable_: Callable[[], bool]) -> AsyncRelayCommandBuilder:
        """Set the predicate that gates can_execute. Returns a new builder."""
        return dataclasses.replace(self, _predicate=callable_)

    def triggers(self, observable: rx.Observable[object]) -> AsyncRelayCommandBuilder:
        """Add a trigger observable (additive). Returns a new builder."""
        return dataclasses.replace(self, _triggers=(*self._triggers, observable))

    def throw_on_cancel(self, value: bool = True) -> AsyncRelayCommandBuilder:
        """Opt into re-raising the cancellation to the awaiter. Returns a new builder."""
        return dataclasses.replace(self, _throw_on_cancel=value)

    def build(self) -> AsyncRelayCommand:
        """Build and return the :class:`AsyncRelayCommand` (succeeds even with no task)."""
        return AsyncRelayCommand(
            self._task,
            self._predicate,
            list(self._triggers),
            throw_on_cancel=self._throw_on_cancel,
        )

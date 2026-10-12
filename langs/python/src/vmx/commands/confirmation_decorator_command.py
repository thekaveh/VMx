"""ConfirmationDecoratorCommand — gates execution on an async confirm delegate.

See spec/04-commands.md §8.3 (including §8.3.2 for asynchronous inner
commands), ADR-0012, ADR-0049, ADR-0134, and ADR-0145.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import Any

from reactivex import Observable
from reactivex import operators as ops
from reactivex.internal.exceptions import DisposedException
from reactivex.subject import Subject

from vmx._asyncio_runner import submit_background
from vmx.commands.protocols import Command, _AsyncCommand
from vmx.commands.relay_command import _run_disposal_steps


class ConfirmationDecoratorCommand:
    """Wraps a single inner command, prompting an async ``confirm`` delegate
    before invoking. UI-agnostic per ADR-0012.

    An inner command that offers an awaitable ``execute_async`` (for example
    :class:`~vmx.commands.AsyncRelayCommand` or another
    ``ConfirmationDecoratorCommand``) is asynchronous: :meth:`execute_async`
    awaits it, so the awaited call completes when the inner operation
    completes (spec §8.3.2, ADR-0145). The decorator never owns, cancels, or
    disposes the inner command.
    """

    def __init__(
        self,
        inner: Command,
        confirm: Callable[[], Awaitable[bool]],
    ) -> None:
        self._inner = inner
        self._confirm = confirm
        self._disposed = False
        self._errors: Subject[BaseException] = Subject()

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._inner.can_execute_changed

    @property
    def errors(self) -> Observable[BaseException]:
        """Observable surfacing an error from the fire-and-forget :meth:`execute`.

        ``execute()`` schedules the confirm flow and returns immediately, so a
        rejecting confirm delegate or a throwing synchronous inner command cannot
        propagate to the caller the way the base command's task does. Instead of
        swallowing it, the error is emitted here (VMX-009). An asynchronous inner
        command is started through its own ``execute()`` and reports its failures
        on its own error channel, never here (spec §8.3.2). Await
        :meth:`execute_async` to observe failures inline. Completes on
        :meth:`dispose`.
        """
        return self._errors.pipe(ops.as_observable())

    def can_execute(self, parameter: Any = None) -> bool:
        return not self._disposed and self._inner.can_execute(parameter)

    def execute(self, parameter: Any = None) -> None:
        """Fire-and-forget. Schedules the confirm flow on the current event loop.

        Once confirmed, the inner command is invoked through its own ``execute()``,
        so an asynchronous inner runs as the inner's own fire-and-forget call and
        reports its failures on its own error channel; this decorator does not
        watch it (spec §8.3.2). A rejecting confirm delegate or a throwing
        synchronous inner command is routed to the :attr:`errors` channel instead
        of being swallowed (VMX-009).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            future = submit_background(self._run(parameter, await_inner=False))
            future.add_done_callback(self._on_done)
            return
        task = loop.create_task(self._run(parameter, await_inner=False))
        # Surface the failure on the error channel; skip cancelled tasks —
        # Task.exception() raises CancelledError for those, which would error
        # the loop's callback.
        task.add_done_callback(self._on_done)

    async def execute_async(self, parameter: Any = None) -> None:
        """Await the confirmation, then the inner invocation it admits.

        Completes without invoking the inner command when ``confirm`` resolves
        False. Otherwise invokes the inner command exactly once: an asynchronous
        inner through ``await inner.execute_async(parameter)``, so this call
        completes when the inner operation completes, and a synchronous inner
        through ``inner.execute(parameter)`` (spec §8.3.2, ADR-0145).

        A failure of the confirmation or of the inner invocation propagates to
        the awaiter unchanged and is not emitted on :attr:`errors`. The inner
        command keeps its own admission and cancellation: a busy
        ``AsyncRelayCommand`` drops the call, and its ``cancel()`` outcome reaches
        the awaiter unchanged.
        """
        await self._run(parameter, await_inner=True)

    async def _run(self, parameter: Any, *, await_inner: bool) -> None:
        if not self.can_execute(parameter):
            return
        # A confirmation that resolves after disposal runs nothing (spec §8.4).
        if not await self._confirm() or self._disposed:
            return
        inner = self._inner
        if await_inner and isinstance(inner, _AsyncCommand):
            await inner.execute_async(parameter)
        else:
            inner.execute(parameter)

    def _on_done(self, task: asyncio.Future[None] | Future[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._emit_error(exc)

    def _emit_error(self, exc: BaseException) -> None:
        # The subject is completed+disposed on dispose(); a failure arriving
        # after dispose must not raise reactivex DisposedException.
        if self._disposed:
            return
        # Off the event loop the confirmation completes on the background
        # runner's thread, so dispose() on another thread can dispose the
        # subject between the check above and on_next. That failure arrives
        # after disposal and is dropped (spec §8.4, ADR-0134), as
        # SearchableState drops its late debounce result.
        try:
            self._errors.on_next(exc)
        except DisposedException:
            pass

    def dispose(self) -> None:
        """Make the decorator inert and complete the :attr:`errors` channel.

        Idempotent (spec §8.4, ADR-0134). A pending confirmation that resolves
        later runs no inner command and emits nothing. The inner command stays
        owned by its creator: disposal neither cancels nor disposes it, so an
        awaited inner operation already running still completes, and
        ``can_execute_changed`` delegates lazily to it.
        """
        if self._disposed:
            return
        self._disposed = True
        _run_disposal_steps(self._errors.on_completed, self._errors.dispose)

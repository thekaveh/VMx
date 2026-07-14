"""ConfirmationDecoratorCommand — gates execution on an async confirm delegate.

See spec/04-commands.md §Decorators and ADR-0012.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import Any

from reactivex import Observable
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx._asyncio_runner import submit_background
from vmx.commands.protocols import Command


class ConfirmationDecoratorCommand:
    """Wraps a single inner command, prompting an async ``confirm`` delegate
    before invoking. UI-agnostic per ADR-0012.
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
        rejecting confirm delegate or a throwing inner command cannot propagate
        to the caller the way the base command's task does. Instead of
        swallowing it, the error is emitted here (VMX-009). Await
        :meth:`execute_async` to observe it inline. Completes on :meth:`dispose`.
        """
        return self._errors.pipe(ops.as_observable())

    def can_execute(self, parameter: Any = None) -> bool:
        return self._inner.can_execute(parameter)

    def execute(self, parameter: Any = None) -> None:
        """Fire-and-forget. Schedules ``execute_async`` on the current event loop.

        A rejecting confirm delegate or a throwing inner command is routed to
        the :attr:`errors` channel instead of being swallowed (VMX-009).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            future = submit_background(self.execute_async(parameter))
            future.add_done_callback(self._on_done)
            return
        task = loop.create_task(self.execute_async(parameter))
        # Surface the failure on the error channel; skip cancelled tasks —
        # Task.exception() raises CancelledError for those, which would error
        # the loop's callback.
        task.add_done_callback(self._on_done)

    async def execute_async(self, parameter: Any = None) -> None:
        if not self.can_execute(parameter):
            return
        if await self._confirm():
            self._inner.execute(parameter)

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
        self._errors.on_next(exc)

    def dispose(self) -> None:
        """Mark the decorator as disposed and complete the :attr:`errors` channel.

        Idempotent. ``can_execute_changed`` delegates lazily to the inner
        command, so the decorator owns no other subscriptions to release.
        Provided for API symmetry with the C# IDisposable surface (see
        ``CompositeCommand.dispose``).
        """
        if self._disposed:
            return
        self._disposed = True
        self._errors.on_completed()
        self._errors.dispose()

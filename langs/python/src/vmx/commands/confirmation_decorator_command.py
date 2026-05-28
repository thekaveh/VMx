"""ConfirmationDecoratorCommand — gates execution on an async confirm delegate.

See spec/04-commands.md §Decorators and ADR-0012.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from reactivex import Observable

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

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._inner.can_execute_changed

    def can_execute(self, parameter: Any = None) -> bool:
        return self._inner.can_execute(parameter)

    def execute(self, parameter: Any = None) -> None:
        """Fire-and-forget. Schedules ``execute_async`` on the current event loop."""
        try:
            task = asyncio.get_running_loop().create_task(self.execute_async(parameter))
            # Retrieve any exception so Python does not log "exception never retrieved".
            task.add_done_callback(lambda t: t.exception())
        except RuntimeError:
            asyncio.run(self.execute_async(parameter))

    async def execute_async(self, parameter: Any = None) -> None:
        if not self.can_execute(parameter):
            return
        if await self._confirm():
            self._inner.execute(parameter)

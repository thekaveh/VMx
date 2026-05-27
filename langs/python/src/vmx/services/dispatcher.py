"""Dispatcher Protocol and RxDispatcher concrete implementation.

See spec/11-threading.md for the threading contract.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from reactivex.abc import SchedulerBase
from reactivex.scheduler import ImmediateScheduler, ThreadPoolScheduler
from reactivex.scheduler.eventloop import AsyncIOScheduler


@runtime_checkable
class Dispatcher(Protocol):
    """Paired Rx schedulers for foreground (UI) and background work."""

    @property
    def foreground(self) -> SchedulerBase:
        """Scheduler for UI-thread (foreground) work."""
        ...

    @property
    def background(self) -> SchedulerBase:
        """Scheduler for background work."""
        ...


class RxDispatcher:
    """Default dispatcher.  Caller injects schedulers explicitly.

    Convenience factories:
    - ``immediate()`` — both schedulers are ``ImmediateScheduler``; useful in
      console apps and synchronous tests.
    - ``asyncio(loop)`` — foreground is ``AsyncIOScheduler``, background is
      ``ThreadPoolScheduler``; suitable for asyncio-based UI frameworks.
    """

    def __init__(
        self,
        foreground: SchedulerBase,
        background: SchedulerBase,
    ) -> None:
        self._foreground = foreground
        self._background = background

    @property
    def foreground(self) -> SchedulerBase:
        """Scheduler for UI-thread (foreground) work."""
        return self._foreground

    @property
    def background(self) -> SchedulerBase:
        """Scheduler for background work."""
        return self._background

    @classmethod
    def immediate(cls) -> RxDispatcher:
        """Return a dispatcher with ``ImmediateScheduler`` for both fg and bg.

        Useful in console / CLI tools and synchronous unit tests.
        """
        return cls(
            foreground=ImmediateScheduler(),
            background=ImmediateScheduler(),
        )

    @classmethod
    def asyncio(cls, loop: asyncio.AbstractEventLoop | None = None) -> RxDispatcher:
        """Return a dispatcher with ``AsyncIOScheduler`` fg + ``ThreadPoolScheduler`` bg.

        Args:
            loop: Optional asyncio event loop to pass to ``AsyncIOScheduler``.
                  When *None*, a fresh loop is created via
                  ``asyncio.new_event_loop()``.
        """
        resolved_loop: asyncio.AbstractEventLoop = (
            loop if loop is not None else asyncio.new_event_loop()
        )
        fg = AsyncIOScheduler(resolved_loop)
        return cls(foreground=fg, background=ThreadPoolScheduler())

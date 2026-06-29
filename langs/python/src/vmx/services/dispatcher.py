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
        # Set by ``asyncio()`` to the event loop driving the foreground
        # scheduler; ``None`` for loop-less dispatchers (e.g. ``immediate()``).
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def foreground(self) -> SchedulerBase:
        """Scheduler for UI-thread (foreground) work."""
        return self._foreground

    @property
    def background(self) -> SchedulerBase:
        """Scheduler for background work."""
        return self._background

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The asyncio event loop backing the foreground scheduler, if any.

        Populated by :meth:`asyncio`; ``None`` for loop-less dispatchers such as
        :meth:`immediate`. Exposed so a caller that let the factory create the
        loop can drive it (``loop.run_forever()``) and close it
        (``loop.close()``) — otherwise the loop's selector file descriptor is
        leaked (VMX-076).
        """
        return self._loop

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

        Note:
            The dispatcher does **not** run the loop — foreground work is only
            dispatched once the loop is running. Prefer passing your application's
            already-running loop. When you let this factory create the loop, you
            own its lifecycle: retrieve it via the :attr:`loop` property to drive
            it (``loop.run_forever()``) and to close it (``loop.close()``) when
            done. Failing to close a factory-created loop leaks its selector file
            descriptor (VMX-076).
        """
        resolved_loop: asyncio.AbstractEventLoop = (
            loop if loop is not None else asyncio.new_event_loop()
        )
        fg = AsyncIOScheduler(resolved_loop)
        dispatcher = cls(foreground=fg, background=ThreadPoolScheduler())
        dispatcher._loop = resolved_loop
        return dispatcher

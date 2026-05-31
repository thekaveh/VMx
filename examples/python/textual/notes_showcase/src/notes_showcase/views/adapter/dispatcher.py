"""TextualDispatcher — VMx :class:`Dispatcher` over Textual's asyncio loop.

See scenario §7.1 (Dispatcher) and plan §4.b.

VMx's :class:`vmx.services.dispatcher.Dispatcher` is a structural Protocol
exposing two ``SchedulerBase`` properties: ``foreground`` (UI thread) and
``background``. Textual is asyncio-native, so:

* ``foreground`` → :class:`reactivex.scheduler.eventloop.AsyncIOScheduler`
  bound to the Textual app's event loop. Posting through Rx schedules onto
  the same loop the UI runs on, matching the spec ch. 11 contract that
  foreground work is executed on the UI thread.
* ``background`` → :class:`reactivex.scheduler.ThreadPoolScheduler` (the same
  default ``RxDispatcher.asyncio`` chooses). Off-loop work parks on a worker
  pool and any UI-touching follow-up must be observed via ``foreground``.

The Textual app is captured (rather than re-fetched on every property access)
so the bridge works even if Textual were to swap its event-loop reference
mid-flight; the loop instance owns the scheduler lifetime.
"""

from __future__ import annotations

from reactivex.abc import SchedulerBase
from reactivex.scheduler import ThreadPoolScheduler
from reactivex.scheduler.eventloop import AsyncIOScheduler
from textual.app import App


class TextualDispatcher:
    """Concrete :class:`vmx.services.dispatcher.Dispatcher` for Textual hosts.

    Satisfied structurally — no inheritance required. Construct with the
    running :class:`textual.app.App` after it has acquired an event loop
    (typically inside ``App.on_mount``); call
    ``self._dispatcher = TextualDispatcher(self)``.
    """

    def __init__(self, app: App[object]) -> None:
        self._app = app
        loop = app._loop  # noqa: SLF001 — Textual exposes the loop only privately.
        if loop is None:
            raise RuntimeError(
                "TextualDispatcher requires a running App event loop; "
                "construct it from within App.on_mount or later."
            )
        self._foreground: SchedulerBase = AsyncIOScheduler(loop)
        self._background: SchedulerBase = ThreadPoolScheduler()

    @property
    def foreground(self) -> SchedulerBase:
        """Scheduler for UI-thread (foreground) work — see spec ch. 11."""
        return self._foreground

    @property
    def background(self) -> SchedulerBase:
        """Scheduler for background work — see spec ch. 11."""
        return self._background

"""DelayedTask — at most one delayed action on an injected scheduler.

See spec/11-threading.md §6.3 and ADR-0219.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from reactivex.abc import DisposableBase, SchedulerBase

_logger = logging.getLogger(__name__)


class DelayedTask:
    """Hold at most one pending action on an injected ``SchedulerBase``.

    ``schedule`` replaces the pending action and restarts the delay.
    ``cancel`` stops it, ``is_pending`` reports it, and ``dispose`` cancels
    it and makes later calls inert. The action runs where the scheduler runs
    it, never through a ``Dispatcher`` (spec/11 §6.2). A failing action is
    logged and does not reach the scheduler (spec/03 §3.6).

    The helper is safe to call from any thread. After ``schedule``,
    ``cancel`` or ``dispose`` returns, the replaced or cancelled action
    never starts. Disposal never disposes the scheduler.
    """

    def __init__(self, scheduler: SchedulerBase) -> None:
        self._scheduler = scheduler
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = False
        self._disposed = False
        self._handle: DisposableBase | None = None

    @property
    def is_pending(self) -> bool:
        """``True`` from ``schedule`` until the action starts, ``cancel`` or ``dispose``."""
        with self._lock:
            return self._pending

    def schedule(self, delay: float | timedelta, action: Callable[[], None]) -> None:
        """Replace any pending action with ``action`` after ``delay`` seconds.

        A zero or negative delay runs the action at the scheduler's next
        opportunity. After ``dispose`` this call has no effect. When the
        scheduler raises, the error propagates and nothing stays pending.
        """
        with self._lock:
            if self._disposed:
                return
            previous = self._handle
            self._handle = None
            self._generation += 1
            generation = self._generation
            self._pending = True
        if previous is not None:
            previous.dispose()

        def run(_scheduler: SchedulerBase, _state: Any = None) -> None:
            self._run(generation, action)

        # The scheduler is called without the lock: an inline scheduler may
        # run ``run`` before ``schedule_relative`` returns.
        try:
            handle = self._scheduler.schedule_relative(_clamp(delay), run)
        except BaseException:
            # A scheduler that refuses the action leaves nothing pending.
            with self._lock:
                if self._generation == generation:
                    self._pending = False
            raise
        with self._lock:
            keep = self._generation == generation and self._pending and not self._disposed
            if keep:
                self._handle = handle
        if not keep:
            handle.dispose()

    def cancel(self) -> None:
        """Cancel the pending action, if any."""
        with self._lock:
            if not self._pending:
                return
            handle = self._take_pending()
        if handle is not None:
            handle.dispose()

    def dispose(self) -> None:
        """Cancel the pending action; later calls have no effect."""
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            handle = self._take_pending()
        if handle is not None:
            handle.dispose()

    def _take_pending(self) -> DisposableBase | None:
        # Caller holds the lock.
        self._generation += 1
        self._pending = False
        handle, self._handle = self._handle, None
        return handle

    def _run(self, generation: int, action: Callable[[], None]) -> None:
        with self._lock:
            if self._generation != generation or not self._pending or self._disposed:
                return
            self._pending = False
            self._handle = None
        try:
            action()
        except Exception:
            _logger.exception("DelayedTask action raised; the failure is logged per spec/03 §3.6")


def _clamp(delay: float | timedelta) -> float | timedelta:
    if isinstance(delay, timedelta):
        return delay if delay > timedelta(0) else timedelta(0)
    return delay if delay > 0 else 0.0

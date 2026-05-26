"""NullDispatcher — null-object variant of IDispatcher.

See spec/11-threading.md §"Null variant" and ADR-0017.
"""

from __future__ import annotations

from reactivex.abc import SchedulerBase
from reactivex.scheduler import ImmediateScheduler


class NullDispatcher:
    """Stateless dispatcher whose schedulers are the immediate scheduler.

    Scheduled work runs synchronously on the calling thread. Useful for
    tests, console hosts, or any code path that doesn't need real dispatch.
    """

    def __init__(self) -> None:
        self._scheduler: SchedulerBase = ImmediateScheduler()

    @property
    def foreground(self) -> SchedulerBase:
        return self._scheduler

    @property
    def background(self) -> SchedulerBase:
        return self._scheduler


NULL_DISPATCHER: NullDispatcher = NullDispatcher()
"""Shared singleton instance."""

"""IDispatcher-equivalent backed by deterministic Rx test schedulers."""

from __future__ import annotations

from reactivex.abc import SchedulerBase
from reactivex.testing import TestScheduler


class TestDispatcher:
    """Dispatcher with TestScheduler foreground + background for deterministic time.

    Satisfies the ``Dispatcher`` Protocol structurally via ``.foreground`` /
    ``.background`` properties; does not inherit.
    """

    __test__ = False  # tell pytest this is not a test class

    def __init__(self) -> None:
        self.foreground_scheduler: TestScheduler = TestScheduler()
        self.background_scheduler: TestScheduler = TestScheduler()

    @property
    def foreground(self) -> SchedulerBase:
        return self.foreground_scheduler

    @property
    def background(self) -> SchedulerBase:
        return self.background_scheduler

    def advance_all(self, ticks: int = 1) -> None:
        self.foreground_scheduler.advance_by(ticks)
        self.background_scheduler.advance_by(ticks)

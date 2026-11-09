"""Unit tests for ``DelayedTask`` beyond the DLY catalog (spec/11 §6.3, ADR-0219)."""

from __future__ import annotations

import threading
from datetime import timedelta

from reactivex.scheduler import ImmediateScheduler, TimeoutScheduler
from reactivex.testing import TestScheduler

from vmx.services import DelayedTask


def test_timedelta_delay_is_accepted() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    runs: list[str] = []

    task.schedule(timedelta(seconds=2), lambda: runs.append("ran"))
    scheduler.advance_by(1)
    assert runs == []
    scheduler.advance_by(1)
    assert runs == ["ran"]


def test_negative_delay_runs_at_the_next_opportunity_not_inside_schedule() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    runs: list[str] = []

    task.schedule(-5, lambda: runs.append("float"))
    assert runs == []
    assert task.is_pending is True
    scheduler.advance_by(0.001)
    assert runs == ["float"]

    task.schedule(timedelta(seconds=-5), lambda: runs.append("timedelta"))
    assert runs == ["float"]
    scheduler.advance_by(0.001)
    assert runs == ["float", "timedelta"]
    assert task.is_pending is False


def test_inline_scheduler_runs_the_action_once_and_leaves_nothing_pending() -> None:
    task = DelayedTask(ImmediateScheduler())
    runs: list[bool] = []

    task.schedule(0, lambda: runs.append(task.is_pending))

    assert runs == [False]
    assert task.is_pending is False


def test_real_time_polling_reschedules_from_inside_the_action() -> None:
    task = DelayedTask(TimeoutScheduler())
    done = threading.Event()
    runs: list[int] = []

    def poll() -> None:
        runs.append(1)
        if len(runs) < 3:
            task.schedule(0.01, poll)
        else:
            done.set()

    task.schedule(0.01, poll)
    try:
        assert done.wait(5.0), "the polling loop did not finish"
        assert len(runs) == 3
        assert task.is_pending is False
    finally:
        task.dispose()


def test_cancel_from_another_thread_prevents_a_real_time_action() -> None:
    task = DelayedTask(TimeoutScheduler())
    ran = threading.Event()

    task.schedule(0.05, ran.set)
    canceller = threading.Thread(target=task.cancel)
    canceller.start()
    canceller.join()

    assert task.is_pending is False
    assert not ran.wait(0.2)

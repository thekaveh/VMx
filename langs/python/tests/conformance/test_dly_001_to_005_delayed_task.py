"""DLY-001..DLY-005 — ``DelayedTask`` over a virtual-time scheduler.

Spec: chapter 11 §6.3, chapter 12 §33, ADR-0219.
``reactivex.testing.TestScheduler`` measures time in seconds.
"""

from __future__ import annotations

import logging

import pytest
from reactivex.testing import TestScheduler

from vmx import DelayedTask


@pytest.mark.conformance("DLY-001")
def test_dly_001_scheduled_action_runs_once_at_its_due_time() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    pending_seen_by_action: list[bool] = []

    task.schedule(10, lambda: pending_seen_by_action.append(task.is_pending))
    assert task.is_pending is True

    scheduler.advance_by(9)
    assert pending_seen_by_action == []
    assert task.is_pending is True

    scheduler.advance_by(1)
    assert pending_seen_by_action == [False]
    assert task.is_pending is False

    scheduler.advance_by(10)
    assert pending_seen_by_action == [False]


@pytest.mark.conformance("DLY-001")
def test_dly_001_action_that_reschedules_itself_polls() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    run_times: list[float] = []

    def poll() -> None:
        run_times.append(scheduler.clock)
        if len(run_times) < 3:
            task.schedule(5, poll)

    task.schedule(5, poll)
    scheduler.advance_by(30)

    assert run_times == [5, 10, 15]
    assert task.is_pending is False


@pytest.mark.conformance("DLY-002")
def test_dly_002_second_schedule_replaces_pending_action_and_restarts_delay() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    runs: list[str] = []

    task.schedule(10, lambda: runs.append("A"))
    scheduler.advance_by(6)
    task.schedule(10, lambda: runs.append("B"))
    scheduler.advance_by(9)  # t = 15
    assert runs == []
    assert task.is_pending is True

    scheduler.advance_by(1)  # t = 16
    assert runs == ["B"]

    scheduler.advance_by(10)  # t = 26
    assert runs == ["B"]


@pytest.mark.conformance("DLY-003")
def test_dly_003_cancel_prevents_the_pending_action() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    runs: list[str] = []

    task.cancel()
    assert task.is_pending is False

    task.schedule(10, lambda: runs.append("first"))
    scheduler.advance_by(4)
    task.cancel()
    assert task.is_pending is False
    scheduler.advance_by(10)  # t = 14
    assert runs == []

    task.schedule(10, lambda: runs.append("second"))
    scheduler.advance_by(9)  # t = 23
    assert runs == []
    scheduler.advance_by(1)  # t = 24
    assert runs == ["second"]


@pytest.mark.conformance("DLY-004")
def test_dly_004_dispose_cancels_and_later_calls_are_inert() -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)
    runs: list[str] = []

    task.schedule(10, lambda: runs.append("pending"))
    task.dispose()
    task.dispose()
    assert task.is_pending is False
    scheduler.advance_by(20)
    assert runs == []

    task.schedule(1, lambda: runs.append("after dispose"))
    assert task.is_pending is False
    task.cancel()
    assert task.is_pending is False
    scheduler.advance_by(5)
    assert runs == []

    other: list[str] = []
    scheduler.schedule_relative(1, lambda _s, _st: other.append("unrelated"))
    scheduler.advance_by(1)
    assert other == ["unrelated"]


@pytest.mark.conformance("DLY-005")
def test_dly_005_failing_action_is_isolated_and_task_stays_usable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scheduler = TestScheduler()
    task = DelayedTask(scheduler)

    def fail() -> None:
        raise RuntimeError("boom")

    task.schedule(10, fail)
    with caplog.at_level(logging.ERROR, logger="vmx.services.delayed_task"):
        scheduler.advance_by(11)  # must not raise

    records = [r for r in caplog.records if r.name == "vmx.services.delayed_task"]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], RuntimeError)
    assert task.is_pending is False

    runs: list[str] = []
    task.schedule(10, lambda: runs.append("second"))
    scheduler.advance_by(11)
    assert runs == ["second"]

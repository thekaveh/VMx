"""Scheduler selection for the notification timers and the search debounce (#1642)."""

from __future__ import annotations

import asyncio

from reactivex.scheduler import ImmediateScheduler, TimeoutScheduler
from reactivex.scheduler.eventloop import AsyncIOThreadSafeScheduler
from vmx import RxDispatcher

from notes_showcase.viewmodels.notes_view_vm import (
    default_search_scheduler,
    default_timer_scheduler,
)


def test_a_timer_capable_foreground_is_used_as_is() -> None:
    loop = asyncio.new_event_loop()
    try:
        dispatcher = RxDispatcher.asyncio(loop)
        assert default_timer_scheduler(dispatcher) is dispatcher.foreground
    finally:
        loop.close()


async def test_a_running_loop_gets_a_scheduler_bound_to_that_loop() -> None:
    scheduler = default_timer_scheduler(RxDispatcher.immediate())

    assert isinstance(scheduler, AsyncIOThreadSafeScheduler)
    assert scheduler._loop is asyncio.get_running_loop()  # type: ignore[attr-defined]


def test_without_a_loop_the_threaded_timer_is_used() -> None:
    assert isinstance(default_timer_scheduler(RxDispatcher.immediate()), TimeoutScheduler)


def test_search_without_debounce_uses_the_immediate_scheduler() -> None:
    assert isinstance(
        default_search_scheduler(RxDispatcher.immediate(), 0.0),
        ImmediateScheduler,
    )


def test_search_with_debounce_uses_the_timer_selection() -> None:
    assert isinstance(
        default_search_scheduler(RxDispatcher.immediate(), 0.15),
        TimeoutScheduler,
    )

"""Unit tests for AsyncRelayCommand scheduling outside an event loop."""

from __future__ import annotations

import asyncio
from threading import Event, Thread

from vmx.commands import AsyncRelayCommand


def test_execute_without_running_loop_returns_before_async_work_finishes() -> None:
    started = Event()
    release = Event()
    finished = Event()
    returned = Event()

    async def task() -> None:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0)
        finished.set()

    command = AsyncRelayCommand.builder().task(task).build()
    caller = Thread(target=lambda: (command.execute(), returned.set()), daemon=True)
    caller.start()

    try:
        assert started.wait(1), "the async command starts on a background event loop"
        returned_before_release = returned.wait(0.1)
    finally:
        release.set()
        caller.join(timeout=1)

    assert returned_before_release, "fire-and-forget execute must not run the coroutine inline"
    assert finished.wait(1)
    command.dispose()

"""Unit tests for AsyncRelayCommand scheduling outside an event loop."""

from __future__ import annotations

import asyncio
from threading import Barrier, Event, Lock, Thread

import pytest
from reactivex.subject import Subject

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


def test_execute_async_admission_is_atomic_across_threads() -> None:
    predicate_barrier = Barrier(2)
    release = Event()
    invocation_lock = Lock()
    invocations = 0

    def predicate() -> bool:
        predicate_barrier.wait(timeout=1)
        return True

    async def task() -> None:
        nonlocal invocations
        with invocation_lock:
            invocations += 1
        while not release.is_set():
            await asyncio.sleep(0)

    command = AsyncRelayCommand.builder().predicate(predicate).task(task).build()
    callers = [Thread(target=lambda: asyncio.run(command.execute_async())) for _ in range(2)]
    for caller in callers:
        caller.start()
    try:
        assert all(caller.is_alive() for caller in callers)
    finally:
        release.set()
        for caller in callers:
            caller.join(timeout=1)

    assert invocations == 1
    assert all(not caller.is_alive() for caller in callers)
    command.dispose()


def test_dispose_attempts_all_terminal_steps_and_preserves_first_failure() -> None:
    trigger: Subject[None] = Subject()
    command = AsyncRelayCommand.builder().triggers(trigger).build()

    def fail_first() -> None:
        raise RuntimeError("first terminal failure")

    def fail_later() -> None:
        raise ValueError("later terminal failure")

    command.can_execute_changed.subscribe(on_completed=fail_first)
    command.errors.subscribe(on_completed=fail_later)

    with pytest.raises(RuntimeError, match="first terminal failure"):
        command.dispose()

    assert trigger.observers == []
    assert command._can_execute_changed_subject.is_disposed is True
    assert command._errors.is_disposed is True
    command.dispose()

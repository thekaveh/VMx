"""Unit tests for AsyncRelayCommand scheduling outside an event loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from threading import Barrier, Event, Lock, Thread

import pytest
from reactivex.subject import Subject

from vmx.commands import AsyncRelayCommand


@pytest.mark.asyncio
async def test_start_observer_failure_restores_idle_without_running_task() -> None:
    calls = 0

    async def task() -> None:
        nonlocal calls
        calls += 1

    command = AsyncRelayCommand.builder().task(task).build()
    command.can_execute_changed.subscribe(
        lambda _: (_ for _ in ()).throw(RuntimeError("start observer"))
    )

    with pytest.raises(RuntimeError, match="start observer"):
        await command.execute_async()

    assert calls == 0
    assert command.is_executing is False
    assert command.can_execute() is True


@pytest.mark.asyncio
async def test_body_failure_precedes_completion_observer_failure() -> None:
    notifications = 0

    async def task() -> None:
        raise ValueError("body failure")

    def observe(_: None) -> None:
        nonlocal notifications
        notifications += 1
        if notifications == 2:
            raise RuntimeError("completion observer")

    command = AsyncRelayCommand.builder().task(task).build()
    command.can_execute_changed.subscribe(observe)

    with pytest.raises(ValueError, match="body failure"):
        await command.execute_async()

    assert command.is_executing is False
    assert command.can_execute() is True


@pytest.mark.asyncio
async def test_fire_and_forget_routes_body_failure_before_completion_observer() -> None:
    notifications = 0
    observed = asyncio.Event()
    errors: list[BaseException] = []

    async def task() -> None:
        raise ValueError("body failure")

    def observe(_: None) -> None:
        nonlocal notifications
        notifications += 1
        if notifications == 2:
            raise RuntimeError("completion observer")

    def on_error(error: BaseException) -> None:
        errors.append(error)
        observed.set()

    command = AsyncRelayCommand.builder().task(task).build()
    command.can_execute_changed.subscribe(observe)
    command.errors.subscribe(on_error)

    command.execute()
    await asyncio.wait_for(observed.wait(), timeout=1)

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "body failure"


@pytest.mark.asyncio
async def test_external_cancellation_remains_throwing_when_command_cancel_follows() -> None:
    started = asyncio.Event()

    async def task() -> None:
        started.set()
        await asyncio.sleep(3600)

    command = AsyncRelayCommand.builder().task(task).build()
    run = asyncio.create_task(command.execute_async())
    await started.wait()

    run.cancel()
    command.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run


@pytest.mark.asyncio
async def test_command_cancellation_remains_nonthrowing_when_external_cancel_follows() -> None:
    started = asyncio.Event()

    async def task() -> None:
        started.set()
        await asyncio.sleep(3600)

    command = AsyncRelayCommand.builder().task(task).build()
    run = asyncio.create_task(command.execute_async())
    await started.wait()

    command.cancel()
    run.cancel()

    await run


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
        predicate_barrier.wait(timeout=10)
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
        # The barrier guarantees both callers raced admission together; exactly
        # one must be rejected and return promptly while the winner holds the
        # in-flight flag (its task spins until release). Observe that rejection
        # BEFORE releasing: releasing first lets the winner finish, after which
        # a descheduled straggler is legally re-admitted as a sequential second
        # execution (re-executable command), which is not an atomicity failure.
        deadline = time.monotonic() + 10
        while all(caller.is_alive() for caller in callers) and time.monotonic() < deadline:
            time.sleep(0.01)
        rejected = sum(1 for caller in callers if not caller.is_alive())
        assert rejected == 1, "exactly one concurrent caller must be rejected mid-flight"
    finally:
        release.set()
        for caller in callers:
            caller.join(timeout=5)

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


@pytest.mark.parametrize(
    ("subject_name", "emit", "value"),
    [
        (
            "_can_execute_changed_subject",
            lambda command, _: command.raise_can_execute_changed(),
            None,
        ),
        ("_errors", lambda command, error: command._emit_error(error), RuntimeError("boom")),
    ],
)
def test_concurrent_dispose_returns_but_defers_terminal_for_active_subject_emission(
    subject_name: str,
    emit: Callable[[AsyncRelayCommand, object], None],
    value: object,
) -> None:
    emission_started = Event()
    release_emission = Event()
    dispose_started = Event()
    dispose_finished = Event()

    class BlockingSubject(Subject[object]):
        def on_next(self, item: object) -> None:
            emission_started.set()
            assert release_emission.wait(1)
            super().on_next(item)

    command = AsyncRelayCommand.builder().build()
    subject = BlockingSubject()
    observed: list[object] = []
    completions: list[None] = []
    subject.subscribe(observed.append, on_completed=lambda: completions.append(None))
    setattr(command, subject_name, subject)
    emission_failures: list[BaseException] = []

    def publish() -> None:
        try:
            emit(command, value)
        except BaseException as error:
            emission_failures.append(error)

    emitter = Thread(target=publish, daemon=True)
    emitter.start()
    assert emission_started.wait(1)

    def dispose() -> None:
        dispose_started.set()
        command.dispose()
        dispose_finished.set()

    disposer = Thread(target=dispose, daemon=True)
    disposer.start()
    assert dispose_started.wait(1)
    disposed_during_emission = dispose_finished.wait(0.1)
    assert completions == []
    release_emission.set()

    emitter.join(timeout=1)
    disposer.join(timeout=1)

    assert not emitter.is_alive()
    assert not disposer.is_alive()
    assert disposed_during_emission
    assert emission_failures == []
    assert observed == [value]
    assert completions == [None]


@pytest.mark.parametrize(
    ("channel", "emit", "value"),
    [
        (
            "can_execute_changed",
            lambda command, _: command.raise_can_execute_changed(),
            None,
        ),
        ("errors", lambda command, error: command._emit_error(error), RuntimeError("boom")),
    ],
)
def test_observer_can_wait_for_foreign_disposer_without_deadlock(
    channel: str,
    emit: Callable[[AsyncRelayCommand, object], None],
    value: object,
) -> None:
    command = AsyncRelayCommand.builder().build()
    observable = getattr(command, channel)
    dispose_finished = Event()
    disposer_threads: list[Thread] = []
    events: list[tuple[str, object]] = []

    def observe(item: object) -> None:
        events.append(("next", item))
        disposer = Thread(
            target=lambda: (command.dispose(), dispose_finished.set()),
            daemon=True,
        )
        disposer_threads.append(disposer)
        disposer.start()
        assert dispose_finished.wait(1), "dispose must not wait on observer-held progress"

    observable.subscribe(
        observe,
        on_completed=lambda: events.append(("complete", None)),
    )

    emit(command, value)
    for disposer in disposer_threads:
        disposer.join(timeout=1)

    assert all(not disposer.is_alive() for disposer in disposer_threads)
    assert events == [("next", value), ("complete", None)]


@pytest.mark.parametrize(
    ("source_channel", "source_emit", "source_value", "target_emit", "target_value"),
    [
        (
            "can_execute_changed",
            lambda command, _: command.raise_can_execute_changed(),
            None,
            lambda command, error: command._emit_error(error),
            RuntimeError("boom"),
        ),
        (
            "errors",
            lambda command, error: command._emit_error(error),
            RuntimeError("boom"),
            lambda command, _: command.raise_can_execute_changed(),
            None,
        ),
    ],
)
def test_observer_can_wait_for_other_channel_emission_without_deadlock(
    source_channel: str,
    source_emit: Callable[[AsyncRelayCommand, object], None],
    source_value: object,
    target_emit: Callable[[AsyncRelayCommand, object], None],
    target_value: object,
) -> None:
    command = AsyncRelayCommand.builder().build()
    target_finished = Event()
    target_threads: list[Thread] = []

    def observe(_: object) -> None:
        target = Thread(
            target=lambda: (target_emit(command, target_value), target_finished.set()),
            daemon=True,
        )
        target_threads.append(target)
        target.start()
        assert target_finished.wait(1), "independent channels must not share delivery progress"

    getattr(command, source_channel).subscribe(observe)

    source_emit(command, source_value)
    for target in target_threads:
        target.join(timeout=1)

    assert all(not target.is_alive() for target in target_threads)


@pytest.mark.parametrize(
    ("channel", "emit", "value"),
    [
        (
            "can_execute_changed",
            lambda command, _: command.raise_can_execute_changed(),
            None,
        ),
        ("errors", lambda command, error: command._emit_error(error), RuntimeError("boom")),
    ],
)
def test_reentrant_dispose_defers_terminal_until_active_delivery_finishes(
    channel: str,
    emit: Callable[[AsyncRelayCommand, object], None],
    value: object,
) -> None:
    command = AsyncRelayCommand.builder().build()
    observable = getattr(command, channel)
    events: list[tuple[str, object]] = []

    def first(item: object) -> None:
        events.append(("first-next", item))
        command.dispose()

    observable.subscribe(first, on_completed=lambda: events.append(("first-complete", None)))
    observable.subscribe(
        lambda item: events.append(("second-next", item)),
        on_completed=lambda: events.append(("second-complete", None)),
    )

    emit(command, value)

    assert events == [
        ("first-next", value),
        ("second-next", value),
        ("first-complete", None),
        ("second-complete", None),
    ]
    assert command._can_execute_changed_subject.is_disposed is True
    assert command._errors.is_disposed is True
    command.dispose()

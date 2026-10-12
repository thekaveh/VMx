"""Unit tests for ConfirmationDecoratorCommand — error channel (VMX-009).

The fire-and-forget ``execute()`` runs the confirm gate asynchronously, so it
cannot propagate the way the base ``RelayCommand``'s task does. Previously BOTH
a rejecting confirm delegate AND a throwing inner command were swallowed; they
must now be surfaced on the ``errors`` channel. Await ``execute_async()`` to
observe them inline.

An inner command is asynchronous by shape: any inner offering an awaitable
``execute_async`` is awaited by ``execute_async()`` and started through its own
``execute()`` by the fire-and-forget path (spec §8.3.2, ADR-0145).
"""

from __future__ import annotations

import asyncio
from threading import Event, Thread

import pytest
from reactivex import Observable
from reactivex.subject import Subject

from vmx.commands import ConfirmationDecoratorCommand, RelayCommand


async def test_execute_surfaces_rejecting_confirm_on_error_channel() -> None:
    boom = RuntimeError("nope")

    async def confirm() -> bool:
        raise boom

    inner = RelayCommand.builder().task(lambda: None).build()
    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)
    errors: list[BaseException] = []
    cmd.errors.subscribe(errors.append)

    cmd.execute()  # fire-and-forget
    for _ in range(5):
        await asyncio.sleep(0)
        if errors:
            break

    assert errors == [boom], "rejecting confirm surfaced on errors, not swallowed"


async def test_execute_surfaces_throwing_inner_on_error_channel() -> None:
    boom = RuntimeError("inner boom")

    def _raise() -> None:
        raise boom

    inner = RelayCommand.builder().task(_raise).build()

    async def confirm() -> bool:
        return True

    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)
    errors: list[BaseException] = []
    cmd.errors.subscribe(errors.append)

    cmd.execute()  # fire-and-forget
    for _ in range(5):
        await asyncio.sleep(0)
        if errors:
            break

    assert errors == [boom], "throwing inner command surfaced on errors, not swallowed"


def test_errors_completes_on_dispose() -> None:
    inner = RelayCommand.builder().task(lambda: None).build()

    async def confirm() -> bool:
        return True

    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)
    completed: list[bool] = []
    cmd.errors.subscribe(on_completed=lambda: completed.append(True))

    cmd.dispose()
    assert len(completed) == 1, "errors observable completes on dispose"


def test_dispose_disposes_error_channel_when_completion_observer_raises() -> None:
    inner = RelayCommand.builder().build()

    async def confirm() -> bool:
        return True

    cmd = ConfirmationDecoratorCommand(inner, confirm=confirm)

    def fail() -> None:
        raise RuntimeError("terminal observer")

    cmd.errors.subscribe(on_completed=fail)

    with pytest.raises(RuntimeError, match="terminal observer"):
        cmd.dispose()

    assert cmd._errors.is_disposed is True
    cmd.dispose()


def test_execute_without_running_loop_returns_while_confirmation_is_pending() -> None:
    started = Event()
    release = Event()
    invoked = Event()
    returned = Event()

    async def confirm() -> bool:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0)
        return True

    inner = RelayCommand.builder().task(invoked.set).build()
    command = ConfirmationDecoratorCommand(inner, confirm=confirm)
    caller = Thread(target=lambda: (command.execute(), returned.set()), daemon=True)
    caller.start()

    try:
        assert started.wait(1), "the confirmation starts on a background event loop"
        returned_before_release = returned.wait(0.1)
    finally:
        release.set()
        caller.join(timeout=1)

    assert returned_before_release, "fire-and-forget execute must not await confirmation inline"
    assert invoked.wait(1)
    command.dispose()


class _StructuralAsyncCommand:
    """An async inner by shape alone: a coroutine ``execute_async`` (spec §8.3.2)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.called = asyncio.Event()
        self.release: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._changed: Subject[None] = Subject()

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._changed

    def can_execute(self, parameter: object = None) -> bool:
        return True

    def execute(self, parameter: object = None) -> None:
        self.calls.append(f"execute:{parameter}")
        self.called.set()

    async def execute_async(self, parameter: object = None) -> None:
        self.calls.append(f"execute_async:{parameter}")
        self.called.set()
        await self.release


async def _confirm_yes() -> bool:
    return True


async def test_execute_async_awaits_any_inner_offering_an_awaitable_execute_async() -> None:
    inner = _StructuralAsyncCommand()
    command = ConfirmationDecoratorCommand(inner, confirm=_confirm_yes)

    awaiter = asyncio.ensure_future(command.execute_async("p"))
    await asyncio.wait_for(inner.called.wait(), 1)

    assert inner.calls == ["execute_async:p"]
    assert not awaiter.done(), "the awaited call waits for the structural async inner"
    inner.release.set_result(None)
    await asyncio.wait_for(awaiter, 1)
    assert inner.calls == ["execute_async:p"]


async def test_execute_starts_an_async_inner_through_its_own_execute() -> None:
    inner = _StructuralAsyncCommand()
    command = ConfirmationDecoratorCommand(inner, confirm=_confirm_yes)

    command.execute("p")
    await asyncio.wait_for(inner.called.wait(), 1)

    assert inner.calls == ["execute:p"], "fire-and-forget uses the inner's own execute()"

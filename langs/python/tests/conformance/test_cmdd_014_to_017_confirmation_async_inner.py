"""Conformance tests: CMDD-014..017 — confirmation over an asynchronous inner command.

Per spec/04-commands.md §8.3.2 (with §8.3.1, §8.4, §10) and ADR-0145. Every
wait is gated on an asyncio future or event; ``_wait`` only bounds a regression
that would otherwise hang the suite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest
from reactivex import Observable
from reactivex.subject import Subject

from tests.liveness import HANG_GUARD
from vmx.commands import AsyncRelayCommand, ConfirmationDecoratorCommand

T = TypeVar("T")


async def _wait(awaitable: Awaitable[T]) -> T:
    return await asyncio.wait_for(awaitable, HANG_GUARD)


async def _drain_other_tasks() -> None:
    """Await every task this test started, including fire-and-forget ones."""
    current = asyncio.current_task()
    others = [task for task in asyncio.all_tasks() if task is not current]
    await _wait(asyncio.gather(*others, return_exceptions=True))


class _Gate:
    """An async command body that blocks until the test releases or fails it."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._outcome: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.runs = 0
        self.cancelled = False

    async def body(self) -> None:
        self.runs += 1
        self.started.set()
        try:
            await self._outcome
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def release(self) -> None:
        self._outcome.set_result(None)

    def fail(self, error: BaseException) -> None:
        self._outcome.set_exception(error)


class _Confirmation:
    """A ``confirm`` delegate that stays pending until the test decides."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.decision: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        self.started.set()
        return await self.decision


class _SpyAsyncCommand(AsyncRelayCommand):
    """A real ``AsyncRelayCommand`` that counts calls to each entry point.

    The base fire-and-forget ``execute`` does not call ``execute_async``, so an
    ``execute`` call counts only under ``execute_calls``.
    """

    def __init__(self, task: Callable[[], Awaitable[None]]) -> None:
        super().__init__(task, None, [])
        self.execute_calls = 0
        self.execute_async_calls = 0

    def execute(self, parameter: object = None) -> None:
        self.execute_calls += 1
        super().execute(parameter)

    async def execute_async(self, parameter: object = None) -> None:
        self.execute_async_calls += 1
        await super().execute_async(parameter)


class _SpySyncCommand:
    """A synchronous command: it offers ``execute`` and no awaitable entry point."""

    def __init__(self, log: list[str]) -> None:
        self._log = log
        self._changed: Subject[None] = Subject()

    @property
    def can_execute_changed(self) -> Observable[None]:
        return self._changed

    def can_execute(self, parameter: object = None) -> bool:
        return True

    def execute(self, parameter: object = None) -> None:
        self._log.append(f"execute:{parameter}")


async def _yes() -> bool:
    return True


def _record(
    target: list[BaseException], signal: asyncio.Event | None = None
) -> Callable[..., None]:
    def _on_next(error: BaseException) -> None:
        target.append(error)
        if signal is not None:
            signal.set()

    return _on_next


# ---------------------------------------------------------------------------
# CMDD-014 — Awaited confirmation completes when an async inner completes
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-014")
async def test_CMDD_014_awaited_confirmation_completes_when_the_async_inner_completes() -> None:
    gate = _Gate()
    inner = _SpyAsyncCommand(gate.body)
    confirmation = _Confirmation()
    decorator = ConfirmationDecoratorCommand(inner, confirmation)

    awaiter = asyncio.ensure_future(decorator.execute_async())
    await _wait(confirmation.started.wait())
    assert inner.execute_async_calls == 0, "nothing runs while the confirmation is pending"

    confirmation.decision.set_result(True)
    await _wait(gate.started.wait())
    assert inner.is_executing
    assert not awaiter.done(), "the awaiter must not complete while the inner body is blocked"

    gate.release()
    await _wait(awaiter)

    assert awaiter.result() is None
    assert not inner.is_executing
    assert gate.runs == 1
    assert inner.execute_async_calls == 1, "the awaitable entry point ran exactly once"
    assert inner.execute_calls == 0, "the synchronous execute() never ran for this call"


@pytest.mark.conformance("CMDD-014")
async def test_CMDD_014_false_confirmation_completes_without_invoking_the_inner() -> None:
    gate = _Gate()
    inner = _SpyAsyncCommand(gate.body)
    confirmation = _Confirmation()
    decorator = ConfirmationDecoratorCommand(inner, confirmation)

    awaiter = asyncio.ensure_future(decorator.execute_async())
    await _wait(confirmation.started.wait())
    confirmation.decision.set_result(False)
    await _wait(awaiter)

    assert awaiter.result() is None
    assert confirmation.calls == 1
    assert gate.runs == 0
    assert inner.execute_async_calls == 0
    assert inner.execute_calls == 0
    assert not inner.is_executing


@pytest.mark.conformance("CMDD-014")
async def test_CMDD_014_sync_inner_runs_execute_once_before_the_awaiter_completes() -> None:
    log: list[str] = []
    inner = _SpySyncCommand(log)

    async def _confirm() -> bool:
        log.append("confirm")
        return True

    decorator = ConfirmationDecoratorCommand(inner, _confirm)

    await _wait(decorator.execute_async("note-1"))
    log.append("awaited")

    assert log == ["confirm", "execute:note-1", "awaited"]


# ---------------------------------------------------------------------------
# CMDD-015 — Failures reach exactly one channel
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-015")
async def test_CMDD_015_awaited_inner_failure_reaches_only_the_awaiter() -> None:
    boom = RuntimeError("inner failed")
    gate = _Gate()
    inner = AsyncRelayCommand.builder().task(gate.body).build()
    decorator = ConfirmationDecoratorCommand(inner, _yes)
    decorator_errors: list[BaseException] = []
    inner_errors: list[BaseException] = []
    decorator.errors.subscribe(_record(decorator_errors))
    inner.errors.subscribe(_record(inner_errors))

    awaiter = asyncio.ensure_future(decorator.execute_async())
    await _wait(gate.started.wait())
    assert not awaiter.done()

    gate.fail(boom)
    with pytest.raises(RuntimeError) as raised:
        await _wait(awaiter)
    await _drain_other_tasks()

    assert raised.value is boom, "the failure reaches the awaiter unchanged"
    assert decorator_errors == []
    assert inner_errors == []
    assert not inner.is_executing


@pytest.mark.conformance("CMDD-015")
async def test_CMDD_015_fire_and_forget_inner_failure_reaches_only_the_inner_errors() -> None:
    boom = RuntimeError("inner failed")
    gate = _Gate()
    inner = AsyncRelayCommand.builder().task(gate.body).build()
    decorator = ConfirmationDecoratorCommand(inner, _yes)
    decorator_errors: list[BaseException] = []
    inner_errors: list[BaseException] = []
    inner_failed = asyncio.Event()
    decorator.errors.subscribe(_record(decorator_errors))
    inner.errors.subscribe(_record(inner_errors, inner_failed))

    before = asyncio.all_tasks()
    decorator.execute()
    (decorator_task,) = asyncio.all_tasks() - before
    await _wait(gate.started.wait())
    # The decorator's own flow ended once it started the inner through the
    # inner's execute(); it does not watch the inner operation.
    assert decorator_task.done()
    assert inner.is_executing

    gate.fail(boom)
    await _wait(inner_failed.wait())
    await _drain_other_tasks()

    assert inner_errors == [boom], "the inner's error channel emits the failure exactly once"
    assert decorator_errors == [], "the decorator does not re-emit the inner's failure"


@pytest.mark.conformance("CMDD-015")
async def test_CMDD_015_confirm_failure_reaches_the_decorator_errors_only() -> None:
    confirm_boom = RuntimeError("confirm failed")

    async def _reject() -> bool:
        raise confirm_boom

    gate = _Gate()
    inner = _SpyAsyncCommand(gate.body)
    decorator = ConfirmationDecoratorCommand(inner, _reject)
    decorator_errors: list[BaseException] = []
    inner_errors: list[BaseException] = []
    decorator_failed = asyncio.Event()
    decorator.errors.subscribe(_record(decorator_errors, decorator_failed))
    inner.errors.subscribe(_record(inner_errors))

    decorator.execute()
    await _wait(decorator_failed.wait())
    await _drain_other_tasks()

    assert decorator_errors == [confirm_boom], "the decorator's errors emit it exactly once"
    assert inner_errors == []
    assert gate.runs == 0
    assert inner.execute_calls == 0
    assert inner.execute_async_calls == 0

    # The awaited path propagates the same failure to its caller instead.
    with pytest.raises(RuntimeError) as raised:
        await _wait(decorator.execute_async())
    assert raised.value is confirm_boom
    assert decorator_errors == [confirm_boom]
    assert gate.runs == 0


# ---------------------------------------------------------------------------
# CMDD-016 — The inner keeps its own admission and cancellation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-016")
async def test_CMDD_016_inner_busy_when_confirmation_resolves_drops_the_call() -> None:
    gate = _Gate()
    inner = _SpyAsyncCommand(gate.body)
    confirmation = _Confirmation()
    decorator = ConfirmationDecoratorCommand(inner, confirmation)

    awaiter = asyncio.ensure_future(decorator.execute_async())
    await _wait(confirmation.started.wait())
    # Another caller starts the inner while the confirmation is pending.
    first_run = asyncio.ensure_future(inner.execute_async())
    await _wait(gate.started.wait())
    assert inner.is_executing

    confirmation.decision.set_result(True)
    await _wait(awaiter)

    assert not first_run.done(), "the awaiter completed with the dropped call"
    assert gate.runs == 1, "the busy inner dropped the call: its body ran no second time"
    assert inner.execute_async_calls == 2, "the direct run plus the decorator's dropped call"
    assert inner.execute_calls == 0

    gate.release()
    await _wait(first_run)
    assert gate.runs == 1


@pytest.mark.conformance("CMDD-016")
async def test_CMDD_016_inner_already_executing_at_call_time_runs_no_second_body() -> None:
    gate = _Gate()
    inner = _SpyAsyncCommand(gate.body)
    confirms: list[None] = []

    async def _counting_confirm() -> bool:
        confirms.append(None)
        return True

    decorator = ConfirmationDecoratorCommand(inner, _counting_confirm)

    first_run = asyncio.ensure_future(inner.execute_async())
    await _wait(gate.started.wait())
    assert decorator.can_execute() is False

    await _wait(decorator.execute_async())
    decorator.execute()
    # first_run is still gated, so drain the loop without awaiting it.
    for _ in range(10):
        await asyncio.sleep(0)

    assert confirms == [], "a busy inner disables the decorator, so confirm is not invoked"
    assert not first_run.done()
    assert gate.runs == 1
    gate.release()
    await _wait(first_run)
    assert gate.runs == 1


@pytest.mark.conformance("CMDD-016")
@pytest.mark.parametrize("throw_on_cancel", [False, True], ids=["non-throwing", "throwing"])
async def test_CMDD_016_inner_cancel_outcome_reaches_the_awaiter_unchanged(
    throw_on_cancel: bool,
) -> None:
    gate = _Gate()
    inner = AsyncRelayCommand.builder().task(gate.body).throw_on_cancel(throw_on_cancel).build()
    decorator = ConfirmationDecoratorCommand(inner, _yes)
    decorator_errors: list[BaseException] = []
    inner_errors: list[BaseException] = []
    decorator.errors.subscribe(_record(decorator_errors))
    inner.errors.subscribe(_record(inner_errors))

    awaiter = asyncio.ensure_future(decorator.execute_async())
    await _wait(gate.started.wait())
    assert not awaiter.done()

    inner.cancel()
    # The inner's own rule (spec §10.3): the default completes normally; the
    # opt-in throwing mode surfaces CancelledError to the awaiter.
    if throw_on_cancel:
        with pytest.raises(asyncio.CancelledError):
            await _wait(awaiter)
    else:
        await _wait(awaiter)
        assert awaiter.result() is None
    await _drain_other_tasks()

    assert gate.cancelled
    assert not inner.is_executing
    assert inner.can_execute() is True
    assert decorator_errors == []
    assert inner_errors == []


# ---------------------------------------------------------------------------
# CMDD-017 — Nested wrappers are awaited; disposal does not own the inner
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-017")
async def test_CMDD_017_outer_wrapper_awaits_inner_wrapper_and_its_body() -> None:
    gate = _Gate()
    leaf = _SpyAsyncCommand(gate.body)
    inner_confirmation = _Confirmation()
    outer_confirmation = _Confirmation()
    inner_wrapper = ConfirmationDecoratorCommand(leaf, inner_confirmation)
    outer = ConfirmationDecoratorCommand(inner_wrapper, outer_confirmation)

    awaiter = asyncio.ensure_future(outer.execute_async())
    await _wait(outer_confirmation.started.wait())
    assert inner_confirmation.calls == 0

    outer_confirmation.decision.set_result(True)
    await _wait(inner_confirmation.started.wait())
    assert not awaiter.done(), "the outer awaits the inner wrapper's confirmation"

    inner_confirmation.decision.set_result(True)
    await _wait(gate.started.wait())
    assert not awaiter.done(), "the outer awaits the inner wrapper's inner operation"

    gate.release()
    await _wait(awaiter)

    assert awaiter.result() is None
    assert gate.runs == 1
    assert leaf.execute_async_calls == 1
    assert leaf.execute_calls == 0


@pytest.mark.conformance("CMDD-017")
async def test_CMDD_017_disposal_during_inner_execution_neither_cancels_nor_disposes() -> None:
    gate = _Gate()
    inner = AsyncRelayCommand.builder().task(gate.body).build()
    inner_terminals: list[str] = []
    inner.errors.subscribe(on_completed=lambda: inner_terminals.append("errors"))
    inner.can_execute_changed.subscribe(
        on_completed=lambda: inner_terminals.append("can_execute_changed")
    )
    decorator = ConfirmationDecoratorCommand(inner, _yes)
    decorator_completions: list[None] = []
    decorator.errors.subscribe(on_completed=lambda: decorator_completions.append(None))

    awaiter = asyncio.ensure_future(decorator.execute_async())
    await _wait(gate.started.wait())
    decorator.dispose()

    assert decorator.can_execute() is False
    assert decorator_completions == [None]
    assert inner.is_executing, "disposing the decorator does not cancel the inner"
    assert not awaiter.done()

    gate.release()
    await _wait(awaiter)

    assert awaiter.result() is None, "the awaiter completes when the body is released"
    assert not gate.cancelled
    assert inner_terminals == [], "the inner was not disposed"
    assert inner.can_execute() is True
    await _wait(inner.execute_async())
    assert gate.runs == 2, "the inner stays usable after the decorator's disposal"


@pytest.mark.conformance("CMDD-017")
@pytest.mark.parametrize("path", ["awaited", "fire-and-forget"])
async def test_CMDD_017_disposal_during_pending_confirmation_starts_no_inner_work(
    path: str,
) -> None:
    gate = _Gate()
    inner = _SpyAsyncCommand(gate.body)
    confirmation = _Confirmation()
    decorator = ConfirmationDecoratorCommand(inner, confirmation)
    decorator_errors: list[BaseException] = []
    decorator.errors.subscribe(_record(decorator_errors))

    if path == "awaited":
        awaiter = asyncio.ensure_future(decorator.execute_async())
    else:
        decorator.execute()
    await _wait(confirmation.started.wait())
    decorator.dispose()
    confirmation.decision.set_result(True)
    await _drain_other_tasks()

    if path == "awaited":
        assert awaiter.result() is None
    assert gate.runs == 0
    assert inner.execute_calls == 0
    assert inner.execute_async_calls == 0
    assert not inner.is_executing
    assert decorator_errors == []

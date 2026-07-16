"""ARES-001..011 — AsyncResourceVM conformance (spec chapter 23)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from vmx import (
    NULL_DISPATCHER,
    AsyncResourceRetention,
    AsyncResourceStatus,
    AsyncResourceVM,
    Message,
    MessageHub,
    PropertyChangedMessage,
)


async def _flush() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


def _vm(
    loader: Callable[[], Awaitable[int]],
    *,
    hub: MessageHub[Message] | None = None,
    retention: AsyncResourceRetention = AsyncResourceRetention.DISCARD_PREVIOUS,
    cleanup: Callable[[int], None] | None = None,
) -> AsyncResourceVM[int]:
    return AsyncResourceVM(
        name="resource",
        loader=loader,
        hub=hub or MessageHub(),
        dispatcher=NULL_DISPATCHER,
        retention=retention,
        cleanup_value=cleanup,
    )


@pytest.mark.conformance("ARES-001")
def test_ares_001_initial_state_and_commands() -> None:
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return 1

    vm = _vm(loader)
    changes: list[str] = []
    vm.property_changed.subscribe(changes.append)

    assert vm.state.status is AsyncResourceStatus.IDLE
    assert calls == 0
    assert changes == []
    assert vm.load_command.can_execute()
    assert not vm.reload_command.can_execute()
    assert not vm.cancel_command.can_execute()


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-002")
async def test_ares_002_success_and_ordinary_notification() -> None:
    hub: MessageHub[Message] = MessageHub()
    result: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    vm = _vm(lambda: result, hub=hub)
    local: list[str] = []
    shared: list[str] = []
    vm.property_changed.subscribe(local.append)
    hub.messages.subscribe(
        lambda message: (
            shared.append(message.property_name)
            if isinstance(message, PropertyChangedMessage) and message.sender is vm
            else None
        )
    )

    load = asyncio.create_task(vm.load())
    await _wait_until(lambda: vm.state.status is AsyncResourceStatus.LOADING)
    assert vm.state.status is AsyncResourceStatus.LOADING
    result.set_result(42)
    await load

    assert vm.state.status is AsyncResourceStatus.READY
    assert vm.state.value == 42
    assert local == ["state", "state"]
    assert shared == local
    assert not vm.load_command.can_execute()
    assert vm.reload_command.can_execute()
    assert not vm.cancel_command.can_execute()


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-003")
async def test_ares_003_failure_is_state_not_command_error() -> None:
    failure = RuntimeError("offline")

    async def loader() -> int:
        raise failure

    vm = _vm(loader)
    command_errors: list[BaseException] = []
    vm.load_command.errors.subscribe(command_errors.append)
    vm.load_command.execute()
    await _wait_until(lambda: vm.state.status is AsyncResourceStatus.ERROR)

    assert vm.state.status is AsyncResourceStatus.ERROR
    assert vm.state.error is failure
    assert not hasattr(vm.state, "value")
    assert command_errors == []
    assert vm.reload_command.can_execute()


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-004")
async def test_ares_004_retry_replaces_error() -> None:
    attempts = 0

    async def loader() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first")
        return 7

    vm = _vm(loader)
    await vm.load()
    assert vm.state.status is AsyncResourceStatus.ERROR
    await vm.reload()
    assert vm.state.status is AsyncResourceStatus.READY
    assert vm.state.value == 7
    assert not hasattr(vm.state, "error")


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-005")
async def test_ares_005_cancel_initial_load_to_idle() -> None:
    observed_cancel = False
    started = False

    async def loader() -> int:
        nonlocal observed_cancel, started
        started = True
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            observed_cancel = True
            raise

    vm = _vm(loader)
    load = asyncio.create_task(vm.load())
    await _wait_until(lambda: vm.state.status is AsyncResourceStatus.LOADING)
    await _wait_until(lambda: started)
    vm.cancel_command.execute()
    await load

    assert observed_cancel
    assert vm.state.status is AsyncResourceStatus.IDLE
    vm.cancel()
    assert vm.state.status is AsyncResourceStatus.IDLE


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-006")
async def test_ares_006_retain_previous_across_cancel_and_failure() -> None:
    second: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    failure = RuntimeError("refresh")
    attempts = 0

    async def loader() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 3
        if attempts == 2:
            return await asyncio.shield(second)
        raise failure

    vm = _vm(loader, retention=AsyncResourceRetention.RETAIN_PREVIOUS)
    await vm.load()
    reload_task = asyncio.create_task(vm.reload())
    await _wait_until(lambda: attempts == 2)
    assert vm.state.status is AsyncResourceStatus.LOADING
    assert vm.state.value == 3
    vm.cancel()
    await reload_task
    assert vm.state.status is AsyncResourceStatus.READY
    assert vm.state.value == 3

    await vm.reload()
    assert vm.state.status is AsyncResourceStatus.ERROR
    assert vm.state.value == 3
    assert vm.state.error is failure


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-007")
async def test_ares_007_discard_cleans_before_loading() -> None:
    second: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    attempts = 0
    cleaned: list[int] = []

    async def loader() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 5
        if attempts == 2:
            return await asyncio.shield(second)
        raise RuntimeError("offline")

    vm = _vm(loader, cleanup=cleaned.append)
    await vm.load()
    reload_task = asyncio.create_task(vm.reload())
    await _wait_until(lambda: attempts == 2)
    assert cleaned == [5]
    assert vm.state.status is AsyncResourceStatus.LOADING
    assert not hasattr(vm.state, "value")
    vm.cancel()
    await reload_task
    assert vm.state.status is AsyncResourceStatus.IDLE
    await vm.load()
    assert vm.state.status is AsyncResourceStatus.ERROR
    assert not hasattr(vm.state, "value")


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-008")
async def test_ares_008_latest_start_wins() -> None:
    first: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    second: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    attempts = 0

    async def loader() -> int:
        nonlocal attempts
        attempts += 1
        target = first if attempts == 1 else second
        try:
            return await asyncio.shield(target)
        except asyncio.CancelledError:
            return await asyncio.shield(target)

    vm = _vm(loader)
    older = asyncio.create_task(vm.load())
    await _wait_until(lambda: attempts == 1)
    newer = asyncio.create_task(vm.reload())
    await _wait_until(lambda: attempts == 2)
    first.set_result(1)
    await older
    assert vm.state.status is AsyncResourceStatus.LOADING
    second.set_result(2)
    await newer
    assert vm.state.status is AsyncResourceStatus.READY
    assert vm.state.value == 2


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-009")
async def test_ares_009_stale_success_cleanup_without_notification() -> None:
    first: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    second: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    attempts = 0
    cleaned: list[int] = []

    async def loader() -> int:
        nonlocal attempts
        attempts += 1
        target = first if attempts == 1 else second
        try:
            return await asyncio.shield(target)
        except asyncio.CancelledError:
            return await asyncio.shield(target)

    vm = _vm(loader, cleanup=cleaned.append)
    changes: list[str] = []
    vm.property_changed.subscribe(changes.append)
    older = asyncio.create_task(vm.load())
    await _wait_until(lambda: attempts == 1)
    newer = asyncio.create_task(vm.reload())
    await _wait_until(lambda: attempts == 2)
    second.set_result(2)
    await newer
    count = len(changes)
    first.set_result(1)
    await _wait_until(lambda: cleaned == [1])

    assert cleaned == [1]
    assert len(changes) == count
    assert vm.state.value == 2
    await older


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-010")
async def test_ares_010_replacement_and_disposal_cleanup_once() -> None:
    value = 0
    cleaned: list[int] = []

    async def loader() -> int:
        nonlocal value
        value += 1
        return value

    vm = _vm(
        loader,
        retention=AsyncResourceRetention.RETAIN_PREVIOUS,
        cleanup=cleaned.append,
    )
    await vm.load()
    await vm.reload()
    assert cleaned == [1]
    vm.dispose()
    vm.dispose()
    assert cleaned == [1, 2]


@pytest.mark.asyncio
@pytest.mark.conformance("ARES-011")
async def test_ares_011_dispose_cancels_and_late_completion_is_inert() -> None:
    late: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    cleaned: list[int] = []
    changes: list[str] = []
    calls = 0
    cancellation_observed = False

    async def loader() -> int:
        nonlocal calls, cancellation_observed
        calls += 1
        try:
            return await asyncio.shield(late)
        except asyncio.CancelledError:
            cancellation_observed = True
            return await asyncio.shield(late)

    vm = _vm(loader, cleanup=cleaned.append)
    vm.property_changed.subscribe(changes.append)
    load = asyncio.create_task(vm.load())
    await _wait_until(lambda: calls == 1)
    vm.dispose()
    vm.dispose()
    count = len(changes)
    assert not vm.load_command.can_execute()
    assert not vm.reload_command.can_execute()
    assert not vm.cancel_command.can_execute()
    late.set_result(9)
    await _flush()
    await vm.load()
    await vm.reload()
    vm.cancel()

    assert cleaned == [9]
    assert len(changes) == count
    assert calls == 1
    await load
    # ARES-011: the in-flight loader observed cancellation on dispose (parity with
    # the C# suite's token.IsCancellationRequested assertion).
    assert cancellation_observed

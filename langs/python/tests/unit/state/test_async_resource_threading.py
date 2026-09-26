"""Real-loop regressions for the supported synchronous command caller (#328)."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future

import pytest

import vmx.commands.async_relay_command as commands
from vmx import (
    NULL_DISPATCHER,
    AsyncResourceRetention,
    AsyncResourceStatus,
    AsyncResourceVM,
    MessageHub,
)
from vmx._asyncio_runner import _BACKGROUND_EVENT_LOOP

TIMEOUT = 3


def resource(loader, cleanup=None, retention=AsyncResourceRetention.DISCARD_PREVIOUS):
    return AsyncResourceVM(
        name="threading",
        loader=loader,
        cleanup_value=cleanup,
        retention=retention,
        hub=MessageHub(),
        dispatcher=NULL_DISPATCHER,
    )


async def turns():
    for _ in range(8):
        await asyncio.sleep(0)


def on_loop(loop, coroutine):
    async def bounded():
        return await asyncio.wait_for(coroutine, TIMEOUT)

    return asyncio.run_coroutine_threadsafe(bounded(), loop).result(TIMEOUT + 1)


class NativeCalls:
    """Instrument real native tasks/futures, including terminal registration."""

    def __init__(self, loop):
        self.loop = loop
        self.calls = []
        self.factory = loop.get_task_factory()
        self.create_future = loop.create_future
        recorder = self

        class Task(asyncio.Task):
            def cancel(self, msg=None):
                recorder.record(self, "cancel")
                return super().cancel(msg)

            def add_done_callback(self, fn, *, context=None):
                recorder.record(self, "add_done_callback")
                return super().add_done_callback(fn, context=context)

        class RecordedFuture(asyncio.Future):
            def set_result(self, value):
                recorder.record(self, "set_result")
                return super().set_result(value)

        loop.set_task_factory(lambda loop, coro, **kwargs: Task(coro, loop=loop, **kwargs))
        loop.create_future = lambda: RecordedFuture(loop=loop)

    def record(self, target, action):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self.calls.append((target, action, loop, threading.get_ident()))

    def restore(self):
        self.loop.set_task_factory(self.factory)
        self.loop.create_future = self.create_future

    def assert_owned(self, *targets):
        calls = [call for call in self.calls if any(call[0] is target for target in targets)]
        assert calls
        assert all(call[2] is self.loop for call in calls), calls


@pytest.mark.parametrize("action", ["cancel", "dispose"])
def test_no_loop_command_caller_cancels_on_operation_loop(action, monkeypatch):
    loop = _BACKGROUND_EVENT_LOOP._ensure_started()
    started = threading.Event()
    observed = threading.Event()
    submitted: list[Future] = []
    real_submit = commands.submit_background

    def submit(coroutine):
        future = real_submit(coroutine)
        submitted.append(future)
        return future

    monkeypatch.setattr(commands, "submit_background", submit)

    async def install():
        loop.set_debug(True)
        return NativeCalls(loop)

    recorder = on_loop(loop, install())

    async def loader():
        started.set()
        try:
            await loop.create_future()
        except asyncio.CancelledError:
            observed.set()
            raise

    vm = resource(loader)
    vm.load_command.execute()
    assert started.wait(TIMEOUT)
    operation = vm._operation
    inner = vm.load_command._current_task
    assert operation is not None
    try:
        getattr(vm, action)()
        submitted[0].result(TIMEOUT)
        assert observed.wait(TIMEOUT)
        recorder.assert_owned(operation.task, operation.cancelled, inner)
        assert any(c[0] is operation.cancelled and c[1] == "set_result" for c in recorder.calls)
        assert any(c[0] is operation.task and c[1] == "add_done_callback" for c in recorder.calls)
        if action == "cancel":
            assert vm.state.status is AsyncResourceStatus.IDLE
    finally:

        async def recover():
            # Recovery after a failing assertion is teardown, never acceptance evidence.
            operation.task.cancel()
            vm.load_command.cancel()
            try:
                await asyncio.wait_for(operation.task, TIMEOUT)
            except asyncio.CancelledError:
                pass
            await turns()
            vm.dispose()
            recorder.restore()

        on_loop(loop, recover())
        submitted[0].result(TIMEOUT)


@pytest.mark.asyncio
async def test_same_loop_repeated_cancel_signals_loader_once():
    started = asyncio.Event()
    release = asyncio.Event()
    cancellations = 0
    cleaned = []

    async def loader():
        nonlocal cancellations
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellations += 1
            await release.wait()
            return 7

    vm = resource(loader, cleaned.append)
    waiter = asyncio.create_task(vm.load())
    await asyncio.wait_for(started.wait(), TIMEOUT)
    operation = vm._operation
    vm.cancel()
    await asyncio.wait_for(waiter, TIMEOUT)
    vm.cancel()
    vm._cancel_operation(operation)
    vm._register_late_cleanup(operation)
    release.set()
    await turns()
    assert cancellations == 1
    assert cleaned == [7]
    vm.dispose()


@pytest.mark.asyncio
async def test_loading_observer_cancels_before_loader_body():
    calls = []

    async def loader():
        calls.append(True)
        return 1

    vm = resource(loader)
    vm.property_changed.subscribe(
        lambda _: vm.cancel() if vm.state.status is AsyncResourceStatus.LOADING else None
    )
    await asyncio.wait_for(vm.load(), TIMEOUT)
    assert calls == []
    assert vm.state.status is AsyncResourceStatus.IDLE
    vm.dispose()


@pytest.mark.asyncio
async def test_disposal_during_replacement_cleanup_cannot_republish_ready():
    values = iter((1, 2))
    cleaned = []
    changes = []

    async def loader():
        return next(values)

    def cleanup(value):
        cleaned.append(value)
        vm.dispose()

    vm = resource(loader, cleanup, AsyncResourceRetention.RETAIN_PREVIOUS)
    vm.property_changed.subscribe(
        lambda name: changes.append(vm.state) if name == "state" else None
    )
    await asyncio.wait_for(vm.load(), TIMEOUT)
    await asyncio.wait_for(vm.reload(), TIMEOUT)
    assert cleaned == [1, 2]
    assert vm._stable_state.status is AsyncResourceStatus.IDLE
    assert len(changes) == 3


@pytest.mark.parametrize("action", ["cancel", "dispose"])
def test_true_completion_invalidation_race_claims_returned_value(action, monkeypatch):
    loop = _BACKGROUND_EVENT_LOOP._ensure_started()
    at_check = threading.Event()
    release_check = threading.Event()
    disposal_entered = threading.Event()
    cleaned = []
    vm = resource(lambda: asyncio.sleep(0, result=11), cleaned.append)
    original_current = vm._is_operation_current
    original_dispose = vm._on_dispose if action == "dispose" else vm.cancel

    def checked(operation):
        current = original_current(operation)
        if current and operation.task.done():
            at_check.set()
            assert release_check.wait(TIMEOUT)
        return current

    def disposing():
        disposal_entered.set()
        original_dispose()

    monkeypatch.setattr(vm, "_is_operation_current", checked)
    monkeypatch.setattr(vm, "_on_dispose" if action == "dispose" else "cancel", disposing)
    waiter = asyncio.run_coroutine_threadsafe(asyncio.wait_for(vm.load(), TIMEOUT), loop)
    assert at_check.wait(TIMEOUT)
    errors = []

    def dispose():
        try:
            getattr(vm, action)()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=dispose)
    thread.start()
    try:
        assert disposal_entered.wait(TIMEOUT)
    finally:
        release_check.set()
        thread.join(TIMEOUT)
    assert not thread.is_alive()
    waiter.result(TIMEOUT)
    on_loop(loop, turns())
    assert errors == []
    if action == "cancel":
        assert vm.state.status is AsyncResourceStatus.READY
        vm.dispose()
    assert cleaned == [11]
    assert vm._stable_state.status is AsyncResourceStatus.IDLE


@pytest.mark.parametrize("action", ["cancel", "dispose"])
def test_stopped_open_loop_queues_resource_and_linked_command(action):
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    recorder = NativeCalls(loop)
    started = asyncio.Event()
    cleaned = []

    async def loader():
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            return 3

    vm = resource(loader, cleaned.append)
    waiter = loop.create_task(vm.load_command.execute_async())
    try:
        loop.run_until_complete(asyncio.wait_for(started.wait(), TIMEOUT))
        operation = vm._operation
        inner = vm.load_command._current_task
        assert operation is not None
        recorder.calls.clear()
        getattr(vm, action)()
        assert recorder.calls == []
        assert not operation.cancelled.done()
        loop.run_until_complete(asyncio.wait_for(waiter, TIMEOUT))
        loop.run_until_complete(turns())
        recorder.assert_owned(operation.task, operation.cancelled, inner)
        assert cleaned == [3]
    finally:

        async def finish():
            vm.dispose()
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task() and not task.done():
                    task.cancel()
            await turns()

        loop.run_until_complete(asyncio.wait_for(finish(), TIMEOUT))
        recorder.restore()
        loop.close()


@pytest.mark.parametrize("close", [False, True], ids=["completed_registration", "closed_terminal"])
def test_terminal_result_consumed_once_across_deferred_registration(close):
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    recorder = NativeCalls(loop)
    cleaned = []
    started = asyncio.Event()
    release = loop.create_future()

    async def loader():
        started.set()
        return await release

    vm = resource(loader, cleaned.append)
    waiter = loop.create_task(vm.load())
    operation = None
    try:
        loop.run_until_complete(asyncio.wait_for(started.wait(), TIMEOUT))
        operation = vm._operation
        assert operation is not None
        # Stop after the loader finishes but before the public waiter consumes it.
        loop.call_soon(operation.task.add_done_callback, lambda _: loop.stop())
        loop.call_soon(release.set_result, 13)
        loop.run_forever()
        assert operation.task.done()
        assert not waiter.done()
        recorder.calls.clear()
        if close:
            loop.close()
        vm.dispose()
        vm._register_late_cleanup(operation)
        vm._cancel_operation(operation)
        assert recorder.calls == []
        if not close:
            loop.run_until_complete(asyncio.wait_for(waiter, TIMEOUT))
            loop.run_until_complete(turns())
            recorder.assert_owned(operation.task, operation.cancelled)
        assert cleaned == [13]
        assert vm._stable_state.status is AsyncResourceStatus.IDLE
    finally:
        if loop.is_closed():
            # The host deliberately destroyed the loop with a suspended waiter.
            # Close its coroutine for fixture hygiene; this is not runtime progress.
            waiter.get_coro().close()
            waiter._log_destroy_pending = False
        else:
            loop.run_until_complete(asyncio.wait_for(waiter, TIMEOUT))
            recorder.restore()
            loop.close()


def test_closed_pending_loop_preserves_invalidation_without_native_mutation():
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    recorder = NativeCalls(loop)
    started = asyncio.Event()

    async def loader():
        started.set()
        await asyncio.Future()
        return 1

    vm = resource(loader)
    waiter = loop.create_task(vm.load_command.execute_async())
    loop.run_until_complete(asyncio.wait_for(started.wait(), TIMEOUT))
    operation = vm._operation
    inner = vm.load_command._current_task
    assert operation is not None and inner is not None
    loop.close()
    recorder.calls.clear()
    try:
        vm.dispose()
        assert vm._operation is None
        assert vm._resource_disposed
        assert not operation.task.done()
        assert not operation.cancelled.done()
        assert not waiter.done()
        assert recorder.calls == []
    finally:
        for task in (operation.task, inner, waiter):
            task.get_coro().close()
            task._log_destroy_pending = False


@pytest.mark.parametrize("closed", [False, True], ids=["unrelated_error", "close_during_enqueue"])
def test_enqueue_only_suppresses_confirmed_closure(closed, monkeypatch):
    from vmx._asyncio_runner import post_to_loop

    loop = asyncio.new_event_loop()
    called = []

    def schedule(callback):
        if closed:
            loop.close()
        raise RuntimeError("enqueue failure")

    monkeypatch.setattr(loop, "call_soon_threadsafe", schedule)
    try:
        if closed:
            assert post_to_loop(loop, lambda: called.append(True)) is False
        else:
            with pytest.raises(RuntimeError, match="enqueue failure"):
                post_to_loop(loop, lambda: called.append(True))
        assert called == []
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_task_factory_can_wait_for_foreign_disposal_without_resource_gate():
    loop = asyncio.get_running_loop()
    original = loop.get_task_factory()
    threads = []
    calls = []
    vm = resource(lambda: asyncio.sleep(0, result=1), calls.append)
    blocked = []

    def factory(loop, coroutine, **kwargs):
        # The custom hook is allowed to synchronize with a caller disposing the VM.
        thread = threading.Thread(target=vm.dispose)
        threads.append(thread)
        thread.start()
        thread.join(TIMEOUT)
        blocked.append(thread.is_alive())
        return asyncio.Task(coroutine, loop=loop, **kwargs)

    async def load():
        loop.set_task_factory(factory)
        try:
            await vm.load()
        finally:
            loop.set_task_factory(original)

    await asyncio.wait_for(load(), TIMEOUT + 1)
    for thread in threads:
        thread.join(TIMEOUT)
    await turns()
    assert blocked == [False]
    assert vm._operation is None
    assert calls == []


@pytest.mark.asyncio
async def test_cancel_rolls_back_before_observer_new_intent_without_cancelling_it():
    started = asyncio.Event()
    newer = []
    calls = 0
    command_cancel_states = []
    vm = None

    async def loader():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await asyncio.Future()
        return 19

    vm = resource(loader)
    original = vm.load_command.cancel

    def recorded_cancel():
        command_cancel_states.append(len(newer))
        original()

    vm.load_command.cancel = recorded_cancel

    def observe(name):
        if name == "state" and vm.state.status is AsyncResourceStatus.IDLE and not newer:
            newer.append(asyncio.create_task(vm.load_command.execute_async()))

    vm.property_changed.subscribe(observe)
    first = asyncio.create_task(vm.load())
    await asyncio.wait_for(started.wait(), TIMEOUT)
    vm.cancel()
    await asyncio.wait_for(first, TIMEOUT)
    await asyncio.wait_for(newer[0], TIMEOUT)
    assert command_cancel_states == [0]
    assert vm.state.value == 19
    vm.dispose()


@pytest.mark.asyncio
async def test_retained_and_late_identical_values_each_clean_once_during_recursive_disposal():
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    cleaned = []

    async def loader():
        nonlocal calls
        calls += 1
        if calls > 1:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                await release.wait()
        return 7

    def cleanup(value):
        cleaned.append(value)
        vm.dispose()

    vm = resource(loader, cleanup, AsyncResourceRetention.RETAIN_PREVIOUS)
    await asyncio.wait_for(vm.load(), TIMEOUT)
    waiter = asyncio.create_task(vm.reload())
    await asyncio.wait_for(started.wait(), TIMEOUT)
    vm.dispose()
    assert cleaned == [7]
    await asyncio.wait_for(waiter, TIMEOUT)
    release.set()
    await turns()
    assert cleaned == [7, 7]


@pytest.mark.asyncio
async def test_disposal_preserves_unrelated_enqueue_error_and_releases_accepted_value(monkeypatch):
    import vmx.state.async_resource_vm as resources

    started = asyncio.Event()
    cleaned = []
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        if calls > 1:
            started.set()
            await asyncio.Future()
        return 5

    vm = resource(loader, cleaned.append, AsyncResourceRetention.RETAIN_PREVIOUS)
    await asyncio.wait_for(vm.load(), TIMEOUT)
    waiter = asyncio.create_task(vm.reload())
    await asyncio.wait_for(started.wait(), TIMEOUT)
    operation = vm._operation
    assert operation is not None
    errors = []

    def fail_enqueue(loop, callback):
        raise RuntimeError("unrelated enqueue failure")

    def dispose():
        try:
            vm.dispose()
        except BaseException as error:
            errors.append(error)

    with monkeypatch.context() as patch:
        patch.setattr(resources, "post_to_loop", fail_enqueue)
        thread = threading.Thread(target=dispose)
        thread.start()
        thread.join(TIMEOUT)
        assert not thread.is_alive()
    assert len(errors) == 1
    assert str(errors[0]) == "unrelated enqueue failure"
    assert cleaned == [5]
    assert not vm.load_command.can_execute()
    assert not vm.reload_command.can_execute()
    # The injected unrelated failure prevented enqueue. Restore and drain explicitly.
    vm._cancel_operation(operation)
    await asyncio.wait_for(waiter, TIMEOUT)
    await turns()

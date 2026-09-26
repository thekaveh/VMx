"""Real worker-to-loop lifecycle regressions for the asyncio dispatcher."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from tests.unit.helpers.real_asyncio_dispatcher import RunningAsyncioDispatcher
from vmx.components.component_vm import ComponentVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.services.message_hub import MessageHub


def _build_vm(
    harness: RunningAsyncioDispatcher,
    hub: MessageHub[object],
    *,
    on_construct: Callable[[], None] | None = None,
    on_destruct: Callable[[], None] | None = None,
) -> ComponentVM:
    builder = (
        ComponentVM.builder()
        .name("real-asyncio")
        .services(hub, harness.dispatcher)
        .background(True)
    )
    if on_construct is not None:
        builder = builder.on_construct(on_construct)
    if on_destruct is not None:
        builder = builder.on_destruct(on_destruct)
    return builder.build()


@pytest.mark.parametrize(
    ("operation", "failure", "expected"),
    [
        ("construct", False, ConstructionStatus.CONSTRUCTED),
        ("construct", True, ConstructionStatus.DESTRUCTED),
        ("destruct", False, ConstructionStatus.DESTRUCTED),
        ("destruct", True, ConstructionStatus.CONSTRUCTED),
    ],
)
def test_real_asyncio_background_lifecycle_delivers_terminal_status_on_loop(
    operation: str, failure: bool, expected: ConstructionStatus
) -> None:
    with RunningAsyncioDispatcher() as harness:
        hub: MessageHub[object] = MessageHub()
        hook_threads: list[int] = []

        def hook() -> None:
            harness.record_worker()
            hook_threads.append(threading.get_ident())
            if failure:
                error = RuntimeError(f"{operation} failed")
                harness.errors.append(error)
                raise error

        vm = _build_vm(
            harness,
            hub,
            on_construct=hook if operation == "construct" else None,
            on_destruct=hook if operation == "destruct" else None,
        )
        try:
            if operation == "destruct":
                constructed = threading.Event()
                initial_subscription = hub.messages.subscribe(
                    lambda message: (
                        constructed.set()
                        if isinstance(message, ConstructionStatusChangedMessage)
                        and message.sender is vm
                        and message.status is ConstructionStatus.CONSTRUCTED
                        else None
                    )
                )
                try:
                    initial_admission = harness.watch_next_foreground_admission()
                    vm.construct()
                    harness.assert_event(initial_admission, "initial terminal enqueue")
                    harness.assert_event(constructed, "initial construction")
                finally:
                    initial_subscription.dispose()

            terminal_threads: list[int] = []
            terminal = threading.Event()
            subscription = hub.messages.subscribe(
                lambda message: (
                    (terminal_threads.append(threading.get_ident()), terminal.set())
                    if isinstance(message, ConstructionStatusChangedMessage)
                    and message.sender is vm
                    and message.status is expected
                    else None
                )
            )
            try:
                admission = harness.watch_next_foreground_admission()
                if operation == "destruct":
                    vm.destruct()
                else:
                    vm.construct()

                harness.assert_event(admission, f"{operation} terminal enqueue")
                harness.assert_event(terminal, f"{operation} terminal delivery")
                assert vm.status is expected
                assert terminal_threads == [harness.thread.ident]
                assert len(hook_threads) == 1
                assert hook_threads[0] != harness.thread.ident
            finally:
                subscription.dispose()
        finally:
            vm.dispose()


def test_dispose_before_queued_terminal_delivery_does_not_resurrect_vm() -> None:
    with RunningAsyncioDispatcher() as harness:
        hub: MessageHub[object] = MessageHub()
        blocker_started = threading.Event()
        release_blocker = threading.Event()
        terminal_statuses: list[ConstructionStatus] = []

        def block_loop() -> None:
            blocker_started.set()
            if not release_blocker.wait(harness.timeout * 2):
                harness.errors.append(AssertionError("foreground blocker release timed out"))

        harness.loop.call_soon_threadsafe(block_loop)

        def hook() -> None:
            harness.record_worker()

        vm = _build_vm(harness, hub, on_construct=hook)
        subscription = hub.messages.subscribe(
            lambda message: (
                terminal_statuses.append(message.status)
                if isinstance(message, ConstructionStatusChangedMessage)
                and message.sender is vm
                and message.status is ConstructionStatus.CONSTRUCTED
                else None
            )
        )
        try:
            harness.assert_event(blocker_started, "foreground blocker")
            admission = harness.watch_next_foreground_admission()
            vm.construct()
            harness.assert_event(admission, "queued terminal delivery")
            vm.dispose()
            release_blocker.set()

            foreground_drained = threading.Event()
            harness.loop.call_soon_threadsafe(foreground_drained.set)
            harness.assert_event(foreground_drained, "queued foreground work")
            assert vm.status is ConstructionStatus.DISPOSED
            assert terminal_statuses == []
        finally:
            release_blocker.set()
            subscription.dispose()
            vm.dispose()

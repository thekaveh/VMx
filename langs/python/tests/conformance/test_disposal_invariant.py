"""Cross-cutting disposal invariant (DISP-001..006)."""

from __future__ import annotations

import asyncio
import threading

import pytest
from reactivex.subject import BehaviorSubject

from vmx.collections import BatchUpdateHandle
from vmx.commands import AsyncRelayCommand
from vmx.components.builders import ComponentVMBuilder
from vmx.composites.builders import CompositeVMBuilder
from vmx.dialogs import ModalVM
from vmx.forms import FormVM
from vmx.lifecycle import ConstructionStatus
from vmx.messages import ConstructionStatusChangedMessage
from vmx.notifications import Notification, NotificationHub, NotificationReaction, NotificationType
from vmx.properties import from_sources
from vmx.services import MessageHub, RxDispatcher


@pytest.mark.conformance("DISP-001")
def test_disp_001_parent_cascade_is_observably_idempotent() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    child = ComponentVMBuilder().name("child").services(hub, dispatcher).build()
    parent = (
        CompositeVMBuilder().name("parent").services(hub, dispatcher).children(lambda: ()).build()
    )
    parent.append(child)
    disposed: list[str] = []
    hub.messages.subscribe(
        lambda message: (
            disposed.append(message.sender_name)
            if isinstance(message, ConstructionStatusChangedMessage)
            and message.status is ConstructionStatus.DISPOSED
            else None
        )
    )

    parent.dispose()
    parent.dispose()

    assert disposed.count("child") == 1
    assert disposed.count("parent") == 1


@pytest.mark.conformance("DISP-002")
async def test_disp_002_repeated_async_command_dispose_cancels_one_inflight_run() -> None:
    started = asyncio.Event()
    cancellations = 0

    async def task() -> None:
        nonlocal cancellations
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancellations += 1
            raise

    command = AsyncRelayCommand.builder().task(task).build()
    run = asyncio.create_task(command.execute_async())
    await started.wait()
    command.dispose()
    command.dispose()
    await run

    assert cancellations == 1
    assert command.can_execute() is False


@pytest.mark.conformance("DISP-003")
async def test_disp_003_concurrent_notification_hub_dispose_completes_once() -> None:
    hub = NotificationHub()
    completions: list[None] = []
    hub.pending.subscribe(on_completed=lambda: completions.append(None))
    pending = hub.post(Notification(NotificationType.NOTIFICATION, "info"))
    barrier = threading.Barrier(32)

    def dispose() -> None:
        barrier.wait()
        hub.dispose()

    threads = [threading.Thread(target=dispose) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert await pending is NotificationReaction.PENDING
    assert len(completions) == 1


@pytest.mark.conformance("DISP-004")
async def test_disp_004_interaction_owners_complete_once_and_keep_first_result() -> None:
    async def persist(_: int) -> None:
        return None

    form = FormVM(1, persist)
    completions: list[None] = []
    form.on_approved.subscribe(on_completed=lambda: completions.append(None))
    form.dispose()
    form.dispose()
    assert len(completions) == 1

    modal = ModalVM("cancel")
    modal.dismiss("first")
    modal.dispose()
    modal.dispose()
    assert await modal.wait_result() == "first"


@pytest.mark.conformance("DISP-005")
def test_disp_005_reactive_helper_completes_once_and_retains_last_value() -> None:
    source: BehaviorSubject[int] = BehaviorSubject(7)
    property_ = from_sources(source, transform=lambda value: value)
    completions: list[None] = []
    property_.value_changed.subscribe(on_completed=lambda: completions.append(None))

    property_.dispose()
    property_.dispose()
    source.on_next(8)

    assert property_.value == 7
    assert len(completions) == 1


@pytest.mark.conformance("DISP-006")
def test_disp_006_batch_handle_ends_one_batch_once() -> None:
    class Host:
        exits = 0

        def _exit_batch(self) -> None:
            self.exits += 1

    host = Host()
    handle = BatchUpdateHandle(host)
    handle.dispose()
    handle.dispose()

    assert host.exits == 1

"""Tests for NotificationsVM."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from reactivex.scheduler import ImmediateScheduler
from reactivex.testing import TestScheduler

from vmx import MessageHub, RxDispatcher
from vmx.messages.protocols import Message
from vmx.notifications import Notification, NotificationHub, NotificationType

from notes_showcase.viewmodels.notifications_vm import NotificationsVM


def _build(
    *,
    cap: int = 5,
    scheduler: object | None = None,
    lifespan: timedelta | None = None,
) -> tuple[NotificationsVM, NotificationHub]:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    notification_hub = NotificationHub()
    # Default to TestScheduler so notification lifespans don't fire real timers
    # during tests; pass a custom scheduler when timer behavior is exercised.
    sched = scheduler if scheduler is not None else TestScheduler()
    builder = (
        NotificationsVM.builder()
        .name("notifications")
        .services(hub, dispatcher)
        .notification_hub(notification_hub)
        .cap(cap)
        .scheduler(sched)  # type: ignore[arg-type]
    )
    if lifespan is not None:
        builder = builder.lifespan(lifespan)
    return builder.build(), notification_hub


async def test_visible_initially_empty() -> None:
    vm, _ = _build()
    vm.construct()
    assert vm.visible.count == 0


async def test_posting_a_notification_adds_visible_entry() -> None:
    vm, hub = _build()
    vm.construct()
    fut = hub.post(Notification(NotificationType.NOTIFICATION, "hello"))
    assert vm.visible.count == 1
    # Resolve the future before teardown so no warning is emitted.
    hub.resolve(Notification(NotificationType.NOTIFICATION, "x"), None)  # type: ignore[arg-type]
    fut.cancel()
    try:
        await fut
    except (asyncio.CancelledError, Exception):
        pass


async def test_cap_drops_oldest_when_over_limit() -> None:
    vm, hub = _build(cap=3)
    vm.construct()
    futures = [
        hub.post(Notification(NotificationType.NOTIFICATION, f"m{i}"))
        for i in range(5)
    ]
    assert vm.visible.count == 3
    # Newest three should remain.
    titles = [v.notification.message for v in vm.visible]
    assert titles == ["m2", "m3", "m4"]
    for f in futures:
        f.cancel()
        try:
            await f
        except (asyncio.CancelledError, Exception):
            pass


async def test_auto_dismiss_resolves_notification_after_lifespan() -> None:
    scheduler = TestScheduler()
    vm, hub = _build(scheduler=scheduler, lifespan=timedelta(seconds=1))
    vm.construct()
    fut = hub.post(Notification(NotificationType.NOTIFICATION, "expires"))
    assert vm.visible.count == 1
    # Advance virtual time past the lifespan to trigger auto-dismiss.
    scheduler.advance_by(scheduler.to_seconds(1.5))
    # Yield to let any scheduled call_soon_threadsafe deliveries land.
    await asyncio.sleep(0)
    assert vm.visible.count == 0
    assert fut.done()


def test_default_cap_is_5() -> None:
    vm, _ = _build()
    assert vm.cap == 5
    assert NotificationsVM.DEFAULT_CAP == 5


async def test_dispose_clears_visible() -> None:
    vm, hub = _build()
    vm.construct()
    fut = hub.post(Notification(NotificationType.NOTIFICATION, "n"))
    assert vm.visible.count == 1
    vm.dispose()
    assert vm.visible.count == 0
    fut.cancel()
    try:
        await fut
    except (asyncio.CancelledError, Exception):
        pass


def test_builder_requires_name_and_notification_hub() -> None:
    with pytest.raises(ValueError, match="name"):
        NotificationsVM.builder().build()
    with pytest.raises(ValueError, match="notification_hub"):
        NotificationsVM.builder().name("x").build()

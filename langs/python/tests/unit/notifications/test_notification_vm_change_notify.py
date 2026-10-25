"""VMX-079/135 regression — NotificationVM change-notification.

NotificationVM now exposes a ``property_changed`` stream so a binding view can
repaint the decaying state. ``is_resolved`` always emits on resolution; with a
``tick_interval`` the time-varying ``remaining_time``/``opacity`` emit
periodically while the notification fades.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from reactivex.testing import TestScheduler

from vmx.notifications import (
    ConfirmationVM,
    Notification,
    NotificationHub,
    NotificationType,
    NotificationVM,
)


async def test_decay_emits_property_changed_with_tick_interval() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "fade")
    hub.post(notif)
    vm = NotificationVM(
        notif,
        hub,
        scheduler,
        lifespan=timedelta(seconds=10),
        tick_interval=timedelta(seconds=1),
    )

    changed: list[str] = []
    vm.property_changed.subscribe(on_next=changed.append)

    scheduler.advance_by(3)  # three decay ticks

    assert "opacity" in changed
    assert "remaining_time" in changed
    vm.dispose()


async def test_is_resolved_emits_on_dismiss_without_tick_interval() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "resolve")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))

    changed: list[str] = []
    vm.property_changed.subscribe(on_next=changed.append)

    vm.dismiss_command.execute()

    assert "is_resolved" in changed
    vm.dispose()


async def test_poll_only_when_no_tick_interval() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "poll")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))

    decay_changes = 0

    def _count(name: str) -> None:
        nonlocal decay_changes
        if name in ("opacity", "remaining_time"):
            decay_changes += 1

    vm.property_changed.subscribe(on_next=_count)

    scheduler.advance_by(5)  # within lifespan, not yet resolved

    assert decay_changes == 0
    assert vm.is_resolved is False
    vm.dispose()


async def test_confirmation_vm_forwards_tick_interval() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.CONFIRMATION, "confirm")
    hub.post(notif)
    vm = ConfirmationVM(
        notif,
        hub,
        scheduler,
        lifespan=timedelta(seconds=10),
        tick_interval=timedelta(seconds=1),
    )

    saw_opacity = False

    def _watch(name: str) -> None:
        nonlocal saw_opacity
        if name == "opacity":
            saw_opacity = True

    vm.property_changed.subscribe(on_next=_watch)

    scheduler.advance_by(2)

    assert saw_opacity
    vm.dispose()


async def test_external_resolve_after_dispose_is_inert() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "late")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))
    changed: list[str] = []
    vm.property_changed.subscribe(on_next=changed.append)
    vm.dispose()

    vm.notify_external_resolve()

    assert vm.is_resolved is False
    assert changed == []


async def test_reject_during_confirmation_teardown_does_not_resolve_the_hub() -> None:
    # #730: a command executed from a teardown observer is inert after dispose.
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.CONFIRMATION, "confirm")
    result = hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)
    rejects: list[None] = []

    def reject_during_teardown(*_: object) -> None:
        rejects.append(None)
        vm.reject_command.execute()

    vm.approve_command.can_execute_changed.subscribe(reject_during_teardown)

    vm.dispose()
    await asyncio.sleep(0)  # the hub completes post results on the next loop turn

    assert rejects, "the teardown observer ran"
    assert vm.is_resolved is False
    assert not result.done()


async def test_expiry_admitted_before_dispose_does_not_resolve_the_hub() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "late expiry")
    result = hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))
    vm.dispose()

    vm._on_expire()
    await asyncio.sleep(0)  # the hub completes post results on the next loop turn

    assert vm.is_resolved is False
    assert not result.done()

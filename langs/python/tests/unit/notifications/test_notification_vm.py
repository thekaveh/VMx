"""Unit tests for NotificationVM — edge cases and implementation details.

Conformance-level tests live in tests/conformance/test_notifications.py.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from reactivex.scheduler import ImmediateScheduler
from reactivex.testing import TestScheduler

from vmx.notifications import (
    Notification,
    NotificationHub,
    NotificationReaction,
    NotificationType,
    NotificationVM,
    NullNotificationHub,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def make_vm(
    lifespan: timedelta = timedelta(seconds=60),
    hub: NotificationHub | None = None,
) -> tuple[NotificationVM, NotificationHub, TestScheduler, Notification]:
    scheduler = TestScheduler()
    if hub is None:
        hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "test")
    hub.post(notification)
    vm = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=lifespan,
    )
    return vm, hub, scheduler, notification


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


async def test_initial_opacity_is_one() -> None:
    vm, _, _, _ = await make_vm()
    assert vm.opacity == pytest.approx(1.0)
    vm.dispose()


async def test_initial_remaining_time_equals_lifespan() -> None:
    lifespan = timedelta(seconds=30)
    vm, _, _, _ = await make_vm(lifespan=lifespan)
    assert vm.remaining_time == lifespan
    vm.dispose()


async def test_initial_is_not_resolved() -> None:
    vm, _, _, _ = await make_vm()
    assert not vm.is_resolved
    vm.dispose()


async def test_lifespan_default_is_60s() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "x")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler)
    assert vm.lifespan == timedelta(seconds=60)
    vm.dispose()


# ---------------------------------------------------------------------------
# Opacity decay
# ---------------------------------------------------------------------------


async def test_opacity_zero_at_lifespan() -> None:
    lifespan = timedelta(seconds=10)
    vm, _, scheduler, _ = await make_vm(lifespan=lifespan)
    scheduler.advance_by(10)
    assert vm.opacity == pytest.approx(0.0, abs=0.01)
    vm.dispose()


async def test_opacity_midpoint_at_half_lifespan() -> None:
    lifespan = timedelta(seconds=10)
    vm, _, scheduler, _ = await make_vm(lifespan=lifespan)
    scheduler.advance_by(5)
    assert vm.opacity == pytest.approx(0.5, abs=0.01)
    vm.dispose()


async def test_opacity_does_not_go_negative() -> None:
    lifespan = timedelta(seconds=5)
    vm, _, scheduler, _ = await make_vm(lifespan=lifespan)
    scheduler.advance_by(100)  # way past lifespan
    assert vm.opacity >= 0.0
    vm.dispose()


async def test_zero_lifespan_opacity_is_zero() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "x")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(0))
    assert vm.opacity == 0.0
    vm.dispose()


async def test_zero_lifespan_supports_synchronous_scheduler() -> None:
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "immediate")
    completion = hub.post(notification)

    vm = NotificationVM(
        notification,
        hub,
        ImmediateScheduler(),
        lifespan=timedelta(0),
    )
    await asyncio.sleep(0)

    assert vm.is_resolved
    assert completion.done()
    assert completion.result() is NotificationReaction.APPROVE
    vm.dispose()


# ---------------------------------------------------------------------------
# Auto-dismiss
# ---------------------------------------------------------------------------


async def test_auto_dismiss_sets_is_resolved() -> None:
    lifespan = timedelta(seconds=5)
    vm, _, scheduler, _ = await make_vm(lifespan=lifespan)
    scheduler.advance_by(5)
    assert vm.is_resolved
    vm.dispose()


async def test_no_auto_dismiss_before_lifespan() -> None:
    lifespan = timedelta(seconds=10)
    vm, _, scheduler, _ = await make_vm(lifespan=lifespan)
    scheduler.advance_by(9)
    assert not vm.is_resolved
    vm.dispose()


# ---------------------------------------------------------------------------
# DismissCommand
# ---------------------------------------------------------------------------


async def test_dismiss_command_resolves_with_approve() -> None:
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.NOTIFICATION, "dismiss")
    task = hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))

    vm.dismiss_command.execute()

    assert vm.is_resolved
    assert await task == NotificationReaction.APPROVE
    vm.dispose()


async def test_dismiss_command_cancels_timer() -> None:
    """After manual dismiss, advancing the scheduler does not double-resolve."""
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.NOTIFICATION, "dismiss")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))

    vm.dismiss_command.execute()
    assert vm.is_resolved

    # Advance well past lifespan — must not error or double-resolve
    scheduler.advance_by(100)
    assert vm.is_resolved
    vm.dispose()


async def test_dismiss_is_idempotent() -> None:
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.NOTIFICATION, "x")
    hub.post(notif)
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))

    vm.dismiss_command.execute()
    vm.dismiss_command.execute()  # must not raise
    assert vm.is_resolved
    vm.dispose()


# ---------------------------------------------------------------------------
# NullNotificationHub (no hub message flow)
# ---------------------------------------------------------------------------


def test_with_null_hub_does_not_auto_resolve_from_pending() -> None:
    """NullNotificationHub emits empty Pending; VM must not spuriously resolve.

    This test is sync because NullNotificationHub does not use asyncio.
    """
    scheduler = TestScheduler()
    hub = NullNotificationHub()
    notif = Notification(NotificationType.NOTIFICATION, "x")
    # NullNotificationHub.post requires an event loop; we skip posting here
    # to test only the pending-subscription guard does not spuriously fire.
    vm = NotificationVM(notif, hub, scheduler, lifespan=timedelta(seconds=10))
    # At t=0 must not be resolved
    assert not vm.is_resolved
    vm.dispose()

"""Unit tests for ConfirmationVM — edge cases and implementation details.

Conformance-level tests live in tests/conformance/test_notifications.py.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from reactivex.testing import TestScheduler

from vmx.notifications import (
    ConfirmationVM,
    Notification,
    NotificationHub,
    NotificationReaction,
    NotificationType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def make_confirmation_vm(
    lifespan: timedelta | None = None,
) -> tuple[ConfirmationVM, NotificationHub, TestScheduler, Notification]:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notification = Notification(NotificationType.CONFIRMATION, "confirm?")
    hub.post(notification)
    vm = ConfirmationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=lifespan,
    )
    return vm, hub, scheduler, notification


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


async def test_default_lifespan_is_300s() -> None:
    scheduler = TestScheduler()
    hub = NotificationHub()
    notif = Notification(NotificationType.CONFIRMATION, "x")
    hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)
    assert vm.lifespan == timedelta(seconds=300)
    vm.dispose()


async def test_initial_is_not_resolved() -> None:
    vm, _, _, _ = await make_confirmation_vm()
    assert not vm.is_resolved
    vm.dispose()


async def test_initial_opacity_is_one() -> None:
    vm, _, _, _ = await make_confirmation_vm()
    assert vm.opacity == pytest.approx(1.0)
    vm.dispose()


# ---------------------------------------------------------------------------
# No auto-dismiss on expiry
# ---------------------------------------------------------------------------


async def test_confirmation_does_not_auto_dismiss_on_expiry() -> None:
    """ConfirmationVM must NOT auto-resolve when lifespan expires."""
    lifespan = timedelta(seconds=5)
    vm, _, scheduler, _ = await make_confirmation_vm(lifespan=lifespan)

    scheduler.advance_by(5)  # lifespan reached

    assert not vm.is_resolved, "ConfirmationVM must NOT auto-dismiss on expiry"
    vm.dispose()


async def test_confirmation_stays_unresolved_well_past_lifespan() -> None:
    lifespan = timedelta(seconds=5)
    vm, _, scheduler, _ = await make_confirmation_vm(lifespan=lifespan)
    scheduler.advance_by(300)
    assert not vm.is_resolved
    vm.dispose()


# ---------------------------------------------------------------------------
# ApproveCommand
# ---------------------------------------------------------------------------


async def test_approve_command_sets_hub_reaction() -> None:
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.CONFIRMATION, "approve?")
    task = hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)

    vm.approve_command.execute()
    assert await task == NotificationReaction.APPROVE
    vm.dispose()


async def test_approve_command_sets_is_resolved() -> None:
    vm, _, _, _ = await make_confirmation_vm()
    vm.approve_command.execute()
    assert vm.is_resolved
    vm.dispose()


# ---------------------------------------------------------------------------
# RejectCommand
# ---------------------------------------------------------------------------


async def test_reject_command_resolves_with_reject() -> None:
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.CONFIRMATION, "reject?")
    task = hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)

    vm.reject_command.execute()
    assert vm.is_resolved
    assert await task == NotificationReaction.REJECT
    vm.dispose()


# ---------------------------------------------------------------------------
# DismissCommand (inherited from NotificationVM)
# ---------------------------------------------------------------------------


async def test_dismiss_command_resolves_with_approve_on_confirmation_vm() -> None:
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.CONFIRMATION, "dismiss")
    task = hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)

    vm.dismiss_command.execute()
    assert vm.is_resolved
    assert await task == NotificationReaction.APPROVE
    vm.dispose()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_approve_then_reject_is_idempotent() -> None:
    """Second command after first must be a no-op."""
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.CONFIRMATION, "x")
    task = hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)

    vm.approve_command.execute()
    vm.reject_command.execute()  # must not raise or change result

    assert await task == NotificationReaction.APPROVE  # first wins
    vm.dispose()


async def test_reject_then_approve_is_idempotent() -> None:
    hub = NotificationHub()
    scheduler = TestScheduler()
    notif = Notification(NotificationType.CONFIRMATION, "x")
    task = hub.post(notif)
    vm = ConfirmationVM(notif, hub, scheduler)

    vm.reject_command.execute()
    vm.approve_command.execute()  # no-op

    assert await task == NotificationReaction.REJECT  # first wins
    vm.dispose()

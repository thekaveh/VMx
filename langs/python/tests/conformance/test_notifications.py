"""Conformance tests: NOTIF-001..016 — notification sub-package.

Per spec/16-notifications.md, ADR-0013, ADR-0031.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from threading import Barrier, Thread

import pytest
from reactivex.testing import TestScheduler

from vmx.notifications import (
    ConfirmationVM,
    Notification,
    NotificationHub,
    NotificationReaction,
    NotificationType,
    NotificationVM,
    NullNotificationHub,
    make_confirm,
)

# Most tests below are async (the hub returns asyncio futures); the two
# enum-shape checks (NOTIF-004, NOTIF-005) are sync and carry no asyncio mark.


# ---------------------------------------------------------------------------
# NOTIF-001 — Post awaitable completes on Resolve
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-001")
async def test_NOTIF_001_post_awaitable_completes_on_resolve() -> None:
    hub = NotificationHub()
    n = Notification(NotificationType.NOTIFICATION, "info")
    task = hub.post(n)
    hub.resolve(n, NotificationReaction.APPROVE)
    assert await task == NotificationReaction.APPROVE


# ---------------------------------------------------------------------------
# NOTIF-002 — Post adds to Pending
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-002")
async def test_NOTIF_002_post_adds_to_pending() -> None:
    hub = NotificationHub()
    last: list[Notification] = []

    def _on_next(snapshot: list[Notification]) -> None:
        last.clear()
        last.extend(snapshot)

    hub.pending.subscribe(on_next=_on_next)
    n = Notification(NotificationType.NOTIFICATION, "info")
    hub.post(n)
    assert n in last


# ---------------------------------------------------------------------------
# NOTIF-003 — Resolve removes from Pending
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-003")
async def test_NOTIF_003_resolve_removes_from_pending() -> None:
    hub = NotificationHub()
    last: list[Notification] = []

    def _on_next(snapshot: list[Notification]) -> None:
        last.clear()
        last.extend(snapshot)

    hub.pending.subscribe(on_next=_on_next)
    n = Notification(NotificationType.NOTIFICATION, "info")
    hub.post(n)
    hub.resolve(n, NotificationReaction.APPROVE)
    assert n not in last


# ---------------------------------------------------------------------------
# NOTIF-004 — NotificationType enum members
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-004")
def test_NOTIF_004_notificationtype_members() -> None:
    assert set(NotificationType) == {
        NotificationType.ERROR,
        NotificationType.NOTIFICATION,
        NotificationType.CONFIRMATION,
    }


# ---------------------------------------------------------------------------
# NOTIF-005 — NotificationReaction enum members
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-005")
def test_NOTIF_005_notificationreaction_members() -> None:
    assert set(NotificationReaction) == {
        NotificationReaction.PENDING,
        NotificationReaction.APPROVE,
        NotificationReaction.REJECT,
    }


# ---------------------------------------------------------------------------
# NOTIF-006 — Resolved task carries the reaction
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-006")
async def test_NOTIF_006_resolved_task_carries_reaction() -> None:
    hub = NotificationHub()
    n = Notification(NotificationType.NOTIFICATION, "info")
    task = hub.post(n)
    hub.resolve(n, NotificationReaction.REJECT)
    assert await task == NotificationReaction.REJECT


# ---------------------------------------------------------------------------
# NOTIF-007 — Confirmation Approve / Reject
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-007")
async def test_NOTIF_007_confirmation_approve_or_reject() -> None:
    hub = NotificationHub()
    n_approve = Notification(NotificationType.CONFIRMATION, "x")
    n_reject = Notification(NotificationType.CONFIRMATION, "y")
    task_approve = hub.post(n_approve)
    task_reject = hub.post(n_reject)
    hub.resolve(n_approve, NotificationReaction.APPROVE)
    hub.resolve(n_reject, NotificationReaction.REJECT)
    assert await task_approve == NotificationReaction.APPROVE
    assert await task_reject == NotificationReaction.REJECT


# ---------------------------------------------------------------------------
# NOTIF-008 — Resolving unknown is no-op
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-008")
async def test_NOTIF_008_resolve_unknown_noop() -> None:
    hub = NotificationHub()
    posted = Notification(NotificationType.CONFIRMATION, "real")
    hub.post(posted)
    snapshots: list[list[Notification]] = []
    hub.pending.subscribe(snapshots.append)

    orphan = Notification(NotificationType.NOTIFICATION, "stray")
    hub.resolve(orphan, NotificationReaction.APPROVE)  # must not raise

    # Catalog And-clause: Pending is unchanged — no new emission beyond the
    # subscription snapshot, which still contains exactly the posted one.
    assert len(snapshots) == 1
    assert snapshots[0] == [posted]


# ---------------------------------------------------------------------------
# NOTIF-009 — NullNotificationHub.post resolves Approve immediately
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-009")
async def test_NOTIF_009_nullhub_post_immediate_approve() -> None:
    hub = NullNotificationHub()
    n = Notification(NotificationType.CONFIRMATION, "x")
    task = hub.post(n)
    assert task.done() is True
    assert await task == NotificationReaction.APPROVE


# ---------------------------------------------------------------------------
# NOTIF-010 — make_confirm helper
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-010")
async def test_NOTIF_010_make_confirm_helper() -> None:
    hub = NotificationHub()
    confirm = make_confirm(hub, "ok?")

    # Auto-approve any pending notification
    sub = hub.pending.subscribe(
        on_next=lambda snapshot: [
            hub.resolve(n, NotificationReaction.APPROVE) for n in list(snapshot)
        ]
    )
    assert await confirm() is True
    sub.dispose()

    sub = hub.pending.subscribe(
        on_next=lambda snapshot: [
            hub.resolve(n, NotificationReaction.REJECT) for n in list(snapshot)
        ]
    )
    assert await confirm() is False
    sub.dispose()


# ---------------------------------------------------------------------------
# NOTIF-011 — NotificationVM opacity decays linearly
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-011")
async def test_NOTIF_011_notification_vm_opacity_decays_linearly() -> None:
    """NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan."""
    scheduler = TestScheduler()
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "hi")
    hub.post(notification)
    sut = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=timedelta(seconds=10),
    )

    assert abs(sut.opacity - 1.0) < 1e-9, "at t=0 opacity is 1.0"

    scheduler.advance_by(5)  # 5 ticks = 5 seconds
    assert abs(sut.opacity - 0.5) < 0.01, f"at t=5s opacity is 0.5, got {sut.opacity}"

    scheduler.advance_by(5)  # total 10 seconds = lifespan
    assert abs(sut.opacity) < 0.01, f"at t=10s opacity is 0.0, got {sut.opacity}"
    sut.dispose()


# ---------------------------------------------------------------------------
# NOTIF-012 — NotificationVM auto-dismisses on expiry
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-012")
async def test_NOTIF_012_notification_vm_auto_dismisses_on_expiry() -> None:
    """NotificationVM auto-dismisses (resolves Approve) at Lifespan expiry."""
    scheduler = TestScheduler()
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "auto")
    task = hub.post(notification)
    sut = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=timedelta(seconds=10),
    )

    assert not sut.is_resolved, "not resolved at t=0"

    scheduler.advance_by(10)  # advance to lifespan

    assert sut.is_resolved, "auto-dismissed at lifespan expiry"
    assert await task == NotificationReaction.APPROVE, "hub task resolved with Approve"
    sut.dispose()


# ---------------------------------------------------------------------------
# NOTIF-013 — ConfirmationVM approve + reject commands
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-013")
async def test_NOTIF_013_confirmation_vm_approve_and_reject_commands() -> None:
    """ConfirmationVM exposes approve_command + reject_command resolving correctly."""
    scheduler = TestScheduler()

    # ApproveCommand resolves with APPROVE
    hub_a = NotificationHub()
    n_a = Notification(NotificationType.CONFIRMATION, "approve me")
    task_a = hub_a.post(n_a)
    sut_a = ConfirmationVM(notification=n_a, hub=hub_a, scheduler=scheduler)
    sut_a.approve_command.execute()
    assert sut_a.is_resolved
    assert await task_a == NotificationReaction.APPROVE
    sut_a.dispose()

    # RejectCommand resolves with REJECT
    hub_r = NotificationHub()
    n_r = Notification(NotificationType.CONFIRMATION, "reject me")
    task_r = hub_r.post(n_r)
    sut_r = ConfirmationVM(notification=n_r, hub=hub_r, scheduler=scheduler)
    sut_r.reject_command.execute()
    assert sut_r.is_resolved
    assert await task_r == NotificationReaction.REJECT
    sut_r.dispose()


# ---------------------------------------------------------------------------
# NOTIF-014 — Manual DismissCommand cancels the timer
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-014")
async def test_NOTIF_014_manual_dismiss_cancels_timer() -> None:
    """Manual dismiss_command cancels the timer; subsequent ticks no-op."""
    scheduler = TestScheduler()
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "dismiss me")
    hub.post(notification)
    sut = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=timedelta(seconds=10),
    )

    # Dismiss manually at t=0
    sut.dismiss_command.execute()
    assert sut.is_resolved, "resolved by manual dismiss"

    # Advance past lifespan — timer must not double-resolve
    scheduler.advance_by(20)  # well past lifespan

    # Still resolved (idempotent), notification is out of pending
    assert sut.is_resolved
    pending_items: list[Notification] = []
    hub.pending.subscribe(on_next=lambda lst: pending_items.extend(lst))
    assert notification not in pending_items, "notification removed from pending on dismiss"
    sut.dispose()


# ---------------------------------------------------------------------------
# NOTIF-015 — Hub Resolve propagates to VM IsResolved
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-015")
async def test_NOTIF_015_hub_resolve_propagates_to_vm_is_resolved() -> None:
    """Hub-side resolve() propagates to VM is_resolved state."""
    scheduler = TestScheduler()
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "hub resolves")
    hub.post(notification)
    sut = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=timedelta(seconds=60),
    )

    assert not sut.is_resolved, "not resolved yet"

    # External resolve via hub
    hub.resolve(notification, NotificationReaction.APPROVE)

    assert sut.is_resolved, "is_resolved propagated from hub resolve"

    # Advance past lifespan — timer must not re-fire
    scheduler.advance_by(60)
    assert sut.is_resolved, "still resolved after timer advance"
    sut.dispose()


# ---------------------------------------------------------------------------
# NOTIF-016 — Deterministic behavior under TestScheduler / fake clock
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-016")
async def test_NOTIF_016_deterministic_under_test_scheduler() -> None:
    """Deterministic behavior under injected TestScheduler / fake clock."""
    scheduler = TestScheduler()
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "tick")
    hub.post(notification)
    sut = NotificationVM(
        notification=notification,
        hub=hub,
        scheduler=scheduler,
        lifespan=timedelta(seconds=10),
    )

    # t=0: opacity 1.0, not resolved
    assert abs(sut.opacity - 1.0) < 1e-9
    assert not sut.is_resolved

    # t=5s: opacity 0.5
    scheduler.advance_by(5)
    assert abs(sut.opacity - 0.5) < 0.01
    assert not sut.is_resolved

    # t=10s: auto-dismissed exactly at lifespan
    scheduler.advance_by(5)
    assert sut.is_resolved, "auto-dismissed exactly at lifespan"
    assert abs(sut.opacity) < 0.01

    # No double-resolve: advancing further does nothing
    scheduler.advance_by(100)
    assert sut.is_resolved
    sut.dispose()


# ---------------------------------------------------------------------------
# resolve() thread-safety (unit; not a conformance ID)
# ---------------------------------------------------------------------------


async def test_resolve_is_thread_safe() -> None:
    """resolve() may be called from a thread other than the event loop's.

    Regression test: previously resolve() called asyncio.Future.set_result
    directly, which is not thread-safe. The fix routes the call through
    loop.call_soon_threadsafe; this test exercises the cross-thread path.
    """
    import threading

    hub = NotificationHub()
    n = Notification(NotificationType.NOTIFICATION, "info")
    future = hub.post(n)

    def worker() -> None:
        hub.resolve(n, NotificationReaction.APPROVE)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    result = await future
    t.join(timeout=1.0)
    assert result == NotificationReaction.APPROVE


# ---------------------------------------------------------------------------
# Concurrent hub delivery
# ---------------------------------------------------------------------------


def test_opposing_notification_hub_callbacks_do_not_deadlock() -> None:
    first = NotificationHub()
    second = NotificationHub()
    first_notification = Notification(NotificationType.NOTIFICATION, "first")
    second_notification = Notification(NotificationType.NOTIFICATION, "second")
    callbacks_ready = Barrier(2)

    def on_first(snapshot: list[Notification]) -> None:
        if first_notification in snapshot:
            callbacks_ready.wait(timeout=1)
            second.resolve(second_notification, NotificationReaction.APPROVE)

    def on_second(snapshot: list[Notification]) -> None:
        if second_notification in snapshot:
            callbacks_ready.wait(timeout=1)
            first.resolve(first_notification, NotificationReaction.APPROVE)

    first.pending.subscribe(on_first)
    second.pending.subscribe(on_second)
    senders = [
        Thread(target=lambda: asyncio.run(_post_once(first, first_notification)), daemon=True),
        Thread(target=lambda: asyncio.run(_post_once(second, second_notification)), daemon=True),
    ]
    for sender in senders:
        sender.start()
    for sender in senders:
        sender.join(timeout=1)

    assert all(not sender.is_alive() for sender in senders)


async def _post_once(hub: NotificationHub, notification: Notification) -> None:
    hub.post(notification)


# NOTIF-017 — Hub dispose resolves in-flight waiters with Pending
# ---------------------------------------------------------------------------


@pytest.mark.conformance("NOTIF-017")
async def test_NOTIF_017_dispose_resolves_inflight_waiters_with_pending() -> None:
    hub = NotificationHub()
    completed: list[bool] = []
    hub.pending.subscribe(on_completed=lambda: completed.append(True))
    task = hub.post(Notification(NotificationType.CONFIRMATION, "in-flight"))

    hub.dispose()

    assert await task == NotificationReaction.PENDING
    assert completed == [True], "pending observable completes on dispose"

    # Subsequent post resolves immediately with PENDING and does not enqueue.
    late = hub.post(Notification(NotificationType.NOTIFICATION, "late"))
    assert late.done()
    assert late.result() == NotificationReaction.PENDING

    # Subsequent resolve is a no-op; second dispose is a no-op.
    hub.resolve(Notification(NotificationType.NOTIFICATION, "ghost"), NotificationReaction.APPROVE)
    hub.dispose()

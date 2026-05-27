"""Conformance tests: NOTIF-001..010 — notification sub-package.

Per spec/16-notifications.md and ADR-0013.
"""

from __future__ import annotations

import pytest

from vmx.notifications import (
    Notification,
    NotificationHub,
    NotificationReaction,
    NotificationType,
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
    orphan = Notification(NotificationType.NOTIFICATION, "stray")
    hub.resolve(orphan, NotificationReaction.APPROVE)  # must not raise


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

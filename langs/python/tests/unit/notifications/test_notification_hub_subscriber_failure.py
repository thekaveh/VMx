"""A raising ``pending`` subscriber must not strand removed waiters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from vmx.notifications import (
    Notification,
    NotificationHub,
    NotificationReaction,
    NotificationType,
)


class _SubscriberError(Exception):
    pass


def _raise_when_armed(armed: list[bool]) -> Callable[[object], None]:
    def on_next(_: object) -> None:
        if armed[0]:
            raise _SubscriberError

    return on_next


async def test_resolve_completes_the_waiter_when_a_pending_subscriber_raises() -> None:
    hub = NotificationHub()
    notification = Notification(NotificationType.NOTIFICATION, "saved")
    post = hub.post(notification)
    armed = [False]
    # ``pending`` replays its snapshot on subscribe; raise only on resolve's.
    subscription = hub.pending.subscribe(_raise_when_armed(armed))
    armed[0] = True

    with pytest.raises(_SubscriberError):
        hub.resolve(notification, NotificationReaction.APPROVE)

    assert await asyncio.wait_for(post, timeout=1) is NotificationReaction.APPROVE
    subscription.dispose()


async def test_dispose_completes_waiters_when_a_pending_subscriber_raises() -> None:
    hub = NotificationHub()
    post = hub.post(Notification(NotificationType.NOTIFICATION, "saved"))

    def on_completed() -> None:
        raise _SubscriberError

    hub.pending.subscribe(on_completed=on_completed)

    with pytest.raises(_SubscriberError):
        hub.dispose()

    assert await asyncio.wait_for(post, timeout=1) is NotificationReaction.PENDING


async def test_pending_completes_when_a_subscriber_disposes_the_hub_and_then_raises() -> None:
    hub = NotificationHub()
    armed = [False]
    completed: list[None] = []

    def dispose_then_raise(_: object) -> None:
        if not armed[0]:
            return
        armed[0] = False
        hub.dispose()
        raise _SubscriberError

    failing = hub.pending.subscribe(dispose_then_raise)
    observer = hub.pending.subscribe(on_completed=lambda: completed.append(None))
    armed[0] = True

    with pytest.raises(_SubscriberError):
        hub.post(Notification(NotificationType.NOTIFICATION, "saved"))

    assert completed == [None]
    failing.dispose()
    observer.dispose()

"""NullNotificationHub — null-object variant. See ADR-0017 and ADR-0013."""

from __future__ import annotations

import asyncio

import reactivex as rx
from reactivex import Observable

from vmx.notifications.notification import Notification
from vmx.notifications.notification_reaction import NotificationReaction


class NullNotificationHub:
    """Null-object hub: post resolves Approve immediately; resolve is a no-op."""

    def __init__(self) -> None:
        self._pending: Observable[list[Notification]] = rx.from_iterable([[]])

    @property
    def pending(self) -> Observable[list[Notification]]:
        return self._pending

    def post(self, notification: Notification) -> asyncio.Future[NotificationReaction]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[NotificationReaction] = loop.create_future()
        future.set_result(NotificationReaction.APPROVE)
        return future

    def resolve(self, notification: Notification, reaction: NotificationReaction) -> None:
        return None


NULL_NOTIFICATION_HUB: NullNotificationHub = NullNotificationHub()
"""Shared singleton."""

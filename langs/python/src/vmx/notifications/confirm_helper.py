"""Bridge helper: turns an INotificationHub Confirmation flow into an async
predicate suitable for ConfirmationDecoratorCommand.

See spec/16-notifications.md §"Bridging command decorators".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from vmx.notifications.notification import Notification
from vmx.notifications.notification_hub import INotificationHub
from vmx.notifications.notification_reaction import NotificationReaction
from vmx.notifications.notification_type import NotificationType


def make_confirm(hub: INotificationHub, prompt: str) -> Callable[[], Awaitable[bool]]:
    """Returns a confirm-delegate that posts a Confirmation and returns True iff Approve."""

    async def _confirm() -> bool:
        notification = Notification(NotificationType.CONFIRMATION, prompt)
        reaction = await hub.post(notification)
        return reaction == NotificationReaction.APPROVE

    return _confirm

"""VMx notification / confirmation hub. See spec/16-notifications.md and ADR-0013.

This is an opt-in sub-package: it is shipped inside the ``vmx`` distribution
but is NOT imported by ``import vmx``. Consumers must ``import vmx.notifications``
(or ``from vmx.notifications import ...``) to use it.
"""

from __future__ import annotations

from vmx.notifications.confirm_helper import make_confirm
from vmx.notifications.confirmation_vm import ConfirmationVM
from vmx.notifications.notification import Notification
from vmx.notifications.notification_hub import INotificationHub, NotificationHub
from vmx.notifications.notification_reaction import NotificationReaction
from vmx.notifications.notification_type import NotificationType
from vmx.notifications.notification_vm import NotificationVM
from vmx.notifications.null_notification_hub import (
    NULL_NOTIFICATION_HUB,
    NullNotificationHub,
)

__all__ = [
    "NULL_NOTIFICATION_HUB",
    "ConfirmationVM",
    "INotificationHub",
    "Notification",
    "NotificationHub",
    "NotificationReaction",
    "NotificationType",
    "NotificationVM",
    "NullNotificationHub",
    "make_confirm",
]

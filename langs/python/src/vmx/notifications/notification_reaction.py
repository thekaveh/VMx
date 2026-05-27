"""NotificationReaction enum. See spec/16-notifications.md."""

from __future__ import annotations

from enum import Enum, auto


class NotificationReaction(Enum):
    """User response to a notification."""

    PENDING = auto()
    APPROVE = auto()
    REJECT = auto()

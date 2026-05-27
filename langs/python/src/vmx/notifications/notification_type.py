"""NotificationType enum. See spec/16-notifications.md."""

from __future__ import annotations

from enum import Enum, auto


class NotificationType(Enum):
    """Classification of a notification."""

    ERROR = auto()
    NOTIFICATION = auto()
    CONFIRMATION = auto()

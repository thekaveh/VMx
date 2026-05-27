"""Notification value class. See spec/16-notifications.md."""

from __future__ import annotations

from vmx.notifications.notification_type import NotificationType


class Notification:
    """Immutable notification value (identity-distinct)."""

    __slots__ = ("_message", "_type")

    def __init__(self, type: NotificationType, message: str) -> None:
        self._type = type
        self._message = message

    @property
    def type(self) -> NotificationType:
        return self._type

    @property
    def message(self) -> str:
        return self._message

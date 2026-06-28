"""ConfirmationVM — render-side ViewModel for a confirmation Notification.

See spec/16-notifications.md §ConfirmationVM and ADR-0031.
"""

from __future__ import annotations

from datetime import timedelta

from reactivex.abc import SchedulerBase

from vmx.commands.relay_command import RelayCommand
from vmx.notifications.notification import Notification
from vmx.notifications.notification_hub import INotificationHub
from vmx.notifications.notification_reaction import NotificationReaction
from vmx.notifications.notification_vm import NotificationVM

_DEFAULT_LIFESPAN = timedelta(seconds=300)


class ConfirmationVM(NotificationVM):
    """Render-side ViewModel for a confirmation :class:`Notification`.

    Extends :class:`NotificationVM` with explicit :attr:`approve_command` and
    :attr:`reject_command`.  Default lifespan is 300 seconds.

    Unlike :class:`NotificationVM`, ``ConfirmationVM`` does **not** auto-resolve
    on lifespan expiry — timeout means "user did not decide".

    Parameters
    ----------
    notification:
        The confirmation notification to render.
    hub:
        Hub used to resolve the notification.
    scheduler:
        Scheduler for time advancement.
    lifespan:
        Optional override for the default 300-second lifespan.
    tick_interval:
        Optional decay-tick cadence forwarded to :class:`NotificationVM`
        (VMX-135) so a binding view can repaint the fade.
    """

    def __init__(
        self,
        notification: Notification,
        hub: INotificationHub,
        scheduler: SchedulerBase,
        lifespan: timedelta | None = None,
        tick_interval: timedelta | None = None,
    ) -> None:
        super().__init__(
            notification,
            hub,
            scheduler,
            lifespan if lifespan is not None else _DEFAULT_LIFESPAN,
            tick_interval,
        )

        self._approve_command = (
            RelayCommand.builder()
            .task(lambda: self._resolve_with(NotificationReaction.APPROVE))
            .build()
        )
        self._reject_command = (
            RelayCommand.builder()
            .task(lambda: self._resolve_with(NotificationReaction.REJECT))
            .build()
        )

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def approve_command(self) -> RelayCommand:
        """Command that resolves with :attr:`NotificationReaction.APPROVE`."""
        return self._approve_command

    @property
    def reject_command(self) -> RelayCommand:
        """Command that resolves with :attr:`NotificationReaction.REJECT`."""
        return self._reject_command

    # ── Override ──────────────────────────────────────────────────────────────

    def _on_expire(self) -> None:
        """ConfirmationVM does NOT auto-resolve on lifespan expiry.

        Timeout means "user did not decide"; the notification remains pending.
        """
        # Intentional no-op.

    def dispose(self) -> None:
        """Cancel commands and delegate to parent dispose."""
        self._approve_command.dispose()
        self._reject_command.dispose()
        super().dispose()

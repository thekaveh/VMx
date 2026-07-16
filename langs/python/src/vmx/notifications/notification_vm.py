"""NotificationVM — render-side ViewModel for a Notification.

See spec/16-notifications.md §NotificationVM and ADR-0031.
"""

from __future__ import annotations

from datetime import timedelta

import reactivex as rx
from reactivex import operators as ops
from reactivex.abc import DisposableBase, SchedulerBase
from reactivex.subject import Subject

from vmx.commands.relay_command import RelayCommand
from vmx.notifications.notification import Notification
from vmx.notifications.notification_hub import INotificationHub
from vmx.notifications.notification_reaction import NotificationReaction

_DEFAULT_LIFESPAN = timedelta(seconds=60)


class NotificationVM:
    """Render-side ViewModel for a :class:`Notification`.

    Exposes UI-bindable state:

    - :attr:`notification` — the consumed datum
    - :attr:`lifespan` — configured lifespan (default 60 s)
    - :attr:`remaining_time` — decays toward ``timedelta(0)`` via *scheduler*
    - :attr:`opacity` — derived ``remaining_time / lifespan`` in range [0.0, 1.0]
    - :attr:`is_resolved` — ``True`` once resolved
    - :attr:`dismiss_command` — resolves with Approve and cancels the timer
    - :attr:`property_changed` — INPC-style change-notification stream (VMX-135)

    Auto-dismiss: when ``remaining_time`` reaches zero the VM resolves the
    notification with :attr:`NotificationReaction.APPROVE`.  Use
    :class:`ConfirmationVM` if you want explicit user action instead.

    Change-notification (VMX-079/135): :attr:`property_changed` emits property
    names so a binding view can repaint.  ``is_resolved`` always emits on
    resolution; when *tick_interval* is supplied, ``remaining_time``/``opacity``
    emit periodically while the notification fades.  Without a tick interval the
    two time-varying properties stay poll-only (no recurring scheduler work),
    preserving the prior behaviour.

    Parameters
    ----------
    notification:
        The notification to render.
    hub:
        Hub used to resolve the notification.
    scheduler:
        Scheduler for time advancement.  Pass a :class:`~reactivex.testing.TestScheduler`
        in tests for deterministic virtual-time control.
    lifespan:
        Optional override for the default 60-second lifespan.
    tick_interval:
        Optional cadence at which ``remaining_time``/``opacity`` raise
        :attr:`property_changed` while the notification fades (VMX-135).  When
        ``None`` (default) the two properties are poll-only.
    """

    def __init__(
        self,
        notification: Notification,
        hub: INotificationHub,
        scheduler: SchedulerBase,
        lifespan: timedelta | None = None,
        tick_interval: timedelta | None = None,
    ) -> None:
        self._notification = notification
        self._hub = hub
        self._scheduler = scheduler
        self._lifespan: timedelta = lifespan if lifespan is not None else _DEFAULT_LIFESPAN
        self._tick_interval: timedelta = (
            tick_interval if tick_interval is not None else timedelta(0)
        )
        self._emits_decay_ticks: bool = self._tick_interval > timedelta(
            0
        ) and self._lifespan > timedelta(0)
        self._start = scheduler.now
        self._is_resolved = False

        # INPC-style change-notification stream (VMX-079/135).
        self._property_changed_subject: Subject[str] = Subject()
        self._tick_sub: DisposableBase | None = None
        self._timer_sub: DisposableBase | None = None
        self._dismiss_command = RelayCommand.builder().task(self._dismiss).build()
        self._pending_sub: DisposableBase | None = None
        self._disposed = False

        # Subscribe to hub Pending: detect external resolution.
        # SkipWhile: skip while the notification is NOT yet seen in the list.
        #   (With BehaviorSubject this is a no-op when notification was already posted.)
        # Skip(1): drop the first emission where notification IS present.
        # Filter/Take(1): fire once on the first emission where it has disappeared.
        _notif = notification  # capture for lambda closures

        def _is_not_present(lst: object) -> bool:
            return _notif not in lst  # type: ignore[operator]

        def _is_not_yet_present(lst: object) -> bool:
            return _notif not in lst  # type: ignore[operator]

        self._pending_sub = hub.pending.pipe(
            ops.skip_while(_is_not_yet_present),
            ops.skip(1),
            ops.filter(_is_not_present),
            ops.take(1),
        ).subscribe(on_next=lambda _: self._notify_external_resolve())

        timer = scheduler.schedule_relative(self._lifespan, lambda sched, _state: self._on_expire())
        if self._disposed or self._is_resolved:
            timer.dispose()
        else:
            self._timer_sub = timer

        # VMX-135: when a tick cadence is requested, periodically raise
        # property_changed for the decaying state so a bound view repaints the
        # fade. The recurring action self-terminates once the notification
        # resolves, is disposed, or the decay completes (remaining_time hits 0).
        if self._emits_decay_ticks:
            self._schedule_decay_tick()

    # ── Public properties ─────────────────────────────────────────────────────

    @property
    def property_changed(self) -> rx.Observable[str]:
        """INPC-style change-notification stream (VMX-079/135).

        Emits the name of each property whose value changed (``is_resolved``,
        and — when a tick interval is configured — ``remaining_time``/``opacity``
        as the notification fades).
        """
        return self._property_changed_subject.pipe(ops.as_observable())

    @property
    def notification(self) -> Notification:
        """The notification datum consumed by this VM."""
        return self._notification

    @property
    def lifespan(self) -> timedelta:
        """Configured lifespan (default 60 s)."""
        return self._lifespan

    @property
    def remaining_time(self) -> timedelta:
        """Time remaining until auto-dismiss. Decays to ``timedelta(0)``."""
        elapsed = self._scheduler.now - self._start
        remaining = self._lifespan - elapsed
        return remaining if remaining > timedelta(0) else timedelta(0)

    @property
    def opacity(self) -> float:
        """Linear decay from 1.0 to 0.0 over ``lifespan``.

        Derived as ``remaining_time / lifespan``. Range [0.0, 1.0].
        """
        lifespan_s = self._lifespan.total_seconds()
        if lifespan_s <= 0.0:
            return 0.0
        return self.remaining_time.total_seconds() / lifespan_s

    @property
    def is_resolved(self) -> bool:
        """True once the notification has been resolved (manually or by timer)."""
        return self._is_resolved

    @property
    def dismiss_command(self) -> RelayCommand:
        """Command that resolves with Approve and cancels the lifespan timer."""
        return self._dismiss_command

    # ── Public methods ────────────────────────────────────────────────────────

    def notify_external_resolve(self) -> None:
        """Notify the VM that the hub has resolved the notification externally.

        Sets :attr:`is_resolved` and cancels the timer.
        """
        self._notify_external_resolve()

    def dispose(self) -> None:
        """Cancel the timer, pending subscription, and command (idempotent)."""
        if self._disposed:
            return
        self._disposed = True
        self._cancel_timers()
        if self._pending_sub is not None:
            self._pending_sub.dispose()
            self._pending_sub = None
        self._dismiss_command.dispose()
        self._property_changed_subject.on_completed()
        self._property_changed_subject.dispose()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _cancel_timers(self) -> None:
        """Dispose the lifespan timer and the decay-tick subscription."""
        if self._timer_sub is not None:
            self._timer_sub.dispose()
            self._timer_sub = None
        if self._tick_sub is not None:
            self._tick_sub.dispose()
            self._tick_sub = None

    def _schedule_decay_tick(self) -> None:
        """Schedule the next periodic decay tick (VMX-135)."""
        self._tick_sub = self._scheduler.schedule_relative(
            self._tick_interval, lambda sched, _state: self._decay_tick()
        )

    def _decay_tick(self) -> None:
        """Raise property_changed for the decaying state and reschedule.

        Self-terminates once the notification resolves, is disposed, or the
        decay completes (``remaining_time`` hits zero).
        """
        if self._disposed or self._is_resolved:
            return
        self._raise_property_changed("remaining_time")
        self._raise_property_changed("opacity")
        if self.remaining_time > timedelta(0):
            self._schedule_decay_tick()

    def _raise_property_changed(self, property_name: str) -> None:
        """Emit *property_name* on the change-notification stream (VMX-135)."""
        if not self._disposed:
            self._property_changed_subject.on_next(property_name)

    def _raise_resolved_changes(self) -> None:
        """Raise property_changed for the resolved + decay state (VMX-135)."""
        self._raise_property_changed("is_resolved")
        self._raise_property_changed("remaining_time")
        self._raise_property_changed("opacity")

    def _on_expire(self) -> None:
        """Called when the lifespan timer fires.

        Default: auto-dismiss with Approve.
        ``ConfirmationVM`` overrides to suppress auto-dismiss.
        """
        self._dismiss()

    def _dismiss(self) -> None:
        """Resolve with Approve and cancel the timer. Idempotent."""
        if self._is_resolved:
            return
        self._is_resolved = True
        self._cancel_timers()
        self._hub.resolve(self._notification, NotificationReaction.APPROVE)
        self._raise_resolved_changes()

    def _resolve_with(self, reaction: NotificationReaction) -> None:
        """Resolve with the given reaction and cancel the timer. Idempotent."""
        if self._is_resolved:
            return
        self._is_resolved = True
        self._cancel_timers()
        self._hub.resolve(self._notification, reaction)
        self._raise_resolved_changes()

    def _notify_external_resolve(self) -> None:
        """Handle external hub resolution: set is_resolved + cancel timer."""
        if self._is_resolved:
            return
        self._is_resolved = True
        self._cancel_timers()
        self._raise_resolved_changes()

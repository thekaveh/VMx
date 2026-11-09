"""NotificationHub dispose and late ``pending`` subscriptions (ADR-0197).

The conformance check is NOTIF-020 in tests/conformance/test_notifications.py.
"""

from __future__ import annotations

from vmx.notifications import Notification, NotificationHub, NotificationType


async def test_subscribe_after_reentrant_dispose_receives_completion_only() -> None:
    hub = NotificationHub()
    hub.post(Notification(NotificationType.NOTIFICATION, "posted"))
    late_values: list[list[Notification]] = []
    late_errors: list[Exception] = []
    late_completions: list[bool] = []
    outer_completions: list[bool] = []
    reentered: list[bool] = []

    def on_next(_snapshot: list[Notification]) -> None:
        if reentered:
            return
        reentered.append(True)
        hub.dispose()
        hub.pending.subscribe(
            on_next=late_values.append,
            on_error=late_errors.append,
            on_completed=lambda: late_completions.append(True),
        )

    hub.pending.subscribe(on_next=on_next, on_completed=lambda: outer_completions.append(True))

    assert reentered == [True]
    assert late_values == []
    assert late_errors == []
    assert late_completions == [True]
    assert outer_completions == [True]


async def test_subscribers_before_dispose_get_one_completion_and_no_value() -> None:
    hub = NotificationHub()
    hub.post(Notification(NotificationType.NOTIFICATION, "posted"))
    values: list[list[Notification]] = []
    completions: list[bool] = []
    hub.pending.subscribe(on_next=values.append, on_completed=lambda: completions.append(True))
    before = len(values)

    hub.dispose()
    hub.dispose()

    assert len(values) == before
    assert completions == [True]

"""NotificationHub — async notification/confirmation hub.

See spec/16-notifications.md and ADR-0013.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Protocol, runtime_checkable

from reactivex import Observable
from reactivex.subject import BehaviorSubject

from vmx.notifications.notification import Notification
from vmx.notifications.notification_reaction import NotificationReaction


def _complete_future_if_pending(
    future: asyncio.Future[NotificationReaction],
    reaction: NotificationReaction,
) -> None:
    """Set ``future.set_result(reaction)`` iff the future is not already done.

    Routed via ``loop.call_soon_threadsafe`` from :meth:`NotificationHub.resolve`
    so the actual ``set_result`` call always runs on the future's owning event
    loop thread (``asyncio.Future`` is not thread-safe).
    """
    if not future.done():
        future.set_result(reaction)


@runtime_checkable
class INotificationHub(Protocol):
    """Public contract for a notification hub."""

    @property
    def pending(self) -> Observable[list[Notification]]: ...

    def post(self, notification: Notification) -> asyncio.Future[NotificationReaction]:
        """Posts a notification; returns a future that completes on resolve."""
        ...

    def resolve(self, notification: Notification, reaction: NotificationReaction) -> None:
        """Resolves a pending notification (no-op if not in pending list)."""
        ...


class NotificationHub:
    """Default INotificationHub implementation backed by asyncio.Future.

    Thread-safety: :meth:`post` must be called from within a running asyncio
    event loop (the returned future is bound to that loop). :meth:`resolve`
    may be called from any thread; the future's ``set_result`` is scheduled
    on the owning loop via ``call_soon_threadsafe``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[Notification] = []
        self._waiters: dict[Notification, asyncio.Future[NotificationReaction]] = {}
        self._pending_subject: BehaviorSubject[list[Notification]] = BehaviorSubject([])

    @property
    def pending(self) -> Observable[list[Notification]]:
        return self._pending_subject

    def post(self, notification: Notification) -> asyncio.Future[NotificationReaction]:
        """Post a notification and return a future that resolves on Resolve.

        MUST be called from within a running asyncio event loop; raises
        :class:`RuntimeError` otherwise. The returned future is created on
        the running loop and is intended to be awaited from async code.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[NotificationReaction] = loop.create_future()
        with self._lock:
            self._pending.append(notification)
            self._waiters[notification] = future
            snapshot = list(self._pending)
        self._pending_subject.on_next(snapshot)
        return future

    def resolve(self, notification: Notification, reaction: NotificationReaction) -> None:
        with self._lock:
            future = self._waiters.pop(notification, None)
            if future is None:
                return
            self._pending.remove(notification)
            snapshot = list(self._pending)
        self._pending_subject.on_next(snapshot)
        if future.done():
            return
        # asyncio.Future.set_result is not thread-safe — route through the
        # future's owning loop so resolve() may be invoked from any thread.
        # (The hub is typically shared between the UI/event-loop thread and
        # background-worker threads that complete the underlying interaction.)
        loop = future.get_loop()
        loop.call_soon_threadsafe(_complete_future_if_pending, future, reaction)

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
        # RLock, not Lock: pending snapshots are emitted while holding the
        # lock (NOTIF-017 ordering discipline), and a subscriber handler may
        # synchronously call back into post/resolve on the same thread —
        # mirroring C#'s reentrant Monitor.
        self._lock = threading.RLock()
        self._pending: list[Notification] = []
        self._waiters: dict[Notification, asyncio.Future[NotificationReaction]] = {}
        self._pending_subject: BehaviorSubject[list[Notification]] = BehaviorSubject([])
        self._disposed = False

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
            # Post after dispose resolves PENDING and does not enqueue,
            # matching dispose()'s shutdown semantics (NOTIF-017).
            if self._disposed:
                future.set_result(NotificationReaction.PENDING)
                return future
            self._pending.append(notification)
            self._waiters[notification] = future
            # Emit inside the lock (NOTIF-017 discipline, mirroring the C#
            # hub): emitting outside raced dispose()'s subject completion and
            # let concurrent posts publish snapshots out of order.
            self._pending_subject.on_next(list(self._pending))
        return future

    def resolve(self, notification: Notification, reaction: NotificationReaction) -> None:
        with self._lock:
            future = self._waiters.pop(notification, None)
            if future is None:
                return
            self._pending.remove(notification)
            self._pending_subject.on_next(list(self._pending))
        if future.done():
            return
        # asyncio.Future.set_result is not thread-safe — route through the
        # future's owning loop so resolve() may be invoked from any thread.
        # (The hub is typically shared between the UI/event-loop thread and
        # background-worker threads that complete the underlying interaction.)
        loop = future.get_loop()
        loop.call_soon_threadsafe(_complete_future_if_pending, future, reaction)

    def dispose(self) -> None:
        """Resolve in-flight waiters with ``PENDING`` and complete ``pending``.

        Idempotent (NOTIF-017). Mirrors the C# hub's shutdown semantics:
        subsequent :meth:`post` calls resolve immediately with ``PENDING``
        without enqueueing, and subsequent :meth:`resolve` calls are no-ops.
        """
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
            waiters = list(self._waiters.values())
            self._waiters.clear()
            self._pending.clear()
            self._pending_subject.on_completed()
            self._pending_subject.dispose()
        for future in waiters:
            future.get_loop().call_soon_threadsafe(
                _complete_future_if_pending, future, NotificationReaction.PENDING
            )

"""VM-backed modal result primitive."""

from __future__ import annotations

import asyncio
import threading
from typing import Generic, TypeVar, cast

T = TypeVar("T")


def _complete_waiter(future: asyncio.Future[None]) -> None:
    """Wake ``future`` on its owning loop; ``set_result`` is not thread-safe."""
    try:
        future.get_loop().call_soon_threadsafe(_set_if_pending, future)
    except RuntimeError:
        # The waiter's loop is already closed; nothing is left to wake.
        pass


def _set_if_pending(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


class ModalVM(Generic[T]):
    """Small result-bearing modal VM base.

    Hosts call :meth:`dismiss` with the selected result. Consumers can await
    :meth:`wait_result`. Disposing resolves the modal with its cancellation
    result so waiters never hang.

    :meth:`dismiss` and :meth:`dispose` can run on any thread. The first result
    is claimed under a lock, and each waiter is woken on its own event loop
    (#1323).
    """

    def __init__(self, cancellation_result: T) -> None:
        self._cancellation_result = cancellation_result
        self._result: T | None = None
        self._is_dismissed = False
        self._lock = threading.Lock()
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def cancellation_result(self) -> T:
        """Result used when the modal is cancelled or disposed."""
        return self._cancellation_result

    @property
    def result(self) -> T | None:
        """Dismissal result, or ``None`` before dismissal."""
        return self._result

    @property
    def is_dismissed(self) -> bool:
        """``True`` after dismissal or disposal."""
        return self._is_dismissed

    def dismiss(self, result: T) -> None:
        """Complete the modal with ``result``. Idempotent; the first result wins."""
        with self._lock:
            if self._is_dismissed:
                return
            self._result = result
            self._is_dismissed = True
            waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            _complete_waiter(waiter)

    def dispose(self) -> None:
        """Cancel the modal with :attr:`cancellation_result`. Idempotent."""
        self.dismiss(self._cancellation_result)

    async def wait_result(self) -> T:
        """Wait for dismissal and return the resolved result."""
        with self._lock:
            if self._is_dismissed:
                return cast(T, self._result)
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
        try:
            await waiter
        finally:
            with self._lock:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
        return cast(T, self._result)

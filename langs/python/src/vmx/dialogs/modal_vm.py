"""VM-backed modal result primitive."""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class ModalVM(Generic[T]):
    """Small result-bearing modal VM base.

    Hosts call :meth:`dismiss` with the selected result. Consumers can await
    :meth:`wait_result`. Disposing resolves the modal with its cancellation
    result so waiters never hang.
    """

    def __init__(self, cancellation_result: T) -> None:
        self._cancellation_result = cancellation_result
        self._result: T | None = None
        self._is_dismissed = False
        self._event = asyncio.Event()

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
        """Complete the modal with ``result``. Idempotent."""
        if self._is_dismissed:
            return
        self._result = result
        self._is_dismissed = True
        self._event.set()

    def dispose(self) -> None:
        """Cancel the modal with :attr:`cancellation_result`. Idempotent."""
        self.dismiss(self._cancellation_result)

    async def wait_result(self) -> T:
        """Wait for dismissal and return the resolved result."""
        await self._event.wait()
        return self._result  # type: ignore[return-value]

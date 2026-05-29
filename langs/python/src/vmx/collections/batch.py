"""Ref-counted batch-update token used by CompositeVM and GroupVM.

See spec/06-composite-vm.md §Batch updates (spec v1.1).
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol


class _BatchHost(Protocol):
    def _exit_batch(self) -> None: ...


class BatchUpdateHandle:
    """Returned by ``CompositeVM.batch_update()`` / ``GroupVM.batch_update()``.

    Usable as a context manager (``with composite.batch_update():``) or as an
    explicit disposable (``handle.dispose()``).
    """

    __slots__ = ("_disposed", "_host")

    def __init__(self, host: _BatchHost) -> None:
        self._host = host
        self._disposed = False

    def dispose(self) -> None:
        """Exit the batch. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        self._host._exit_batch()

    def __enter__(self) -> BatchUpdateHandle:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.dispose()

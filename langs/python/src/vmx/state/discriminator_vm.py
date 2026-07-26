"""DiscriminatorVM — owns one active key with modal precedence helpers."""

from __future__ import annotations

from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

TKey = TypeVar("TKey")


class DiscriminatorVM(Generic[TKey]):
    """Small state VM for a single active discriminator key."""

    def __init__(self, initial: TKey) -> None:
        self._active_key = initial
        self._modal_stack: list[TKey] = []
        self._active_changed: Subject[TKey] = Subject()
        self._disposed = False

    @property
    def active_key(self) -> TKey:
        """Currently active key."""
        return self._active_key

    @property
    def active_changed(self) -> rx.Observable[TKey]:
        """Hot observable of active-key changes."""
        return self._active_changed.pipe(ops.as_observable())

    @property
    def modal_depth(self) -> int:
        """Number of saved modal frames."""
        return len(self._modal_stack)

    def is_active(self, key: TKey) -> bool:
        """Return ``True`` when ``key`` is the active key."""
        return self._active_key == key

    def set_active_key(self, key: TKey) -> None:
        """Set the active key and abandon any saved modal history."""
        if self._disposed:
            return
        self._modal_stack.clear()
        self._set_active_key_preserving_modals(key)

    def _set_active_key_preserving_modals(self, key: TKey) -> None:
        if key == self._active_key:
            return
        self._active_key = key
        self._active_changed.on_next(key)

    def modal_open(self, modal_key: TKey) -> None:
        """Activate ``modal_key`` and remember the previous active key."""
        if self._disposed:
            return
        self._modal_stack.append(self._active_key)
        self._set_active_key_preserving_modals(modal_key)

    def modal_close(self) -> None:
        """Restore the active key that preceded the most recent modal."""
        if self._disposed or not self._modal_stack:
            return
        previous = self._modal_stack.pop()
        self._set_active_key_preserving_modals(previous)

    def clear_modals(self) -> None:
        """Release all saved modal frames without changing the active key."""
        if self._disposed:
            return
        self._modal_stack.clear()

    def dispose(self) -> None:
        """Complete the active-changed stream. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        self._modal_stack.clear()
        self._active_changed.on_completed()
        self._active_changed.dispose()

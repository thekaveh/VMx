"""Read-only live membership capability for aggregate observation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

from reactivex.abc import DisposableBase

T_co = TypeVar("T_co", covariant=True)


@runtime_checkable
class ObservableMembershipSource(Protocol[T_co]):
    """Ordered snapshot plus payload-free structural notifications."""

    def snapshot(self) -> tuple[T_co, ...]: ...

    def subscribe_membership(self, callback: Callable[[], None]) -> DisposableBase: ...

"""DerivedProperty — value derived from N source observables.

See spec/15-derived-properties.md and ADR-0011.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar, cast

import reactivex as rx
from reactivex import Observable, Subject
from reactivex import operators as ops

TValue = TypeVar("TValue")


class DerivedProperty(Generic[TValue]):
    """A read-only-or-read-write value computed from source observables."""

    def __init__(
        self,
        derived_stream: Observable[TValue],
        can_set: Callable[[TValue], bool] | None = None,
        set_action: Callable[[TValue], None] | None = None,
    ) -> None:
        self._value: TValue
        self._has_value = False
        self._changes: Subject[TValue] = Subject()
        self._can_set = can_set
        self._set_action = set_action
        self._disposed = False

        def _on_next(v: TValue) -> None:
            if not self._has_value:
                self._value = v
                self._has_value = True
                return
            if v == self._value:
                return
            self._value = v
            self._changes.on_next(v)

        self._subscription = derived_stream.subscribe(on_next=_on_next)

    @property
    def value(self) -> TValue:
        if not self._has_value:
            raise RuntimeError("Derived property has no value yet — no source has emitted.")
        return self._value

    @property
    def value_changed(self) -> Observable[TValue]:
        return self._changes

    def can_set(self, value: TValue) -> bool:
        return self._can_set(value) if self._can_set is not None else False

    def set_value(self, value: TValue) -> None:
        if not self.can_set(value):
            raise ValueError("can_set returned False for the given value")
        if self._set_action is not None:
            self._set_action(value)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._subscription.dispose()
        self._changes.on_completed()
        self._changes.dispose()


def from_sources(
    *sources: Observable[object],
    transform: Callable[..., TValue],
    can_set: Callable[[TValue], bool] | None = None,
    set_action: Callable[[TValue], None] | None = None,
) -> DerivedProperty[TValue]:
    """Build a DerivedProperty from any number of source observables.

    The transform receives source values positionally, in source order.
    """
    if not sources:
        raise ValueError("At least one source is required")

    if len(sources) == 1:
        stream = sources[0].pipe(ops.map(transform))
    else:

        def _apply(values: object) -> TValue:
            # combine_latest emits a tuple of source values; cast keeps mypy
            # happy without an `assert isinstance` that would be stripped by
            # `python -O`.
            return transform(*cast(tuple[object, ...], values))

        stream = rx.combine_latest(*sources).pipe(ops.map(_apply))

    return DerivedProperty(stream, can_set=can_set, set_action=set_action)

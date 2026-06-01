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

    For 1-5 sources, prefer the typed-arity factories below (``from_one``,
    ``from_two``, ..., ``from_five``) which give mypy / IDEs precise per-source
    types for the transform's parameters. Use ``from_sources`` (or the
    equivalent ``from_many``) when the source count is dynamic or above 5.
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


# ---------------------------------------------------------------------------
# Typed-arity factories (1..5) — parity with C# DerivedProperty.From<T1..Tn>
# and TS fromOne/fromTwo/.../fromFive (per ADR-0035 §2 DP2).
# ---------------------------------------------------------------------------

T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
T4 = TypeVar("T4")
T5 = TypeVar("T5")


def from_one(
    source: Observable[T1],
    transform: Callable[[T1], TValue],
    *,
    can_set: Callable[[TValue], bool] | None = None,
    set_action: Callable[[TValue], None] | None = None,
) -> DerivedProperty[TValue]:
    """Single-source typed factory. ``transform`` receives one ``T1`` value."""
    stream = source.pipe(ops.map(transform))
    return DerivedProperty(stream, can_set=can_set, set_action=set_action)


def from_two(
    source1: Observable[T1],
    source2: Observable[T2],
    transform: Callable[[T1, T2], TValue],
    *,
    can_set: Callable[[TValue], bool] | None = None,
    set_action: Callable[[TValue], None] | None = None,
) -> DerivedProperty[TValue]:
    """Two-source typed factory. ``transform`` receives ``(T1, T2)``."""

    def _apply(values: object) -> TValue:
        v1, v2 = cast(tuple[T1, T2], values)
        return transform(v1, v2)

    stream = rx.combine_latest(source1, source2).pipe(ops.map(_apply))
    return DerivedProperty(stream, can_set=can_set, set_action=set_action)


def from_three(
    source1: Observable[T1],
    source2: Observable[T2],
    source3: Observable[T3],
    transform: Callable[[T1, T2, T3], TValue],
    *,
    can_set: Callable[[TValue], bool] | None = None,
    set_action: Callable[[TValue], None] | None = None,
) -> DerivedProperty[TValue]:
    """Three-source typed factory. ``transform`` receives ``(T1, T2, T3)``."""

    def _apply(values: object) -> TValue:
        v1, v2, v3 = cast(tuple[T1, T2, T3], values)
        return transform(v1, v2, v3)

    stream = rx.combine_latest(source1, source2, source3).pipe(ops.map(_apply))
    return DerivedProperty(stream, can_set=can_set, set_action=set_action)


def from_four(
    source1: Observable[T1],
    source2: Observable[T2],
    source3: Observable[T3],
    source4: Observable[T4],
    transform: Callable[[T1, T2, T3, T4], TValue],
    *,
    can_set: Callable[[TValue], bool] | None = None,
    set_action: Callable[[TValue], None] | None = None,
) -> DerivedProperty[TValue]:
    """Four-source typed factory. ``transform`` receives ``(T1, T2, T3, T4)``."""

    def _apply(values: object) -> TValue:
        v1, v2, v3, v4 = cast(tuple[T1, T2, T3, T4], values)
        return transform(v1, v2, v3, v4)

    stream = rx.combine_latest(source1, source2, source3, source4).pipe(ops.map(_apply))
    return DerivedProperty(stream, can_set=can_set, set_action=set_action)


def from_five(
    source1: Observable[T1],
    source2: Observable[T2],
    source3: Observable[T3],
    source4: Observable[T4],
    source5: Observable[T5],
    transform: Callable[[T1, T2, T3, T4, T5], TValue],
    *,
    can_set: Callable[[TValue], bool] | None = None,
    set_action: Callable[[TValue], None] | None = None,
) -> DerivedProperty[TValue]:
    """Five-source typed factory. ``transform`` receives ``(T1, T2, T3, T4, T5)``."""

    def _apply(values: object) -> TValue:
        v1, v2, v3, v4, v5 = cast(tuple[T1, T2, T3, T4, T5], values)
        return transform(v1, v2, v3, v4, v5)

    # ``rx.combine_latest`` has typed overloads only for 2-4 sources;
    # 5+ sources fall through to a generic variadic at runtime. Cast the
    # input list to ``Observable[object]`` so mypy uses the variadic
    # signature; the type-safety guarantee is preserved by the typed
    # signature of ``from_five`` and the ``cast`` inside ``_apply``.
    sources_typed: list[Observable[object]] = [
        cast(Observable[object], source1),
        cast(Observable[object], source2),
        cast(Observable[object], source3),
        cast(Observable[object], source4),
        cast(Observable[object], source5),
    ]
    stream = rx.combine_latest(*sources_typed).pipe(ops.map(_apply))
    return DerivedProperty(stream, can_set=can_set, set_action=set_action)


# Alias for parity with C# `FromMany` / TS `fromMany`.
from_many = from_sources

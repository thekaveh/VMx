"""Shared subscriber-failure delivery for the library channels.

A failing subscriber does not stop the delivery to the other subscribers and
does not detach a subscription. A call-fed delivery re-raises the first
failure after every subscriber has run; a stream-fed delivery logs it. See
spec/03-messages.md §3.6 and ADR-0191.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TypeVar

import reactivex as rx
from reactivex import Observable, abc
from reactivex.subject import BehaviorSubject, Subject

T = TypeVar("T")


def _deliver_each(
    observers: Sequence[abc.ObserverBase[T]],
    deliver: Callable[[abc.ObserverBase[T]], None],
) -> None:
    """Deliver to each observer in turn, then re-raise the first failure."""
    first_error: BaseException | None = None
    for observer in observers:
        try:
            deliver(observer)
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


class FanOutSubject(Subject[T]):
    """A ``Subject`` that reaches every observer even when one of them raises.

    reactivex's ``Subject`` stops at the first raising observer. This subject
    delivers each value, and the completion, to every observer of a snapshot,
    then re-raises the first failure. No observer is detached.
    """

    def _on_next_core(self, value: T) -> None:
        with self.lock:
            observers = self.observers.copy()
        _deliver_each(observers, lambda observer: observer.on_next(value))

    def _on_completed_core(self) -> None:
        with self.lock:
            observers = self.observers.copy()
            self.observers.clear()
        _deliver_each(observers, lambda observer: observer.on_completed())


class FanOutBehaviorSubject(BehaviorSubject[T]):
    """A ``BehaviorSubject`` with the delivery rules of :class:`FanOutSubject`."""

    def _on_next_core(self, value: T) -> None:
        with self.lock:
            observers = self.observers.copy()
            self.value = value
        _deliver_each(observers, lambda observer: observer.on_next(value))

    def _on_completed_core(self) -> None:
        with self.lock:
            observers = self.observers.copy()
            self.observers.clear()
        _deliver_each(observers, lambda observer: observer.on_completed())


def isolated(source: Observable[T], logger: logging.Logger, channel: str) -> Observable[T]:
    """Wrap each subscriber of *source* so that its failure is logged, not raised.

    This is the stream-fed route (spec/03 §3.6 rule 4), as in
    ``MessageHub.messages`` (``HUB-007``). The failure never reaches the
    upstream publisher, and the subscriber stays attached. The returned
    observable also hides the identity of *source* (VMX-013).
    """

    def subscribe(
        observer: abc.ObserverBase[T],
        scheduler: abc.SchedulerBase | None = None,
    ) -> abc.DisposableBase:
        def on_next(value: T) -> None:
            try:
                observer.on_next(value)
            except Exception:
                logger.exception("%s subscriber raised; isolating per ADR-0191", channel)

        return source.subscribe(
            on_next=on_next,
            on_error=observer.on_error,
            on_completed=observer.on_completed,
            scheduler=scheduler,
        )

    return rx.create(subscribe)

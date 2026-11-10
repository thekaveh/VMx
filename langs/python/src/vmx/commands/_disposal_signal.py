"""Wrapper-command change streams that also notify once at disposal.

See spec/04-commands.md §8.4. TypeScript ``disposalSignal.ts`` is the
counterpart.
"""

from __future__ import annotations

import reactivex as rx
from reactivex import Observable, abc
from reactivex.disposable import CompositeDisposable

from vmx._disposal import _run_disposal_steps
from vmx._subscriber_failures import FanOutSubject


def with_disposal_signal(source: Observable[None], disposal: Observable[None]) -> Observable[None]:
    """Pass *source* through in full and add one value for each *disposal* value.

    The inner completion, such as the one a disposed ``AsyncRelayCommand``
    sends, still reaches the subscriber. A plain merge would hide it.
    """

    def subscribe(
        observer: abc.ObserverBase[None],
        scheduler: abc.SchedulerBase | None = None,
    ) -> abc.DisposableBase:
        inner = source.subscribe(observer, scheduler=scheduler)
        signal = disposal.subscribe(on_next=observer.on_next, scheduler=scheduler)
        return CompositeDisposable(inner, signal)

    return rx.create(subscribe)


class DisposalSignal:
    """The disposal notification of one wrapper command."""

    def __init__(self) -> None:
        self._subject: FanOutSubject[None] = FanOutSubject()

    def wrap(self, source: Observable[None]) -> Observable[None]:
        """Return *source* with this signal added."""
        return with_disposal_signal(source, self._subject)

    def fire(self) -> None:
        """Notify every wrapper subscriber once, then complete the signal.

        Every subscriber runs even when one raises; the first failure is
        re-raised afterwards (spec/03 §3.6). The subject is completed but not
        disposed, so a later subscription to the wrapper stream still works
        and receives no disposal value.
        """
        _run_disposal_steps(lambda: self._subject.on_next(None), self._subject.on_completed)

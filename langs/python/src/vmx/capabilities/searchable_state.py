"""SearchableState — debounced filter helper implementing ISearchable.

See spec/06-composite-vm.md §Search / filter and ADR-0014.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import Observable
from reactivex import operators as ops
from reactivex.abc import SchedulerBase
from reactivex.scheduler import TimeoutScheduler
from reactivex.subject import BehaviorSubject, Subject

from vmx.capabilities.search import ISearchable

T = TypeVar("T")


class SearchableState(ISearchable, Generic[T]):
    """Implements ISearchable with a debounced filter pipeline.

    Args:
        items: callable returning the current items to filter.
        predicate: filter function ``(item, term) -> bool``.
        debounce_seconds: debounce delay (default 1.0; pass 0 to disable).
        scheduler: optional scheduler for the debounce (default:
            TimeoutScheduler — required for real time delays; pass a
            TestScheduler in tests that exercise debounce timing).
    """

    def __init__(
        self,
        items: Callable[[], Iterable[T]],
        predicate: Callable[[T, str], bool],
        debounce_seconds: float = 1.0,
        scheduler: SchedulerBase | None = None,
    ) -> None:
        self._items_source = items
        self._predicate = predicate
        self._term_subject: BehaviorSubject[str] = BehaviorSubject("")
        self._filtered_subject: BehaviorSubject[list[T]] = BehaviorSubject(self._apply_filter(""))
        self._force_search: Subject[None] = Subject()
        self._disposed = False
        sched = scheduler or TimeoutScheduler()

        if debounce_seconds > 0:
            debounced = self._term_subject.pipe(ops.debounce(debounce_seconds, sched))
        else:
            debounced = self._term_subject

        force = self._force_search.pipe(ops.map(lambda _: self._term_subject.value))
        recompute = rx.merge(debounced, force)
        self._subscription = recompute.subscribe(
            on_next=lambda term: self._filtered_subject.on_next(self._apply_filter(term))
        )

    @property
    def search_term(self) -> str:
        return self._term_subject.value

    @search_term.setter
    def search_term(self, value: str) -> None:
        self._term_subject.on_next(value)

    @property
    def filtered(self) -> Observable[list[T]]:
        return self._filtered_subject

    def can_search(self) -> bool:
        return any(True for _ in self._items_source())

    def search(self) -> None:
        self._force_search.on_next(None)

    def _apply_filter(self, term: str) -> list[T]:
        return [item for item in self._items_source() if self._predicate(item, term)]

    def dispose(self) -> None:
        """Tear down internal subscriptions and complete the streams. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        self._subscription.dispose()
        self._term_subject.on_completed()
        self._filtered_subject.on_completed()
        self._force_search.on_completed()

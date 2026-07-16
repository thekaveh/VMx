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
from reactivex.internal.exceptions import DisposedException
from reactivex.scheduler import TimeoutScheduler
from reactivex.subject import BehaviorSubject, Subject

from vmx.capabilities.search import ISearchable

T = TypeVar("T")

# Sentinel for "no first item": a legal None item must not read as "empty".
_NO_ITEM: object = object()


class SearchableState(ISearchable, Generic[T]):
    """Implements ISearchable with a debounced filter pipeline.

    Args:
        items: callable returning the current items to filter.
        predicate: filter function ``(item, term) -> bool``.
        debounce_seconds: debounce delay (default 1.0; pass 0 to disable).
        scheduler: optional scheduler for the debounce (default:
            TimeoutScheduler — required for real time delays; pass a
            TestScheduler in tests that exercise debounce timing).
        source_changes: optional payload-free invalidation stream. Each value
            immediately re-reads ``items`` with the current term. Completion or
            failure stops automatic refresh without terminating ``filtered``.
    """

    def __init__(
        self,
        items: Callable[[], Iterable[T]],
        predicate: Callable[[T, str], bool],
        debounce_seconds: float = 1.0,
        scheduler: SchedulerBase | None = None,
        source_changes: Observable[object] | None = None,
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
        source = (
            source_changes.pipe(
                ops.map(lambda _: self._term_subject.value),
                ops.catch(self._isolate_source_failure),
            )
            if source_changes is not None
            else rx.empty()
        )
        recompute = rx.merge(debounced, force, source)
        self._subscription = recompute.subscribe(on_next=self._emit_filtered)

        # Close the initial snapshot/attach gap. This constructor-only first
        # value cannot be observed by callers; signals after attachment flow
        # through the merged subscription above.
        if source_changes is not None:
            self._filtered_subject.on_next(self._apply_filter(self._term_subject.value))

    @property
    def search_term(self) -> str:
        # After dispose the BehaviorSubject's value is None; keep the declared
        # str contract by reporting an empty term.
        if self._disposed:
            return ""
        return self._term_subject.value

    @search_term.setter
    def search_term(self, value: str) -> None:
        if self._disposed:
            return
        # Spec wording is "emission on a new value" — guard against no-op
        # re-sets so debounce + recompute don't fire when nothing changed.
        if value == self._term_subject.value:
            return
        self._term_subject.on_next(value)

    @property
    def filtered(self) -> Observable[list[T]]:
        # Sealed behind ``as_observable`` so subscribers can only subscribe —
        # never ``on_next``/``dispose`` the internal BehaviorSubject (VMX-013).
        # Replay of the current filtered value is preserved (a fresh subscriber
        # still receives the latest snapshot on subscribe).
        return self._filtered_subject.pipe(ops.as_observable())

    def can_search(self) -> bool:
        # next(iter(...), sentinel) materialises just one element instead of
        # the whole sequence; the dedicated sentinel keeps a legal None item
        # from reading as "empty" (C# uses .Any(), TS a for-loop probe).
        return next(iter(self._items_source()), _NO_ITEM) is not _NO_ITEM

    def search(self) -> None:
        if self._disposed:
            return
        self._force_search.on_next(None)

    def _apply_filter(self, term: str) -> list[T]:
        return [item for item in self._items_source() if self._predicate(item, term)]

    def _emit_filtered(self, term: str) -> None:
        # The debounce runs on a background Timer thread; dispose() can dispose
        # _filtered_subject between this callback's start and its on_next.
        # reactivex raises DisposedException on post-dispose on_next (unlike
        # rxjs's no-op), so drop that fault — a disposed searchable has no
        # observers to notify (parity with the C# guard).
        if self._disposed:
            return
        try:
            self._filtered_subject.on_next(self._apply_filter(term))
        except DisposedException:
            pass

    @staticmethod
    def _isolate_source_failure(_error: Exception, _source: Observable[str]) -> Observable[str]:
        return rx.empty()

    def dispose(self) -> None:
        """Tear down internal subscriptions and complete the streams. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        self._subscription.dispose()
        self._term_subject.on_completed()
        self._term_subject.dispose()
        self._filtered_subject.on_completed()
        self._filtered_subject.dispose()
        self._force_search.on_completed()
        self._force_search.dispose()

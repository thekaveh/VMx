"""Conformance tests for SearchableState source reactivity (SRCH-001..007, SRCH-009)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
import reactivex as rx
from reactivex.disposable import Disposable
from reactivex.subject import Subject
from reactivex.testing import TestScheduler

from vmx.capabilities import SearchableState


def _matches(item: str, term: str) -> bool:
    return term == "" or term.lower() in item.lower()


@pytest.mark.conformance("SRCH-001")
def test_SRCH_001_source_signal_refreshes_unchanged_term() -> None:
    items = ["one"]
    source_changes: Subject[object] = Subject()
    state = SearchableState(
        items=lambda: items,
        predicate=lambda _item, _term: True,
        debounce_seconds=0,
        source_changes=source_changes,
    )
    snapshots: list[list[str]] = []
    state.filtered.subscribe(on_next=snapshots.append)
    before = len(snapshots)

    items.append("two")
    source_changes.on_next(object())

    assert len(snapshots) == before + 1
    assert snapshots[-1] == ["one", "two"]


@pytest.mark.conformance("SRCH-002")
def test_SRCH_002_mutations_read_latest_ordered_snapshot() -> None:
    items = ["a", "b", "c"]
    source_changes: Subject[object] = Subject()
    state = SearchableState(
        items=lambda: items,
        predicate=lambda _item, _term: True,
        debounce_seconds=0,
        source_changes=source_changes,
    )
    snapshots: list[list[str]] = []
    state.filtered.subscribe(on_next=snapshots.append)

    items.pop(1)
    source_changes.on_next(object())
    assert snapshots[-1] == ["a", "c"]

    items[1] = "replacement"
    source_changes.on_next(object())
    assert snapshots[-1] == ["a", "replacement"]

    items[:] = ["reset-1", "reset-2", "reset-3"]
    source_changes.on_next(object())
    assert snapshots[-1] == ["reset-1", "reset-2", "reset-3"]

    items.reverse()
    source_changes.on_next(object())
    assert snapshots[-1] == ["reset-3", "reset-2", "reset-1"]


@pytest.mark.conformance("SRCH-003")
def test_SRCH_003_pulses_preserve_equality_and_upstream_coalescing() -> None:
    items = ["same"]
    source_changes: Subject[object] = Subject()
    state = SearchableState(
        items=lambda: items,
        predicate=lambda _item, _term: True,
        debounce_seconds=0,
        source_changes=source_changes,
    )
    snapshots: list[list[str]] = []
    state.filtered.subscribe(on_next=snapshots.append)
    before = len(snapshots)

    source_changes.on_next(object())
    source_changes.on_next(object())
    assert len(snapshots) == before + 2

    items.extend(["batched-1", "batched-2"])
    source_changes.on_next(object())
    assert len(snapshots) == before + 3
    assert snapshots[-1] == ["same", "batched-1", "batched-2"]


@pytest.mark.conformance("SRCH-004")
def test_SRCH_004_source_refresh_does_not_reset_pending_term_debounce() -> None:
    scheduler = TestScheduler()
    items = ["alpha", "beta"]
    source_changes: Subject[object] = Subject()
    state = SearchableState(
        items=lambda: items,
        predicate=_matches,
        debounce_seconds=10,
        scheduler=scheduler,
        source_changes=source_changes,
    )
    snapshots: list[list[str]] = []
    state.filtered.subscribe(on_next=snapshots.append)

    state.search_term = "alp"
    items.append("alpine")
    before_signal = len(snapshots)
    source_changes.on_next(object())

    assert len(snapshots) == before_signal + 1
    assert snapshots[-1] == ["alpha", "alpine"]

    scheduler.advance_by(9)
    assert len(snapshots) == before_signal + 1
    scheduler.advance_by(1)
    assert len(snapshots) == before_signal + 2
    assert snapshots[-1] == ["alpha", "alpine"]


@pytest.mark.conformance("SRCH-005")
def test_SRCH_005_source_error_is_isolated_from_manual_search() -> None:
    items = ["one"]
    source_changes: Subject[object] = Subject()
    state = SearchableState(
        items=lambda: items,
        predicate=lambda _item, _term: True,
        debounce_seconds=0,
        source_changes=source_changes,
    )
    snapshots: list[list[str]] = []
    errors: list[Exception] = []
    completions: list[None] = []
    state.filtered.subscribe(
        on_next=snapshots.append,
        on_error=errors.append,
        on_completed=lambda: completions.append(None),
    )

    source_changes.on_error(RuntimeError("source failed"))
    items.append("two")
    state.search()

    assert errors == []
    assert completions == []
    assert snapshots[-1] == ["one", "two"]


@pytest.mark.conformance("SRCH-006")
def test_SRCH_006_dispose_cancels_source_once_without_owning_it() -> None:
    subscribe_count = 0
    dispose_count = 0
    source_observer: Any = None

    def subscribe(observer: Any, _scheduler: Any = None) -> Disposable:
        nonlocal subscribe_count, dispose_count, source_observer
        subscribe_count += 1
        source_observer = observer

        def dispose() -> None:
            nonlocal dispose_count
            dispose_count += 1

        return Disposable(dispose)

    source_changes = rx.create(subscribe)
    items = ["one"]
    state = SearchableState(
        items=lambda: items,
        predicate=lambda _item, _term: True,
        debounce_seconds=0,
        source_changes=source_changes,
    )
    snapshots: list[list[str]] = []
    state.filtered.subscribe(on_next=snapshots.append)

    state.dispose()
    state.dispose()
    source_observer.on_next(object())

    assert subscribe_count == 1
    assert dispose_count == 1
    assert len(snapshots) == 1

    independent = source_changes.subscribe(on_next=lambda _value: None)
    assert subscribe_count == 2
    independent.dispose()


class _OwnedItem:
    def __init__(self, value: str) -> None:
        self.value = value
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1


@pytest.mark.conformance("SRCH-007")
def test_SRCH_007_omitted_signal_preserves_explicit_refresh_and_ownership() -> None:
    first = _OwnedItem("one")
    second = _OwnedItem("two")
    items = [first]
    state = SearchableState(
        items=lambda: items,
        predicate=lambda _item, _term: True,
        debounce_seconds=0,
    )
    snapshots: list[list[_OwnedItem]] = []
    state.filtered.subscribe(on_next=snapshots.append)
    before_mutation = len(snapshots)

    items.append(second)
    assert len(snapshots) == before_mutation

    state.search()
    assert snapshots[-1] == [first, second]
    state.dispose()

    assert first.dispose_count == 0
    assert second.dispose_count == 0


class PredicateError(Exception):
    """Raised by the failing predicate."""


class FilteredSubscriberError(Exception):
    """Raised by the failing ``filtered`` subscriber."""


@pytest.mark.conformance("SRCH-009")
def test_SRCH_009_failing_predicate_or_filtered_subscriber_keeps_helper_live(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def predicate(item: str, term: str) -> bool:
        if term == "boom":
            raise PredicateError
        return term in item

    state = SearchableState(
        items=lambda: ["apple", "banana"],
        predicate=predicate,
        debounce_seconds=0,
    )
    a_seen: list[list[str]] = []
    b_seen: list[list[str]] = []

    def failing(snapshot: list[str]) -> None:
        a_seen.append(snapshot)
        raise FilteredSubscriberError

    with caplog.at_level(logging.ERROR):
        state.filtered.subscribe(failing)
        state.filtered.subscribe(b_seen.append)
        a_seen.clear()
        b_seen.clear()

        state.search_term = "boom"
        assert a_seen == []
        assert b_seen == []

        state.search_term = "an"
        assert a_seen == [["banana"]]
        assert b_seen == [["banana"]]

        state.search()
        assert a_seen == [["banana"], ["banana"]]
        assert b_seen == [["banana"], ["banana"]]

    failures = [r.exc_info[1] for r in caplog.records if r.exc_info is not None]
    assert any(isinstance(error, PredicateError) for error in failures)
    assert any(isinstance(error, FilteredSubscriberError) for error in failures)
    state.dispose()

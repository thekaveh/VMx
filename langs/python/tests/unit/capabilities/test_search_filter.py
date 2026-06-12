"""Unit tests: SearchableState dispose-path and no-op regression guards.

These tests verify idempotence, observable-completion on dispose, and the
equality guard in search_term.setter. They are not normative conformance IDs —
COMP-014..018 / GRP-007..010 cover the behavior-level conformance tests.
"""

from __future__ import annotations

from vmx.capabilities import SearchableState


def _ci_substr(item: str, term: str) -> bool:
    if term == "":
        return True
    return term.lower() in item.lower()


def test_searchable_state_dispose_is_idempotent() -> None:
    items = ["a"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    s.dispose()
    # Second call must be a no-op (no Subject re-completion error from reactivex).
    s.dispose()


def test_searchable_state_dispose_completes_filtered_stream() -> None:
    items = ["a"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    completed = False

    def on_completed() -> None:
        nonlocal completed
        completed = True

    s.filtered.subscribe(on_completed=on_completed)
    s.dispose()
    assert completed is True


def test_searchable_state_search_term_setter_skips_noop_re_set() -> None:
    """Setting search_term to its current value must not trigger a recompute.

    Regression guard for the equality-guard in SearchableState.search_term.setter.
    Spec wording: "emission on a new value".
    """
    items = ["apple", "banana"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    snapshots: list[list[str]] = []
    s.filtered.subscribe(on_next=lambda v: snapshots.append(list(v)))
    initial_count = len(snapshots)

    s.search_term = "appl"
    after_first = len(snapshots)
    assert after_first > initial_count, "first set must emit"

    s.search_term = "appl"  # same value
    after_second = len(snapshots)
    assert after_second == after_first, (
        "setting search_term to the same value must NOT trigger a recompute "
        f"(got {after_second - after_first} extra emission(s))"
    )


def test_can_search_true_when_first_item_is_none() -> None:
    """A legal None item must not read as 'no items' (sentinel regression)."""
    s = SearchableState(items=lambda: [None, 1, 2], predicate=lambda i, t: True, debounce_seconds=0)
    assert s.can_search() is True
    s.dispose()


def test_can_search_false_when_empty() -> None:
    s = SearchableState(items=lambda: [], predicate=lambda i, t: True, debounce_seconds=0)
    assert s.can_search() is False
    s.dispose()

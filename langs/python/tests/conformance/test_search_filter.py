"""Conformance tests: COMP-014..018, GRP-007..010 — search / filter.

Per spec/06-composite-vm.md §Search/filter, spec/07-group-vm.md, ADR-0014.
"""

from __future__ import annotations

import pytest

from vmx.capabilities import SearchableState


def _ci_substr(item: str, term: str) -> bool:
    if term == "":
        return True
    return term.lower() in item.lower()


# ---------------------------------------------------------------------------
# COMP-014 — defaults
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-014")
def test_COMP_014_defaults() -> None:
    items = ["apple", "banana", "cherry"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    assert s.search_term == ""
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    assert snap[-1] == items


# ---------------------------------------------------------------------------
# COMP-015 — debounced recompute
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-015")
def test_COMP_015_search_term_triggers_recompute() -> None:
    items = ["apple", "banana", "cherry"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    s.search_term = "an"
    assert snap[-1] == ["banana"]


# ---------------------------------------------------------------------------
# COMP-016 — search() forces immediate
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-016")
def test_COMP_016_search_forces_immediate() -> None:
    items = ["one", "two"]
    s = SearchableState(
        items=lambda: items,
        predicate=lambda item, term: term == "" or item == term,
        debounce_seconds=1.0,  # large debounce
    )
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    s.search_term = "two"
    s.search()  # force immediate
    assert snap[-1] == ["two"]


# ---------------------------------------------------------------------------
# COMP-017 — user-supplied predicate
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-017")
def test_COMP_017_user_predicate() -> None:
    items = ["a", "bb", "ccc"]
    s = SearchableState(
        items=lambda: items,
        predicate=lambda item, term: len(item) > len(term),
        debounce_seconds=0,
    )
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    s.search_term = "bb"
    s.search()
    assert snap[-1] == ["ccc"]


# ---------------------------------------------------------------------------
# COMP-018 — recomputes when items source changes
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-018")
def test_COMP_018_recompute_on_items_change() -> None:
    items: list[str] = ["one"]
    s = SearchableState(
        items=lambda: items,
        predicate=lambda _i, _t: True,
        debounce_seconds=0,
    )
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    items.append("two")
    s.search()
    assert snap[-1] == ["one", "two"]


# ---------------------------------------------------------------------------
# GRP-007..010 — same SearchableState used in group context
# ---------------------------------------------------------------------------


@pytest.mark.conformance("GRP-007")
def test_GRP_007_defaults_group_context() -> None:
    items = ["x", "y"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    assert s.search_term == ""


@pytest.mark.conformance("GRP-008")
def test_GRP_008_term_recompute_group_context() -> None:
    items = ["x", "yx", "z"]
    s = SearchableState(items=lambda: items, predicate=_ci_substr, debounce_seconds=0)
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    s.search_term = "x"
    assert snap[-1] == ["x", "yx"]


@pytest.mark.conformance("GRP-009")
def test_GRP_009_search_forces_group_context() -> None:
    items = ["a", "b"]
    s = SearchableState(
        items=lambda: items,
        predicate=lambda i, t: t == "" or i == t,
        debounce_seconds=1.0,
    )
    snap: list[list[str]] = []
    s.filtered.subscribe(on_next=snap.append)
    s.search_term = "b"
    s.search()
    assert snap[-1] == ["b"]


@pytest.mark.conformance("GRP-010")
def test_GRP_010_user_predicate_group_context() -> None:
    items = [1, 2, 3, 4]
    s: SearchableState[int] = SearchableState(
        items=lambda: items,
        predicate=lambda i, t: i > int(t or 0),
        debounce_seconds=0,
    )
    snap: list[list[int]] = []
    s.filtered.subscribe(on_next=snap.append)
    s.search_term = "2"
    s.search()
    assert snap[-1] == [3, 4]

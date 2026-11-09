"""Conformance tests: COL-070 — dictionary key views give callers no mutator.

``keys1`` and ``keys2`` return a :class:`ReadOnlyObservableList`. The view
reads and notifies, but it has no add, insert, remove, replace, clear, or
batch member. Per spec/21-collections.md §4.1-§4.2 and ADR-0193 (#1316).
"""

from __future__ import annotations

import pytest

import vmx
import vmx.collections
from vmx.collections import ObservableDictionary, ObservableList, ReadOnlyObservableList

_MUTATORS = (
    "add",
    "append",
    "extend",
    "insert",
    "remove",
    "remove_at",
    "replace",
    "replace_all",
    "clear",
    "batch_update",
    "__setitem__",
    "__delitem__",
)


@pytest.mark.conformance("COL-070")
def test_COL_070_key_views_are_read_only_lists_in_first_appearance_order() -> None:
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary()
    dictionary.add("a", 1, "one")
    dictionary.add("b", 2, "two")

    keys1 = dictionary.keys1
    keys2 = dictionary.keys2

    assert list(keys1) == ["a", "b"]
    assert list(keys2) == [1, 2]
    for view in (keys1, keys2):
        assert isinstance(view, ReadOnlyObservableList)
        assert not isinstance(view, ObservableList)
        for name in _MUTATORS:
            assert not hasattr(view, name), name


@pytest.mark.conformance("COL-070")
def test_COL_070_read_only_list_is_exported_from_the_public_packages() -> None:
    assert vmx.ReadOnlyObservableList is ReadOnlyObservableList
    assert vmx.collections.ReadOnlyObservableList is ReadOnlyObservableList
    assert "ReadOnlyObservableList" in vmx.__all__
    assert "ReadOnlyObservableList" in vmx.collections.__all__


@pytest.mark.conformance("COL-070")
def test_COL_070_key_views_notify_when_the_dictionary_adds_a_key() -> None:
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary()
    added: list[tuple[str, int]] = []
    dictionary.keys1.on_item_added.subscribe(added.append)

    dictionary.add("a", 1, "one")

    assert added == [("a", 0)]

"""Conformance tests: COL-068 — dictionary Remove and Replace hub messages carry the entry position.

Remove sets ``index`` and ``old_index`` to the entry's position before the
removal and ``new_index`` to -1. Replace sets all three to the entry's
position. A position is the entry's index in enumeration order. Per
spec/21-collections.md §4.7 and ADR-0193 (#1316).
"""

from __future__ import annotations

import pytest

from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


def _dictionary() -> tuple[
    ObservableDictionary[str, int, str], list[CollectionChangedMessage[object]]
]:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary(hub=hub)
    dictionary.add("a", 1, "one")
    dictionary.add("b", 2, "two")
    dictionary.add("c", 3, "three")
    messages: list[CollectionChangedMessage[object]] = []
    hub.messages.subscribe(messages.append)  # type: ignore[arg-type]
    return dictionary, messages


@pytest.mark.conformance("COL-068")
def test_COL_068_replace_then_remove_carry_the_entry_position() -> None:
    dictionary, messages = _dictionary()

    dictionary["c", 3] = "z"
    dictionary.remove("b", 2)

    replace, remove = messages
    assert replace.action == "replace"
    assert (replace.index, replace.old_index, replace.new_index) == (2, 2, 2)
    assert replace.new_items == (("c", 3, "z"),)
    assert replace.old_items == (("c", 3, "three"),)
    assert remove.action == "remove"
    assert (remove.index, remove.old_index, remove.new_index) == (1, 1, -1)
    assert remove.old_items == (("b", 2, "two"),)


@pytest.mark.conformance("COL-068")
def test_COL_068_delitem_reports_the_pre_removal_position() -> None:
    dictionary, messages = _dictionary()

    del dictionary["a", 1]

    (remove,) = messages
    assert remove.action == "remove"
    assert (remove.index, remove.old_index, remove.new_index) == (0, 0, -1)

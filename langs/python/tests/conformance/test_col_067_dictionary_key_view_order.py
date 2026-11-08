"""Conformance tests: COL-067 — dictionary events and the hub message follow both key-view updates.

A mutation changes the entries and ``count``, then both key views, then raises
the dictionary events and sends the hub message. The order of the two key-view
notifications is not checked. Per spec/21-collections.md §4.2 and ADR-0177
(#1176).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub

Snapshot = tuple[list[tuple[str, int, str]], int, list[str], list[int]]
Dictionary = ObservableDictionary[str, int, str]

_MUTATIONS: dict[str, tuple[Callable[[Dictionary], object], Snapshot]] = {
    "add": (
        lambda d: d.add("c", 3, "three"),
        ([("a", 1, "one"), ("b", 2, "two"), ("c", 3, "three")], 3, ["a", "b", "c"], [1, 2, 3]),
    ),
    "insert": (
        lambda d: d.__setitem__(("c", 3), "three"),
        ([("a", 1, "one"), ("b", 2, "two"), ("c", 3, "three")], 3, ["a", "b", "c"], [1, 2, 3]),
    ),
    "remove": (lambda d: d.remove("a", 1), ([("b", 2, "two")], 1, ["b"], [2])),
    "clear": (lambda d: d.clear(), ([], 0, [], [])),
}


def _read(dictionary: Dictionary) -> Snapshot:
    return (list(dictionary), dictionary.count, list(dictionary.keys1), list(dictionary.keys2))


@pytest.mark.conformance("COL-067")
@pytest.mark.parametrize("mutation", list(_MUTATIONS))
def test_COL_067_dictionary_events_and_hub_message_follow_both_key_views(mutation: str) -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    dictionary: Dictionary = ObservableDictionary(hub=hub)
    dictionary.add("a", 1, "one")
    dictionary.add("b", 2, "two")
    seen: list[tuple[str, Snapshot]] = []

    def record(channel: str) -> Callable[[object], None]:
        return lambda _: seen.append((channel, _read(dictionary)))

    hub.messages.subscribe(record("hub"))
    dictionary.on_item_added.subscribe(record("dictionary"))
    dictionary.on_item_removed.subscribe(record("dictionary"))
    dictionary.on_reset.subscribe(record("dictionary"))
    for channel, view in (("keys1", dictionary.keys1), ("keys2", dictionary.keys2)):
        view.on_item_added.subscribe(record(channel))
        view.on_item_removed.subscribe(record(channel))
        view.on_reset.subscribe(record(channel))
    act, expected = _MUTATIONS[mutation]

    act(dictionary)

    final = _read(dictionary)
    assert final == expected
    # Both key views notify first, in an unspecified order; then the
    # dictionary event, then the hub message.
    assert sorted(channel for channel, _ in seen[:2]) == ["keys1", "keys2"]
    assert [channel for channel, _ in seen[2:]] == ["dictionary", "hub"]
    # A key-view handler sees the updated entries, count and own view.
    for channel, (entries, count, keys1, keys2) in seen[:2]:
        assert (entries, count) == (final[0], final[1])
        assert (keys1 if channel == "keys1" else keys2) == (
            final[2] if channel == "keys1" else final[3]
        )
    # The dictionary event and the hub message see both views updated.
    for _, state in seen[2:]:
        assert state == final

"""Conformance tests: COL-071 — a duplicate dictionary ``add`` fails and changes nothing.

``ObservableDictionary.add`` of a key pair that is already present raises
``ValueError``, the keyed collection's duplicate-key type. The stored value,
the entries, the key views and ``count`` do not change, and no local event or
hub message is sent. Per spec/21-collections.md §4.1 and ADR-0214 (#1308).
"""

from __future__ import annotations

import pytest

from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


@pytest.mark.conformance("COL-071")
def test_COL_071_duplicate_add_raises_value_error_and_changes_nothing() -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary(hub=hub)
    dictionary.add("a", 1, "one")
    dictionary.add("b", 2, "two")
    events: list[str] = []
    hub.messages.subscribe(lambda _m: events.append("hub"))
    dictionary.on_item_added.subscribe(lambda _e: events.append("added"))
    dictionary.on_item_removed.subscribe(lambda _e: events.append("removed"))
    dictionary.on_item_replaced.subscribe(lambda _e: events.append("replaced"))
    dictionary.on_reset.subscribe(lambda _e: events.append("reset"))
    for channel, view in (("keys1", dictionary.keys1), ("keys2", dictionary.keys2)):
        view.on_item_added.subscribe(lambda _e, c=channel: events.append(c))
        view.on_item_removed.subscribe(lambda _e, c=channel: events.append(c))
        view.on_reset.subscribe(lambda _e, c=channel: events.append(c))

    with pytest.raises(ValueError) as caught:
        dictionary.add("a", 1, "uno")

    assert type(caught.value) is ValueError
    assert dictionary["a", 1] == "one"
    assert dictionary.count == 2
    assert list(dictionary) == [("a", 1, "one"), ("b", 2, "two")]
    assert list(dictionary.keys1) == ["a", "b"]
    assert list(dictionary.keys2) == [1, 2]
    assert events == []

"""Conformance tests: COL-066 — a failing local subscriber does not suppress the hub message.

The change is committed and exactly one hub ``CollectionChangedMessage`` is
sent; Python re-raises the first failure after publication. Per
spec/01-concepts.md §1.4, spec/21-collections.md §2.5 and ADR-0171 (#1051).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.collections.keyed_serviced_observable_collection import (
    KeyedServicedObservableCollection,
)
from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


class LocalFailureError(Exception):
    """Raised by the failing local subscriber."""


ListLike = ServicedObservableCollection[str] | KeyedServicedObservableCollection[str, str]

_LIST_MUTATIONS: dict[str, tuple[Callable[[ListLike], object], str, list[str]]] = {
    "append": (lambda c: c.append("c"), "add", ["a", "b", "c"]),
    "remove_at": (lambda c: c.remove_at(0), "remove", ["b"]),
    "replace": (lambda c: c.replace(0, "z"), "replace", ["z", "b"]),
    "move": (lambda c: c.move(0, 1), "move", ["b", "a"]),
    "clear": (lambda c: c.clear(), "reset", []),
    "replace_all": (
        lambda c: c.replace_all(["x", "y"]),
        "reset",
        ["x", "y"],
    ),
}


def _make_list(kind: str, hub: MessageHub[CollectionChangedMessage[str]]) -> ListLike:
    collection: ListLike
    if kind == "serviced":
        collection = ServicedObservableCollection(hub=hub)
    else:
        collection = KeyedServicedObservableCollection(lambda item: item, hub=hub)
    collection.append("a")
    collection.append("b")
    return collection


@pytest.mark.conformance("COL-066")
@pytest.mark.parametrize("kind", ["serviced", "keyed"])
@pytest.mark.parametrize("mutation", list(_LIST_MUTATIONS))
def test_COL_066_list_sends_one_hub_message_despite_failing_local_subscriber(
    kind: str, mutation: str
) -> None:
    hub: MessageHub[CollectionChangedMessage[str]] = MessageHub()
    collection = _make_list(kind, hub)
    order: list[str] = []
    messages: list[CollectionChangedMessage[str]] = []

    def on_hub(message: object) -> None:
        assert isinstance(message, CollectionChangedMessage)
        messages.append(message)
        order.append("hub")

    def on_local(_: CollectionChangedMessage[str]) -> None:
        order.append("local")
        raise LocalFailureError

    hub.messages.subscribe(on_hub)
    collection.on_collection_changed.subscribe(on_local)
    act, action, expected = _LIST_MUTATIONS[mutation]

    with pytest.raises(LocalFailureError):
        act(collection)

    assert list(collection) == expected
    if isinstance(collection, KeyedServicedObservableCollection):
        assert all(collection.get(item) == item for item in expected)
    assert [m.action for m in messages] == [action]
    assert order == ["local", "hub"]


Dictionary = ObservableDictionary[str, int, str]
DictMutation = tuple[Callable[[Dictionary], object], list[tuple[str, int, str]]]

_DICT_MUTATIONS: dict[str, DictMutation] = {
    "add": (lambda d: d.add("b", 2, "two"), [("a", 1, "one"), ("b", 2, "two")]),
    "remove": (lambda d: d.remove("a", 1), []),
    "replace": (lambda d: d.__setitem__(("a", 1), "uno"), [("a", 1, "uno")]),
    "clear": (lambda d: d.clear(), []),
}


@pytest.mark.conformance("COL-066")
@pytest.mark.parametrize("mutation", list(_DICT_MUTATIONS))
def test_COL_066_dictionary_sends_one_hub_message_despite_failing_local_subscriber(
    mutation: str,
) -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary(hub=hub)
    dictionary.add("a", 1, "one")
    order: list[str] = []
    messages: list[object] = []

    def on_hub(message: object) -> None:
        messages.append(message)
        order.append("hub")

    def on_local(_: object) -> None:
        order.append("local")
        raise LocalFailureError

    hub.messages.subscribe(on_hub)
    dictionary.on_item_added.subscribe(on_local)
    dictionary.on_item_removed.subscribe(on_local)
    dictionary.on_item_replaced.subscribe(on_local)
    dictionary.on_reset.subscribe(on_local)
    act, expected = _DICT_MUTATIONS[mutation]

    with pytest.raises(LocalFailureError):
        act(dictionary)

    assert list(dictionary) == expected
    assert len(messages) == 1
    assert isinstance(messages[0], CollectionChangedMessage)
    assert order == ["local", "hub"]

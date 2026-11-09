"""Conformance tests: COL-069 — a failing local subscriber does not stop later subscribers.

Each local subscriber receives each change once, the failing subscriber stays
attached, and the hub receives one ``CollectionChangedMessage`` per change.
Python re-raises the first failure after the hub send. Per spec/21-collections.md
§2.5, spec/01-concepts.md §1.4, spec/03-messages.md §3.6 and ADR-0191 (#1311).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import reactivex as rx

from vmx.collections.keyed_serviced_observable_collection import (
    KeyedServicedObservableCollection,
)
from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


class LocalFailureError(Exception):
    """Raised by the failing local subscriber."""


class _Recorder:
    """Two local subscribers, A then B; A fails on every delivery."""

    def __init__(self, stream: rx.Observable[Any]) -> None:
        self.a_seen: list[object] = []
        self.b_seen: list[object] = []
        stream.subscribe(self._failing)
        stream.subscribe(self.b_seen.append)

    def _failing(self, change: object) -> None:
        self.a_seen.append(change)
        raise LocalFailureError


def _hub_messages(hub: MessageHub[Any]) -> list[CollectionChangedMessage[Any]]:
    messages: list[CollectionChangedMessage[Any]] = []

    def on_hub(message: object) -> None:
        assert isinstance(message, CollectionChangedMessage)
        messages.append(message)

    hub.messages.subscribe(on_hub)
    return messages


@pytest.mark.conformance("COL-069")
@pytest.mark.parametrize("kind", ["serviced", "keyed"])
def test_COL_069_list_failing_local_subscriber_does_not_stop_later_subscriber(
    kind: str,
) -> None:
    hub: MessageHub[Any] = MessageHub()
    collection: ServicedObservableCollection[str] | KeyedServicedObservableCollection[str, str]
    if kind == "serviced":
        collection = ServicedObservableCollection(hub=hub)
    else:
        collection = KeyedServicedObservableCollection(lambda item: item, hub=hub)
    messages = _hub_messages(hub)
    recorder = _Recorder(collection.on_collection_changed)

    with pytest.raises(LocalFailureError):
        collection.append("a")
    with pytest.raises(LocalFailureError):
        collection.append("b")

    assert list(collection) == ["a", "b"]
    assert len(recorder.b_seen) == 2
    assert recorder.a_seen == recorder.b_seen
    assert [m.action for m in messages] == ["add", "add"]


Dictionary = ObservableDictionary[str, int, str]

_GRANULAR: dict[str, tuple[Callable[[Dictionary], Any], Callable[[Dictionary, int], object]]] = {
    "added": (lambda d: d.on_item_added, lambda d, n: d.add(f"k{n}", n, "v")),
    "removed": (lambda d: d.on_item_removed, lambda d, n: d.remove("a" if n == 0 else "b", n + 1)),
    "replaced": (lambda d: d.on_item_replaced, lambda d, n: d.__setitem__(("a", 1), f"r{n}")),
    "reset": (lambda d: d.on_reset, lambda d, _n: d.clear()),
}


@pytest.mark.conformance("COL-069")
@pytest.mark.parametrize("event", list(_GRANULAR))
def test_COL_069_dictionary_failing_granular_handler_does_not_stop_later_handler(
    event: str,
) -> None:
    hub: MessageHub[Any] = MessageHub()
    dictionary: Dictionary = ObservableDictionary(hub=hub)
    dictionary.add("a", 1, "one")
    dictionary.add("b", 2, "two")
    select, act = _GRANULAR[event]
    recorder = _Recorder(select(dictionary))
    messages = _hub_messages(hub)

    for n in range(2):
        if event == "reset" and n == 1:
            dictionary.add("c", 3, "three")
            messages.clear()
        before = len(messages)
        with pytest.raises(LocalFailureError):
            act(dictionary, n)
        # One hub message for this change, sent before the re-raise.
        assert len(messages) == before + 1

    assert len(recorder.b_seen) == 2
    assert recorder.a_seen == recorder.b_seen

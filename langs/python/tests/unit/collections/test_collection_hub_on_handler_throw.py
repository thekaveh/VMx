"""#1051 — a raising local subscriber does not suppress the hub message.

The first failure wins and is re-raised after publication
(spec/21-collections.md §2.5, ADR-0171).
"""

from __future__ import annotations

import pytest

from vmx.collections._delivery import deliver_then_publish
from vmx.collections.keyed_serviced_observable_collection import (
    KeyedServicedObservableCollection,
)
from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


class LocalFailureError(Exception):
    """Raised by a local subscriber."""


class HubFailureError(Exception):
    """Raised by the hub."""


class _ThrowingHub:
    """A hub whose ``send`` records the message, then raises."""

    def __init__(self) -> None:
        self.sent: list[object] = []

    def send(self, message: object) -> None:
        self.sent.append(message)
        raise HubFailureError


def _raise_local(_: object) -> None:
    raise LocalFailureError


def test_local_failure_wins_over_hub_failure() -> None:
    hub = _ThrowingHub()
    collection: ServicedObservableCollection[int] = ServicedObservableCollection(hub=hub)  # type: ignore[arg-type]
    collection.on_collection_changed.subscribe(_raise_local)

    with pytest.raises(LocalFailureError):
        collection.append(1)

    assert list(collection) == [1]
    assert len(hub.sent) == 1


def test_hub_failure_still_propagates_without_a_local_failure() -> None:
    hub = _ThrowingHub()
    collection: KeyedServicedObservableCollection[int, int] = KeyedServicedObservableCollection(
        lambda item: item,
        hub=hub,  # type: ignore[arg-type]
    )

    with pytest.raises(HubFailureError):
        collection.append(1)

    assert collection.get(1) == 1


def test_raising_subscriber_keeps_publishing_on_later_mutations() -> None:
    hub: MessageHub[CollectionChangedMessage[int]] = MessageHub()
    messages: list[object] = []
    hub.messages.subscribe(messages.append)
    collection: ServicedObservableCollection[int] = ServicedObservableCollection(hub=hub)
    collection.on_collection_changed.subscribe(_raise_local)

    for value in (1, 2):
        with pytest.raises(LocalFailureError):
            collection.append(value)

    assert list(collection) == [1, 2]
    assert len(messages) == 2


def test_no_hub_still_reraises_the_local_failure() -> None:
    collection: ServicedObservableCollection[int] = ServicedObservableCollection()
    collection.on_collection_changed.subscribe(_raise_local)

    with pytest.raises(LocalFailureError):
        collection.append(1)

    assert list(collection) == [1]


def test_dictionary_add_index_is_read_after_local_delivery() -> None:
    hub = _ThrowingHub()
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary(hub=hub)  # type: ignore[arg-type]
    dictionary.on_item_added.subscribe(_raise_local)

    with pytest.raises(LocalFailureError):
        dictionary.add("a", 1, "one")

    assert len(hub.sent) == 1
    message = hub.sent[0]
    assert isinstance(message, CollectionChangedMessage)
    assert message.action == "add"
    assert message.new_index == 0


def test_disposed_dictionary_publishes_nothing() -> None:
    hub = _ThrowingHub()
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary(hub=hub)  # type: ignore[arg-type]
    dictionary.dispose()

    dictionary.add("a", 1, "one")

    assert hub.sent == []


def test_deliver_then_publish_runs_publish_after_a_base_exception() -> None:
    calls: list[str] = []

    def deliver() -> None:
        calls.append("deliver")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        deliver_then_publish(deliver, lambda: calls.append("publish"))

    assert calls == ["deliver", "publish"]

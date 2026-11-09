"""A failing subscriber does not skip the later notification steps (#1367, #1430).

``ObservableList`` still sends ``Count`` after a raising granular or reset
subscriber. ``ObservableDictionary`` still updates both key views, raises its
own events and sends its hub message after a raising key-view subscriber. The
first failure is re-raised to the caller after the last step (spec/21 §3.3,
#1367, #1430).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import reactivex as rx

from vmx.collections.observable_dictionary import ObservableDictionary
from vmx.collections.observable_list import ObservableList
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


class SubscriberError(Exception):
    """Raised by the failing subscriber."""


def _raise(_: object) -> None:
    raise SubscriberError


def _setup_empty(lst: ObservableList[int]) -> None:
    return None


def _setup_one(lst: ObservableList[int]) -> None:
    lst.append(1)


def _batch_append(lst: ObservableList[int]) -> None:
    with lst.batch_update():
        lst.append(1)


_LIST_CASES: list[tuple[str, Callable[[ObservableList[int]], None], str, Any, int]] = [
    ("append", _setup_empty, "on_item_added", lambda lst: lst.append(1), 1),
    ("insert", _setup_empty, "on_item_added", lambda lst: lst.insert(0, 1), 1),
    ("remove", _setup_one, "on_item_removed", lambda lst: lst.remove(1), 0),
    ("remove_at", _setup_one, "on_item_removed", lambda lst: lst.remove_at(0), 0),
    ("clear", _setup_one, "on_reset", lambda lst: lst.clear(), 0),
    ("replace_all", _setup_one, "on_reset", lambda lst: lst.replace_all([1, 2]), 2),
    ("batch", _setup_empty, "on_reset", _batch_append, 1),
]


@pytest.mark.parametrize(
    ("setup", "stream", "operation", "final_count"),
    [case[1:] for case in _LIST_CASES],
    ids=[case[0] for case in _LIST_CASES],
)
def test_observable_list_sends_count_after_a_raising_subscriber(
    setup: Callable[[ObservableList[int]], None],
    stream: str,
    operation: Callable[[ObservableList[int]], None],
    final_count: int,
) -> None:
    lst: ObservableList[int] = ObservableList()
    setup(lst)
    names: list[str] = []
    lst.on_property_changed.subscribe(names.append)
    later: list[object] = []
    source: rx.Observable[Any] = getattr(lst, stream)
    source.subscribe(_raise)
    source.subscribe(later.append)

    with pytest.raises(SubscriberError):
        operation(lst)

    assert lst.count == final_count
    assert names == ["Count"]
    assert len(later) == 1


def test_observable_list_replace_delivers_to_every_subscriber_then_raises() -> None:
    lst: ObservableList[int] = ObservableList()
    lst.append(1)
    later: list[object] = []
    lst.on_item_replaced.subscribe(_raise)
    lst.on_item_replaced.subscribe(later.append)

    with pytest.raises(SubscriberError):
        lst.replace(0, 2)

    assert list(lst) == [2]
    assert later == [(2, 1, 0)]


def test_observable_list_raising_count_subscriber_reaches_later_subscribers() -> None:
    lst: ObservableList[int] = ObservableList()
    names: list[str] = []
    lst.on_property_changed.subscribe(_raise)
    lst.on_property_changed.subscribe(names.append)

    with pytest.raises(SubscriberError):
        lst.append(1)

    assert names == ["Count"]


# ── ObservableDictionary key views ─────────────────────────────────────────


class _Recording:
    def __init__(self, dictionary: ObservableDictionary[str, int, str], hub: MessageHub[Any]):
        self.events: list[str] = []
        dictionary.on_item_added.subscribe(lambda _: self.events.append("added"))
        dictionary.on_item_removed.subscribe(lambda _: self.events.append("removed"))
        dictionary.on_item_replaced.subscribe(lambda _: self.events.append("replaced"))
        dictionary.on_reset.subscribe(lambda _: self.events.append("reset"))
        self.hub: list[CollectionChangedMessage[Any]] = []
        hub.messages.subscribe(self._on_hub)

    def _on_hub(self, message: object) -> None:
        if isinstance(message, CollectionChangedMessage):
            self.hub.append(message)


def _assert_views_match(dictionary: ObservableDictionary[str, int, str]) -> None:
    keys1: list[str] = []
    keys2: list[int] = []
    for k1, k2, _ in dictionary:
        if k1 not in keys1:
            keys1.append(k1)
        if k2 not in keys2:
            keys2.append(k2)
    assert list(dictionary.keys1) == keys1
    assert list(dictionary.keys2) == keys2


def _dict_add(d: ObservableDictionary[str, int, str]) -> None:
    d.add("b", 2, "x")


def _dict_set(d: ObservableDictionary[str, int, str]) -> None:
    d[("b", 2)] = "x"


def _dict_remove(d: ObservableDictionary[str, int, str]) -> None:
    d.remove("a", 1)


def _dict_clear(d: ObservableDictionary[str, int, str]) -> None:
    d.clear()


_DICT_CASES = [
    ("add", _dict_add, "added"),
    ("set", _dict_set, "added"),
    ("remove", _dict_remove, "removed"),
    ("clear", _dict_clear, "reset"),
]


@pytest.mark.parametrize("view", ["keys1", "keys2"])
@pytest.mark.parametrize(
    ("operation", "event"),
    [case[1:] for case in _DICT_CASES],
    ids=[case[0] for case in _DICT_CASES],
)
def test_dictionary_raising_key_view_subscriber_skips_no_notification(
    view: str,
    operation: Callable[[ObservableDictionary[str, int, str]], None],
    event: str,
) -> None:
    hub: MessageHub[Any] = MessageHub()
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary(hub)
    dictionary.add("a", 1, "v")
    recording = _Recording(dictionary, hub)
    key_view = getattr(dictionary, view)
    key_view.on_item_added.subscribe(_raise)
    key_view.on_item_removed.subscribe(_raise)
    key_view.on_reset.subscribe(_raise)

    with pytest.raises(SubscriberError):
        operation(dictionary)

    assert recording.events == [event]
    assert len(recording.hub) == 1
    _assert_views_match(dictionary)


def test_failed_keys2_add_still_lists_the_new_key1() -> None:
    dictionary: ObservableDictionary[str, int, str] = ObservableDictionary()
    subscription = dictionary.keys2.on_item_added.subscribe(_raise)

    with pytest.raises(SubscriberError):
        dictionary.add("a", 1, "v")

    assert list(dictionary.keys1) == ["a"]
    assert list(dictionary.keys2) == [1]
    subscription.dispose()
    dictionary.add("a", 2, "z")
    assert list(dictionary.keys1) == ["a"]
    assert list(dictionary.keys2) == [1, 2]
    assert dictionary.count == 2

"""Unit tests for ServicedObservableCollection.

Conformance-level tests live in tests/conformance/test_col_001_to_004_serviced.py.
"""

from __future__ import annotations

import pytest

from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hub() -> MessageHub[CollectionChangedMessage[int]]:
    return MessageHub()


# ---------------------------------------------------------------------------
# Null-hub fallback
# ---------------------------------------------------------------------------


def test_no_hub_append_raises_local_event() -> None:
    sut: ServicedObservableCollection[str] = ServicedObservableCollection()
    events: list[CollectionChangedMessage[str]] = []
    sut.on_collection_changed.subscribe(events.append)

    sut.append("hello")

    assert len(events) == 1
    assert events[0].action == "add"
    assert events[0].new_items == ("hello",)


def test_no_hub_clear_raises_reset_event() -> None:
    sut: ServicedObservableCollection[int] = ServicedObservableCollection()
    sut.append(1)
    sut.append(2)
    events: list[CollectionChangedMessage[int]] = []
    sut.on_collection_changed.subscribe(events.append)

    sut.clear()

    assert len(events) == 1
    assert events[0].action == "reset"


def test_no_hub_all_mutations_do_not_raise() -> None:
    sut: ServicedObservableCollection[int] = ServicedObservableCollection(hub=None)
    sut.append(1)
    sut.append(2)
    sut.remove(1)
    sut[0] = 99
    sut.clear()
    # No exception raised — pass


def test_no_hub_insert_emits_add() -> None:
    sut: ServicedObservableCollection[int] = ServicedObservableCollection()
    sut.append(10)
    sut.append(30)
    events: list[CollectionChangedMessage[int]] = []
    sut.on_collection_changed.subscribe(events.append)

    sut.insert(1, 20)

    assert len(sut) == 3
    assert sut[1] == 20
    assert len(events) == 1
    assert events[0].action == "add"
    assert events[0].new_items == (20,)
    assert events[0].index == 1


# ---------------------------------------------------------------------------
# Hub wiring
# ---------------------------------------------------------------------------


def test_hub_append_publishes_add_message() -> None:
    hub: MessageHub[CollectionChangedMessage[str]] = MessageHub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection("col", hub)
    msgs: list[CollectionChangedMessage[str]] = []
    hub.messages.subscribe(msgs.append)  # type: ignore[arg-type]

    sut.append("x")

    assert len(msgs) == 1
    assert msgs[0].action == "add"
    assert msgs[0].new_items == ("x",)
    assert msgs[0].index == 0


def test_hub_remove_publishes_remove_message() -> None:
    hub: MessageHub[CollectionChangedMessage[str]] = MessageHub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection("col", hub)
    sut.append("y")

    msgs: list[CollectionChangedMessage[str]] = []
    hub.messages.subscribe(msgs.append)  # type: ignore[arg-type]
    sut.remove("y")

    assert len(msgs) == 1
    assert msgs[0].action == "remove"
    assert msgs[0].old_items == ("y",)


def test_hub_setitem_publishes_replace_message() -> None:
    hub: MessageHub[CollectionChangedMessage[str]] = MessageHub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection("col", hub)
    sut.append("old")

    msgs: list[CollectionChangedMessage[str]] = []
    hub.messages.subscribe(msgs.append)  # type: ignore[arg-type]
    sut[0] = "new"

    assert len(msgs) == 1
    assert msgs[0].action == "replace"
    assert msgs[0].new_items == ("new",)
    assert msgs[0].old_items == ("old",)


def test_hub_clear_publishes_reset_message() -> None:
    hub: MessageHub[CollectionChangedMessage[str]] = MessageHub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection("col", hub)
    sut.append("a")

    msgs: list[CollectionChangedMessage[str]] = []
    hub.messages.subscribe(msgs.append)  # type: ignore[arg-type]
    sut.clear()

    assert len(msgs) == 1
    assert msgs[0].action == "reset"
    assert msgs[0].new_items == ()
    assert msgs[0].old_items == ()
    assert msgs[0].index == -1


def test_both_local_and_hub_observe_change() -> None:
    hub: MessageHub[CollectionChangedMessage[int]] = _hub()
    sut: ServicedObservableCollection[int] = ServicedObservableCollection("col", hub)

    local_saw: list[bool] = []
    hub_saw: list[bool] = []
    sut.on_collection_changed.subscribe(lambda _: local_saw.append(True))
    hub.messages.subscribe(lambda _: hub_saw.append(True))  # type: ignore[arg-type]

    sut.append(42)

    assert local_saw == [True]
    assert hub_saw == [True]


# ---------------------------------------------------------------------------
# Large-N stress
# ---------------------------------------------------------------------------


def test_stress_10k_appends_and_clear() -> None:
    hub: MessageHub[CollectionChangedMessage[int]] = _hub()
    sut: ServicedObservableCollection[int] = ServicedObservableCollection("stress", hub)
    hub_count: list[int] = [0]
    hub.messages.subscribe(lambda _: hub_count.__setitem__(0, hub_count[0] + 1))  # type: ignore[arg-type]

    n = 10_000
    for i in range(n):
        sut.append(i)
    sut.clear()

    assert len(sut) == 0
    assert hub_count[0] == n + 1  # n adds + 1 reset


# ---------------------------------------------------------------------------
# Default name
# ---------------------------------------------------------------------------


def test_default_name_is_non_empty() -> None:
    sut: ServicedObservableCollection[int] = ServicedObservableCollection()
    assert sut.name
    assert isinstance(sut.name, str)


# ---------------------------------------------------------------------------
# del / __delitem__
# ---------------------------------------------------------------------------


def test_delitem_emits_remove_event() -> None:
    sut: ServicedObservableCollection[int] = ServicedObservableCollection()
    sut.append(10)
    sut.append(20)
    events: list[CollectionChangedMessage[int]] = []
    sut.on_collection_changed.subscribe(events.append)

    del sut[0]

    assert len(events) == 1
    assert events[0].action == "remove"
    assert events[0].old_items == (10,)
    assert events[0].index == 0
    assert list(sut) == [20]


def test_remove_nonexistent_raises_value_error() -> None:
    sut: ServicedObservableCollection[int] = ServicedObservableCollection()
    with pytest.raises(ValueError):
        sut.remove(999)

"""Unit tests for ObservableDictionary[TKey1, TKey2, TValue].

Conformance-level tests live in tests/conformance/.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.collections import ObservableDictionary
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# Basic CRUD — no subscribers
# ---------------------------------------------------------------------------


def test_add_increments_count() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("b", 2, 2.0)
    assert sut.count == 2


def test_add_duplicate_key_raises_key_error() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    with pytest.raises(KeyError):
        sut.add("a", 1, 9.9)


def test_remove_existing_entry_returns_true_and_decrements_count() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    assert sut.remove("a", 1) is True
    assert sut.count == 0


def test_remove_missing_entry_returns_false() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    assert sut.remove("x", 99) is False


def test_contains_key_true_after_add_false_after_remove() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    assert sut.contains_key("a", 1)
    sut.remove("a", 1)
    assert not sut.contains_key("a", 1)


def test_get_raises_key_error_when_absent() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(KeyError):
        sut.get("missing", 99)


def test_setitem_adds_entry_when_not_present() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut["a", 1] = 5.5
    assert sut.contains_key("a", 1)
    assert sut.get("a", 1) == pytest.approx(5.5)


def test_setitem_replaces_value_when_present() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut["a", 1] = 9.9
    assert sut.get("a", 1) == pytest.approx(9.9)
    assert sut.count == 1


def test_getitem_returns_correct_value() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 42.0)
    assert sut["a", 1] == pytest.approx(42.0)


def test_delitem_removes_entry() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    del sut["a", 1]
    assert not sut.contains_key("a", 1)


def test_delitem_raises_key_error_when_absent() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(KeyError):
        del sut["missing", 99]


def test_clear_empties_dictionary_and_key_views() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("b", 2, 2.0)
    sut.clear()
    assert sut.count == 0
    assert sut.keys1.count == 0
    assert sut.keys2.count == 0


# ---------------------------------------------------------------------------
# Null-key guard
# ---------------------------------------------------------------------------


def test_none_key1_raises_type_error() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(TypeError):
        sut.add(None, 1, 0.0)  # type: ignore[arg-type]


def test_none_key2_raises_type_error() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(TypeError):
        sut.add("a", None, 0.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Distinct-key views
# ---------------------------------------------------------------------------


def test_keys1_contains_distinct_key1_values() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("a", 2, 2.0)
    sut.add("b", 3, 3.0)
    assert sut.keys1.count == 2
    assert any(k == "a" for k in sut.keys1)
    assert any(k == "b" for k in sut.keys1)


def test_keys2_contains_distinct_key2_values() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("b", 1, 2.0)
    sut.add("c", 2, 3.0)
    assert sut.keys2.count == 2
    assert any(k == 1 for k in sut.keys2)
    assert any(k == 2 for k in sut.keys2)


def test_keys1_drops_key_when_last_entry_removed() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("a", 2, 2.0)
    sut.remove("a", 1)
    assert any(k == "a" for k in sut.keys1)  # still has ("a", 2)
    sut.remove("a", 2)
    assert not any(k == "a" for k in sut.keys1)


def test_keys1_insertion_order_preserved() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("c", 1, 1.0)
    sut.add("a", 2, 2.0)
    sut.add("b", 3, 3.0)
    assert list(sut.keys1) == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def test_on_item_added_fires_on_add_with_correct_payload() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    events: list[tuple[str, int, float]] = []
    sut.on_item_added.subscribe(lambda e: events.append(e))

    sut.add("a", 1, 7.7)

    assert len(events) == 1
    assert events[0][0] == "a"
    assert events[0][1] == 1
    assert events[0][2] == pytest.approx(7.7)


def test_on_item_removed_fires_on_remove_with_correct_payload() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 7.7)
    events: list[tuple[str, int, float]] = []
    sut.on_item_removed.subscribe(lambda e: events.append(e))

    sut.remove("a", 1)

    assert len(events) == 1
    assert events[0][0] == "a"
    assert events[0][1] == 1
    assert events[0][2] == pytest.approx(7.7)


def test_on_item_replaced_fires_on_setitem_with_old_and_new_values() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    events: list[tuple[str, int, float, float]] = []
    sut.on_item_replaced.subscribe(lambda e: events.append(e))

    sut["a", 1] = 9.9

    assert len(events) == 1
    assert events[0][2] == pytest.approx(9.9)
    assert events[0][3] == pytest.approx(1.0)


def test_on_reset_fires_on_clear() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    resets: list[bool] = []
    sut.on_reset.subscribe(lambda _: resets.append(True))

    sut.clear()

    assert len(resets) == 1


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------


def test_iter_yields_all_entries_in_insertion_order() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.1)
    sut.add("b", 2, 2.2)
    sut.add("c", 3, 3.3)

    entries = list(sut)
    assert len(entries) == 3
    assert entries[0] == ("a", 1, pytest.approx(1.1))
    assert entries[1] == ("b", 2, pytest.approx(2.2))
    assert entries[2] == ("c", 3, pytest.approx(3.3))


def test_len_returns_entry_count() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("b", 2, 2.0)
    assert len(sut) == 2


def test_in_operator_returns_true_for_present_key() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    assert ("a", 1) in sut


def test_in_operator_returns_false_for_absent_key() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    assert ("missing", 99) not in sut


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_keys1_observable_list_fires_item_added_on_new_key1() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    added: list[str] = []
    sut.keys1.on_item_added.subscribe(lambda e: added.append(e[0]))

    sut.add("x", 1, 1.0)
    sut.add("x", 2, 2.0)  # same Key1 — no new event

    assert added == ["x"]


def test_keys2_observable_list_fires_item_removed_when_last_entry_for_key2_removed() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 5, 1.0)
    removed: list[int] = []
    sut.keys2.on_item_removed.subscribe(lambda e: removed.append(e[0]))

    sut.remove("a", 5)

    assert removed == [5]


def test_clear_does_not_fire_individual_item_removed_events() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("b", 2, 2.0)
    sut.add("c", 3, 3.0)
    fired: list[str] = []
    sut.on_item_removed.subscribe(lambda _: fired.append("removed"))

    sut.clear()

    assert fired == [], "Clear must NOT fire per-entry on_item_removed events"


def test_items_method_yields_triples_in_insertion_order() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut.add("b", 2, 2.0)
    result = list(sut.items())
    assert result[0] == ("a", 1, pytest.approx(1.0))
    assert result[1] == ("b", 2, pytest.approx(2.0))


# ---------------------------------------------------------------------------
# try_get_value
# ---------------------------------------------------------------------------


def test_try_get_value_returns_true_and_value_when_present() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 42.0)
    found, value = sut.try_get_value("a", 1)
    assert found is True
    assert value == pytest.approx(42.0)


def test_try_get_value_returns_false_and_none_when_absent() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    found, value = sut.try_get_value("missing", 99)
    assert found is False
    assert value is None


def test_try_get_value_raises_for_none_key1() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(TypeError):
        sut.try_get_value(None, 1)  # type: ignore[arg-type]


def test_try_get_value_raises_for_none_key2() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(TypeError):
        sut.try_get_value("a", None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Hub injection
# ---------------------------------------------------------------------------


def test_hub_injection_publishes_add_message_on_add() -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    sut: ObservableDictionary[str, int, float] = ObservableDictionary(hub=hub)
    received: list[CollectionChangedMessage[object]] = []
    hub.messages.subscribe(lambda m: received.append(m))  # type: ignore[arg-type]

    sut.add("a", 1, 42.0)

    assert len(received) == 1
    assert isinstance(received[0], CollectionChangedMessage)
    assert received[0].action == "add"
    assert received[0].sender_object is sut


def test_hub_injection_publishes_remove_message_on_remove() -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    sut: ObservableDictionary[str, int, float] = ObservableDictionary(hub=hub)
    sut.add("a", 1, 1.0)
    received: list[CollectionChangedMessage[object]] = []
    hub.messages.subscribe(lambda m: received.append(m))  # type: ignore[arg-type]

    sut.remove("a", 1)

    assert len(received) == 1
    assert received[0].action == "remove"


def test_hub_injection_publishes_replace_message_on_setitem() -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    sut: ObservableDictionary[str, int, float] = ObservableDictionary(hub=hub)
    sut.add("a", 1, 1.0)
    received: list[CollectionChangedMessage[object]] = []
    hub.messages.subscribe(lambda m: received.append(m))  # type: ignore[arg-type]

    sut["a", 1] = 9.9

    assert len(received) == 1
    assert received[0].action == "replace"


def test_hub_injection_publishes_reset_message_on_clear() -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    sut: ObservableDictionary[str, int, float] = ObservableDictionary(hub=hub)
    sut.add("a", 1, 1.0)
    received: list[CollectionChangedMessage[object]] = []
    hub.messages.subscribe(lambda m: received.append(m))  # type: ignore[arg-type]

    sut.clear()

    assert len(received) == 1
    assert received[0].action == "reset"


def test_hub_none_does_not_throw_on_any_mutation() -> None:
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("a", 1, 1.0)
    sut["a", 1] = 2.0
    sut.remove("a", 1)
    sut.add("b", 2, 3.0)
    sut.clear()


@pytest.mark.parametrize("key", [(None, 1), ("a", None)])
def test_none_key_raises_type_error_on_item_access_and_membership(
    key: tuple[object, object],
) -> None:
    d: ObservableDictionary[str, int, float] = ObservableDictionary()
    with pytest.raises(TypeError):
        d[key]  # type: ignore[index]
    with pytest.raises(TypeError):
        key in d  # noqa: B015


def test_dispose_completes_every_stream_when_an_observer_raises() -> None:
    d: ObservableDictionary[str, str, int] = ObservableDictionary()
    completed: list[str] = []

    def raise_on_completed() -> None:
        raise RuntimeError("observer")

    d.on_item_added.subscribe(on_completed=raise_on_completed)
    d.on_item_removed.subscribe(on_completed=lambda: completed.append("removed"))
    d.on_reset.subscribe(on_completed=lambda: completed.append("reset"))

    with pytest.raises(RuntimeError, match="observer"):
        d.dispose()

    assert completed == ["removed", "reset"]


def test_hub_add_index_is_captured_before_a_reentrant_add() -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    d: ObservableDictionary[str, str, int] = ObservableDictionary(hub)
    indices: dict[object, int] = {}

    def record(message: CollectionChangedMessage[object]) -> None:
        for item in message.new_items:
            indices[item] = message.index

    hub.messages.subscribe(record)

    def add_nested(entry: tuple[str, str, int]) -> None:
        if entry[0] == "a":
            d.add("b", "y", 2)

    d.on_item_added.subscribe(add_nested)
    d.add("a", "x", 1)

    assert indices == {("a", "x", 1): 0, ("b", "y", 2): 1}


@pytest.mark.parametrize("view", ["keys1", "keys2"])
def test_hub_add_index_is_captured_before_a_key_view_reentrant_add(view: str) -> None:
    # #733: a key-view subscriber runs before the hub publication.
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    d: ObservableDictionary[str, str, int] = ObservableDictionary(hub)
    indices: dict[object, int] = {}

    def record(message: CollectionChangedMessage[object]) -> None:
        for item in message.new_items:
            indices[item] = message.index

    hub.messages.subscribe(record)
    nested: list[bool] = []

    def add_nested(_: object) -> None:
        if not nested:
            nested.append(True)
            d.add("z", "z", 1)

    getattr(d, view).on_item_added.subscribe(add_nested)
    d.add("a", "a", 0)

    assert indices == {("a", "a", 0): 0, ("z", "z", 1): 1}


@pytest.mark.parametrize(
    ("nested", "expected"),
    [("remove", 0), ("clear", -1)],
)
def test_hub_add_index_follows_a_key_view_reentrant_remove_or_clear(
    nested: str, expected: int
) -> None:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    d: ObservableDictionary[str, str, int] = ObservableDictionary(hub)
    d.add("x", "x", 9)
    indices: dict[object, int] = {}

    def record(message: CollectionChangedMessage[object]) -> None:
        for item in message.new_items:
            indices[item] = message.index

    hub.messages.subscribe(record)
    done: list[bool] = []

    def mutate(_: object) -> None:
        if not done:
            done.append(True)
            if nested == "remove":
                d.remove("x", "x")
            else:
                d.clear()

    d.keys1.on_item_added.subscribe(mutate)
    d.add("a", "a", 0)

    assert indices == {("a", "a", 0): expected}


@pytest.mark.parametrize("view", ["keys1", "keys2"])
def test_key_views_keep_first_appearance_order_after_a_key_view_reentrant_add(
    view: str,
) -> None:
    # #772: an entry added from a key-view subscriber keeps both views in
    # first-appearance order.
    d: ObservableDictionary[str, int, str] = ObservableDictionary()
    nested: list[bool] = []

    def add_nested(_: object) -> None:
        if not nested:
            nested.append(True)
            d.add("b", 2, "nested")

    getattr(d, view).on_item_added.subscribe(add_nested)
    d.add("a", 1, "outer")

    assert list(d.keys1) == ["a", "b"]
    assert list(d.keys2) == [1, 2]


def test_keys2_contains_the_new_key2_when_keys1_notifies() -> None:
    d: ObservableDictionary[str, int, str] = ObservableDictionary()
    seen: list[list[int]] = []
    d.keys1.on_item_added.subscribe(lambda _: seen.append(list(d.keys2)))

    d.add("a", 1, "outer")

    assert seen == [[1]]


def _add_from_a_keys2_handler(
    d: ObservableDictionary[str, int, str], nested: Callable[[], object]
) -> None:
    """Run *nested* once, from the keys2 handler for key2 1, then add (a, 1)."""
    done: list[bool] = []

    def on_key2(event: tuple[int, int]) -> None:
        if not done and event[0] == 1:
            done.append(True)
            nested()

    d.keys2.on_item_added.subscribe(on_key2)
    d.add("a", 1, "outer")


def test_key_views_stay_empty_when_a_keys2_handler_removes_the_new_entry() -> None:
    d: ObservableDictionary[str, int, str] = ObservableDictionary()

    _add_from_a_keys2_handler(d, lambda: d.remove("a", 1))

    assert len(d) == 0
    assert list(d.keys1) == []
    assert list(d.keys2) == []


def test_keys1_lists_a_pending_key1_before_a_key_that_a_keys2_handler_adds() -> None:
    d: ObservableDictionary[str, int, str] = ObservableDictionary()
    d.add("x", 0, "first")

    def nested() -> None:
        d.add("c", 5, "nested")
        d.add("a", 3, "nested")

    _add_from_a_keys2_handler(d, nested)

    assert list(d.keys1) == ["x", "a", "c"]
    assert list(d.keys2) == [0, 1, 5, 3]


def test_keys1_keeps_its_order_when_a_keys2_handler_moves_a_key1_later() -> None:
    d: ObservableDictionary[str, int, str] = ObservableDictionary()
    d.add("x", 0, "first")
    d.add("y", 2, "second")

    def nested() -> None:
        d.add("x", 4, "nested")
        d.remove("x", 0)

    _add_from_a_keys2_handler(d, nested)

    assert list(d.keys1) == ["x", "y", "a"]
    assert list(d.keys2) == [2, 1, 4]


@pytest.mark.parametrize("view", ["keys1", "keys2"])
def test_key_views_match_the_entries_after_a_key_view_reset_handler_adds_during_clear(
    view: str,
) -> None:
    # #1075: an entry added from a key-view reset handler during clear keeps
    # both views equal to the keys of the remaining entries.
    d: ObservableDictionary[str, str, str] = ObservableDictionary()
    d.add("a", "a", "outer")
    done: list[bool] = []

    def add_nested(_: object) -> None:
        if not done:
            done.append(True)
            d.add("b", "b", "nested")

    getattr(d, view).on_reset.subscribe(add_nested)
    d.clear()

    assert list(d) == [("b", "b", "nested")]
    assert list(d.keys1) == ["b"]
    assert list(d.keys2) == ["b"]

    d.remove("b", "b")

    assert list(d) == []
    assert list(d.keys1) == []
    assert list(d.keys2) == []


@pytest.mark.parametrize(
    ("view", "nested", "keys1", "keys2"),
    [
        ("keys1", "add", ["b", "c", "a"], ["y", "z", "x"]),
        ("keys1", "remove", ["c"], ["z"]),
        ("keys2", "add", ["b", "c", "a"], ["y", "z", "x"]),
        ("keys2", "remove", ["c"], ["z"]),
    ],
)
def test_key_views_match_the_entries_after_a_key_view_handler_changes_them_during_remove(
    view: str, nested: str, keys1: list[str], keys2: list[str]
) -> None:
    # #1075: an entry added or removed from a key-view item-removed handler
    # during remove keeps both views equal to the distinct keys of the entries.
    # keys1 never lists a key twice, also while a subscriber runs.
    d: ObservableDictionary[str, str, str] = ObservableDictionary()
    d.add("a", "x", "outer")
    d.add("b", "y", "kept")
    d.add("c", "z", "kept")
    done: list[bool] = []

    def change_nested(_: object) -> None:
        if done:
            return
        done.append(True)
        if nested == "add":
            d.add("a", "x", "nested")
        else:
            d.remove("b", "y")

    getattr(d, view).on_item_removed.subscribe(change_nested)
    snapshots: list[list[str]] = []
    d.keys1.on_item_added.subscribe(lambda _: snapshots.append(list(d.keys1)))
    d.remove("a", "x")

    entries = [(k1, k2) for k1, k2, _ in d]
    assert list(dict.fromkeys(k1 for k1, _ in entries)) == keys1
    assert list(dict.fromkeys(k2 for _, k2 in entries)) == keys2
    assert list(d.keys1) == keys1
    assert list(d.keys2) == keys2
    assert all(len(set(keys)) == len(keys) for keys in snapshots)


def test_keys2_is_updated_when_keys1_notifies_a_remove_or_a_clear() -> None:
    # #1075: remove and clear update keys2 first, as add does, so a keys1
    # subscriber already reads the updated keys2.
    d: ObservableDictionary[str, str, str] = ObservableDictionary()
    d.add("a", "a", "first")
    d.add("b", "b", "second")
    seen: list[list[str]] = []
    d.keys1.on_item_removed.subscribe(lambda _: seen.append(list(d.keys2)))
    d.keys1.on_reset.subscribe(lambda _: seen.append(list(d.keys2)))

    d.remove("a", "a")
    d.clear()

    assert seen == [["b"], []]


@pytest.mark.parametrize("operation", ["remove", "clear"])
def test_key_views_stay_in_step_when_a_keys2_subscriber_raises(operation: str) -> None:
    # #1075: keys1 is updated even when a keys2 subscriber raises during the
    # keys2 notification, so a later add does not list a key twice.
    d: ObservableDictionary[str, str, str] = ObservableDictionary()
    d.add("a", "x", "first")
    failing = [True]

    def fail(_: object) -> None:
        if failing[0]:
            raise RuntimeError("keys2 subscriber failed")

    d.keys2.on_item_removed.subscribe(fail)
    d.keys2.on_reset.subscribe(fail)

    with pytest.raises(RuntimeError, match="keys2 subscriber failed"):
        if operation == "remove":
            d.remove("a", "x")
        else:
            d.clear()
    failing[0] = False

    assert list(d.keys1) == []
    d.add("a", "y", "again")
    assert list(d.keys1) == ["a"]
    d.remove("a", "y")
    assert list(d.keys1) == []
    assert list(d.keys2) == []
    assert len(d) == 0


def test_nan_key_is_one_axis_key_like_a_dict_key() -> None:
    sut: ObservableDictionary[float, str, int] = ObservableDictionary()
    nan = float("nan")

    sut.add(nan, "a", 1)
    sut.add(nan, "b", 2)
    assert sut.keys1.count == 1

    sut.remove(nan, "a")
    assert sut.keys1.count == 1
    sut.remove(nan, "b")
    assert sut.keys1.count == 0


def test_key_view_contains_a_nan_key_by_identity() -> None:
    sut: ObservableDictionary[float, str, int] = ObservableDictionary()
    nan = float("nan")
    sut.add(nan, "b", 1)

    assert nan in sut.keys1

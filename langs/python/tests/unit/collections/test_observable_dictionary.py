"""Unit tests for ObservableDictionary[TKey1, TKey2, TValue].

Conformance-level tests live in tests/conformance/.
"""

from __future__ import annotations

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

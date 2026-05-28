"""Conformance tests: COL-010..COL-015 + COL-022 — ObservableDictionary (multi-key).

Per spec/21-collections.md §4 and ADR-0025.
"""

from __future__ import annotations

import pytest

from vmx.collections import ObservableDictionary
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# COL-010 — insert and retrieve
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-010")
def test_COL_010_insert_and_retrieve() -> None:
    """COL-010: ObservableDictionary insert sets ContainsKey and indexer."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    added: list[tuple[str, int, float]] = []
    sut.on_item_added.subscribe(lambda e: added.append(e))

    sut.add("alpha", 1, 3.14)

    # contains_key is True after insert
    assert sut.contains_key("alpha", 1)

    # get() returns correct value
    assert sut.get("alpha", 1) == pytest.approx(3.14)

    # count incremented
    assert sut.count == 1

    # on_item_added fired with correct payload
    assert len(added) == 1
    assert added[0] == ("alpha", 1, pytest.approx(3.14))

    # keys1 contains the new Key1
    assert any(k == "alpha" for k in sut.keys1)

    # keys2 contains the new Key2
    assert any(k == 1 for k in sut.keys2)


# ---------------------------------------------------------------------------
# COL-011 — remove
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-011")
def test_COL_011_remove() -> None:
    """COL-011: ObservableDictionary Remove clears the entry and decrements Count."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("alpha", 1, 3.14)
    sut.add("alpha", 2, 2.72)  # same key1, different key2
    sut.add("beta", 1, 1.41)  # different key1, same key2

    removed: list[tuple[str, int, float]] = []
    sut.on_item_removed.subscribe(lambda e: removed.append(e))

    result = sut.remove("alpha", 1)

    # Return value is True
    assert result is True

    # Entry no longer present
    assert not sut.contains_key("alpha", 1)
    assert sut.count == 2

    # on_item_removed fired with correct payload
    assert len(removed) == 1
    assert removed[0][0] == "alpha"
    assert removed[0][1] == 1
    assert removed[0][2] == pytest.approx(3.14)

    # "alpha" still in keys1 (because ("alpha", 2) remains)
    assert any(k == "alpha" for k in sut.keys1)

    # key2=1 still in keys2 (because ("beta", 1) remains)
    assert any(k == 1 for k in sut.keys2)

    # Remove last entry using key2=2
    sut.remove("alpha", 2)
    assert not any(k == 2 for k in sut.keys2)

    # Remove last entry using key1="beta"
    sut.remove("beta", 1)
    assert not any(k == "beta" for k in sut.keys1)
    assert not any(k == 1 for k in sut.keys2)


# ---------------------------------------------------------------------------
# COL-012 — replace
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-012")
def test_COL_012_replace() -> None:
    """COL-012: Replacing an existing entry returns the new value without changing Count."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("alpha", 1, 3.14)

    added: list[str] = []
    removed: list[str] = []
    replaced: list[tuple[str, int, float, float]] = []

    sut.on_item_added.subscribe(lambda _: added.append("added"))
    sut.on_item_removed.subscribe(lambda _: removed.append("removed"))
    sut.on_item_replaced.subscribe(lambda e: replaced.append(e))

    # Setting via __setitem__ on an existing key pair triggers replace
    sut["alpha", 1] = 9.99

    # New value is accessible
    assert sut.get("alpha", 1) == pytest.approx(9.99)

    # Count unchanged
    assert sut.count == 1

    # on_item_replaced fired, NOT Added or Removed
    assert added == [], "Replace must NOT fire on_item_added"
    assert removed == [], "Replace must NOT fire on_item_removed"
    assert len(replaced) == 1
    k1, k2, new_v, old_v = replaced[0]
    assert k1 == "alpha"
    assert k2 == 1
    assert new_v == pytest.approx(9.99)
    assert old_v == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# COL-013 — distinct-key observable views
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-013")
def test_COL_013_distinct_key_observable_views_stay_in_sync() -> None:
    """COL-013: Keys1 and Keys2 observable views reflect distinct keys in insertion order."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()

    keys1_added: list[str] = []
    keys1_removed: list[str] = []
    sut.keys1.on_item_added.subscribe(lambda e: keys1_added.append(e[0]))
    sut.keys1.on_item_removed.subscribe(lambda e: keys1_removed.append(e[0]))

    keys2_added: list[int] = []
    keys2_removed: list[int] = []
    sut.keys2.on_item_added.subscribe(lambda e: keys2_added.append(e[0]))
    sut.keys2.on_item_removed.subscribe(lambda e: keys2_removed.append(e[0]))

    # First entry — both axes get new values
    sut.add("alpha", 1, 1.0)
    assert keys1_added == ["alpha"]
    assert keys2_added == [1]

    # Second entry with same Key1 — Keys1 must NOT fire again
    sut.add("alpha", 2, 2.0)
    assert len(keys1_added) == 1, "Key1='alpha' already present; no new Keys1 event"
    assert 2 in keys2_added

    # Entry with new Key1
    sut.add("beta", 1, 3.0)
    assert "beta" in keys1_added
    assert len(keys2_added) == 2, "Key2=1 already present; no new Keys2 event"

    # Remove ("alpha", 1) — "alpha" still alive via ("alpha", 2)
    sut.remove("alpha", 1)
    assert keys1_removed == [], "alpha still has entry (alpha,2)"

    # Remove ("alpha", 2) — "alpha" now gone
    sut.remove("alpha", 2)
    assert "alpha" in keys1_removed

    # Key2=2 disappeared when ("alpha",2) was removed
    assert 2 in keys2_removed


# ---------------------------------------------------------------------------
# COL-014 — enumeration order
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-014")
def test_COL_014_enumeration_order_is_insertion_order() -> None:
    """COL-014: Enumerating ObservableDictionary yields entries in insertion order."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("alpha", 1, 1.1)
    sut.add("beta", 2, 2.2)
    sut.add("gamma", 1, 3.3)
    sut.add("alpha", 2, 4.4)

    entries = list(sut)

    assert len(entries) == 4
    assert entries[0] == ("alpha", 1, pytest.approx(1.1))
    assert entries[1] == ("beta", 2, pytest.approx(2.2))
    assert entries[2] == ("gamma", 1, pytest.approx(3.3))
    assert entries[3] == ("alpha", 2, pytest.approx(4.4))


# ---------------------------------------------------------------------------
# COL-015 — clear empties key views
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-015")
def test_COL_015_clear_empties_key_views() -> None:
    """COL-015: Clear() resets Count to 0 and empties Keys1 and Keys2."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()
    sut.add("alpha", 1, 1.0)
    sut.add("beta", 2, 2.0)

    granular: list[str] = []

    sut.on_item_added.subscribe(lambda _: granular.append("added"))
    sut.on_item_removed.subscribe(lambda _: granular.append("removed"))

    reset_fired: list[bool] = []
    sut.on_reset.subscribe(lambda _: reset_fired.append(True))

    sut.clear()

    # Count drops to zero
    assert sut.count == 0

    # Keys1 and Keys2 are empty
    assert sut.keys1.count == 0
    assert sut.keys2.count == 0

    # on_reset fired exactly once
    assert len(reset_fired) == 1

    # No individual added/removed events fired during clear
    assert granular == [], "Clear must NOT fire per-entry on_item_removed events"


# ---------------------------------------------------------------------------
# COL-022 — ObservableDictionary hub publication
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COL-022")
def test_COL_022_hub_publication_mutations_publish_to_hub() -> None:
    """COL-022: ObservableDictionary mutations publish CollectionChangedMessage to hub."""
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    sut: ObservableDictionary[str, int, float] = ObservableDictionary(hub=hub)

    received: list[CollectionChangedMessage[object]] = []
    hub.messages.subscribe(lambda m: received.append(m))  # type: ignore[arg-type]

    # Add — publishes an "add" message
    sut.add("alpha", 1, 3.14)
    assert len(received) == 1
    msg = received[0]
    assert isinstance(msg, CollectionChangedMessage)
    assert msg.action == "add"
    assert msg.sender_object is sut

    received.clear()

    # Replace via __setitem__ — publishes a "replace" message
    sut["alpha", 1] = 9.99
    assert len(received) == 1
    assert received[0].action == "replace"

    received.clear()

    # Remove — publishes a "remove" message
    sut.remove("alpha", 1)
    assert len(received) == 1
    assert received[0].action == "remove"

    received.clear()

    # Clear — publishes a "reset" message
    sut.add("beta", 2, 2.72)
    received.clear()  # discard the Add from above
    sut.clear()
    assert len(received) == 1
    assert received[0].action == "reset"


@pytest.mark.conformance("COL-022")
def test_COL_022_no_hub_no_publication_no_errors() -> None:
    """COL-022 (no-hub path): ObservableDictionary with hub=None does not raise."""
    sut: ObservableDictionary[str, int, float] = ObservableDictionary()

    # All mutations must be silent (no hub, no errors)
    sut.add("x", 1, 1.0)
    sut["x", 1] = 2.0
    sut.remove("x", 1)
    sut.add("y", 2, 3.0)
    sut.clear()

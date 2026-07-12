"""Focused Python surface tests for KeyedServicedObservableCollection."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from vmx.collections.keyed_serviced_observable_collection import (
    KeyedServicedObservableCollection,
)
from vmx.messages.collection_changed import CollectionChangedMessage


@dataclass
class _Item:
    key: str


def _keyed() -> KeyedServicedObservableCollection[str, _Item]:
    return KeyedServicedObservableCollection(lambda candidate: candidate.key)


def test_integer_indices_follow_python_semantics_but_move_is_strict() -> None:
    sut = _keyed()
    a, b = _Item("a"), _Item("b")
    sut.extend([a, b])
    events: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(events.append)

    assert sut.replace(-1, _Item("c")) is b
    assert events[-1].index == 1
    assert sut.remove_at(-1).key == "c"
    assert events[-1].index == 1
    sut.insert(-100, b)
    assert list(sut) == [b, a]
    assert events[-1].index == 0
    sut.insert(100, _Item("c"))
    assert events[-1].index == 2

    for source, destination in ((-1, 0), (0, -1), (3, 0), (0, 3)):
        with pytest.raises(IndexError):
            sut.move(source, destination)


def test_extended_slice_shape_failure_and_unhashable_keys_are_atomic() -> None:
    sut = _keyed()
    a, b, c = _Item("a"), _Item("b"), _Item("c")
    sut.extend([a, b, c])
    events: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(events.append)

    with pytest.raises(ValueError):
        sut[::2] = [_Item("x")]
    assert list(sut) == [a, b, c]
    assert events == []

    bad = KeyedServicedObservableCollection[list[str], _Item](lambda candidate: [candidate.key])
    with pytest.raises(TypeError):
        bad.append(a)
    assert list(bad) == []


def test_slice_deletion_repairs_index_and_emits_one_reset() -> None:
    sut = _keyed()
    a, b, c, d = (_Item(key) for key in "abcd")
    sut.extend([a, b, c, d])
    events: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(events.append)

    del sut[1::2]

    assert list(sut) == [a, c]
    assert sut.get("b") is None
    assert sut.get("d") is None
    assert sut.get("c") is c
    assert [message.action for message in events] == ["reset"]


def test_public_exports_are_available() -> None:
    from vmx import KeyedServicedObservableCollection as RootExport
    from vmx.collections import KeyedServicedObservableCollection as CollectionExport

    assert RootExport is KeyedServicedObservableCollection
    assert CollectionExport is KeyedServicedObservableCollection


class _ProbeKey:
    def __init__(self, value: str) -> None:
        self.value = value
        self.hash_calls = 0
        self.equality_calls = 0

    def __hash__(self) -> int:
        self.hash_calls += 1
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        self.equality_calls += 1
        return isinstance(other, _ProbeKey) and self.value == other.value


@dataclass
class _ProbeItem:
    key: _ProbeKey


def test_append_and_present_upsert_do_not_scan_or_rehash_unrelated_memberships() -> None:
    projections = 0

    def key_of(candidate: _ProbeItem) -> _ProbeKey:
        nonlocal projections
        projections += 1
        return candidate.key

    sut = KeyedServicedObservableCollection[_ProbeKey, _ProbeItem](key_of)
    existing = [_ProbeKey(str(index)) for index in range(64)]
    sut.extend(_ProbeItem(key) for key in existing)
    for key in existing:
        key.hash_calls = key.equality_calls = 0
    projections = 0

    appended_key = _ProbeKey("appended")
    sut.append(_ProbeItem(appended_key))

    assert projections == 1
    assert all(key.hash_calls == key.equality_calls == 0 for key in existing)
    assert appended_key.hash_calls <= 3

    projections = 0
    for key in (*existing, appended_key):
        key.hash_calls = key.equality_calls = 0
    replacement_key = _ProbeKey("32")
    replacement = _ProbeItem(replacement_key)

    assert sut.upsert(replacement) is False

    assert projections == 1
    assert sut[32] is replacement
    assert all(
        key.hash_calls == key.equality_calls == 0
        for index, key in enumerate(existing)
        if index != 32
    )
    assert existing[32].hash_calls <= 2
    assert replacement_key.hash_calls <= 3

    # Present-key replacement recaptures the projected equal key object rather
    # than leaving the former key object inside the dict.
    existing[32].value = "retired"
    assert sut.get(replacement_key) is replacement


def test_reverse_is_atomic_uses_captured_keys_and_has_documented_noops() -> None:
    projections = 0

    def key_of(candidate: _Item) -> str:
        nonlocal projections
        projections += 1
        return candidate.key

    sut = KeyedServicedObservableCollection[str, _Item](key_of)
    events: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(events.append)

    sut.reverse()
    only = _Item("only")
    sut.append(only)
    events.clear()
    projections = 0
    sut.reverse()
    assert list(sut) == [only]
    assert projections == 0
    assert events == []

    a, b = _Item("a"), _Item("b")
    sut.replace_all([a, b, only])
    events.clear()
    projections = 0
    sut.reverse()

    assert list(sut) == [only, b, a]
    assert sut.get("only") is only
    assert sut.get("b") is b
    assert sut.get("a") is a
    assert projections == 0
    assert [message.action for message in events] == ["reset"]

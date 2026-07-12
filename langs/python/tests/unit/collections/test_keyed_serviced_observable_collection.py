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

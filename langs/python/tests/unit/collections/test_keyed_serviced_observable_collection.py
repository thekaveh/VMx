"""Focused Python surface tests for KeyedServicedObservableCollection."""

from __future__ import annotations

from collections.abc import Callable, Iterator
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


def test_empty_slice_delete_and_assign_emit_nothing() -> None:
    sut = _keyed()
    sut.extend([_Item("a"), _Item("b")])
    events: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(events.append)

    del sut[1:1]
    sut[1:1] = []

    assert events == []
    assert [item.key for item in sut] == ["a", "b"]


# ---------------------------------------------------------------------------
# extend and += are atomic (#1321, ADR-0214, spec/21 §2.10)
# ---------------------------------------------------------------------------


class _Hub:
    def __init__(self) -> None:
        self.messages: list[CollectionChangedMessage[int]] = []

    def send(self, message: CollectionChangedMessage[int]) -> None:
        self.messages.append(message)


def _int_keyed(
    key_of: Callable[[int], int] = lambda value: value,
) -> tuple[KeyedServicedObservableCollection[int, int], list[CollectionChangedMessage[int]], _Hub]:
    hub = _Hub()
    sut: KeyedServicedObservableCollection[int, int] = KeyedServicedObservableCollection(
        key_of, hub=hub
    )
    sut.append(1)
    sut.append(3)
    hub.messages.clear()
    local: list[CollectionChangedMessage[int]] = []
    sut.on_collection_changed.subscribe(local.append)
    return sut, local, hub


def _assert_unchanged(
    sut: KeyedServicedObservableCollection[int, int],
    local: list[CollectionChangedMessage[int]],
    hub: _Hub,
) -> None:
    assert list(sut) == [1, 3]
    assert (sut.get(1), sut.get(3), sut.get(5), sut.get(7)) == (1, 3, None, None)
    assert (sut.contains_key(1), sut.contains_key(3), sut.contains_key(5)) == (True, True, False)
    assert local == []
    assert hub.messages == []


def _iadd(sut: KeyedServicedObservableCollection[int, int], values: list[int]) -> None:
    sut += values


@pytest.mark.parametrize(
    ("operation", "values"),
    [
        ("extend", [5, 5]),
        ("iadd", [5, 5]),
        ("extend", [5, 3]),
        ("iadd", [5, 3]),
    ],
)
def test_extend_and_iadd_with_a_duplicate_key_change_nothing(
    operation: str, values: list[int]
) -> None:
    sut, local, hub = _int_keyed()

    with pytest.raises(ValueError):
        if operation == "extend":
            sut.extend(values)
        else:
            _iadd(sut, values)

    _assert_unchanged(sut, local, hub)


class _ProjectorError(Exception):
    pass


class _IterationError(Exception):
    pass


def test_extend_projector_failure_propagates_and_changes_nothing() -> None:
    def key_of(value: int) -> int:
        if value == 7:
            raise _ProjectorError
        return value

    sut, local, hub = _int_keyed(key_of)

    with pytest.raises(_ProjectorError):
        sut.extend([5, 7])

    _assert_unchanged(sut, local, hub)


def test_extend_iteration_failure_propagates_and_changes_nothing() -> None:
    def values() -> Iterator[int]:
        yield 5
        raise _IterationError

    sut, local, hub = _int_keyed()

    with pytest.raises(_IterationError):
        sut.extend(values())

    _assert_unchanged(sut, local, hub)


@pytest.mark.parametrize("operation", ["extend", "iadd"])
def test_extend_success_emits_one_reset_on_each_channel(operation: str) -> None:
    sut, local, hub = _int_keyed()

    if operation == "extend":
        sut.extend([5, 7])
    else:
        _iadd(sut, [5, 7])

    assert list(sut) == [1, 3, 5, 7]
    assert (sut.get(5), sut.get(7)) == (5, 7)
    assert [message.action for message in local] == ["reset"]
    assert [message.action for message in hub.messages] == ["reset"]


def test_extend_with_empty_input_emits_nothing() -> None:
    sut, local, hub = _int_keyed()

    sut.extend([])

    _assert_unchanged(sut, local, hub)

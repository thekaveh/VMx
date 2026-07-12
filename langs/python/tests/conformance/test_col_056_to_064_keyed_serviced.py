"""Conformance tests: COL-056..COL-064 — keyed serviced collection."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from vmx.collections.keyed_serviced_observable_collection import (
    KeyedServicedObservableCollection,
)
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


@dataclass(eq=False)
class _Item:
    key: str
    value: str = ""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Item) and self.value == other.value


def _item(key: str, value: str = "") -> _Item:
    return _Item(key, value or key)


def _observed(
    *items: _Item,
) -> tuple[
    KeyedServicedObservableCollection[str, _Item],
    list[CollectionChangedMessage[_Item]],
    list[CollectionChangedMessage[_Item]],
]:
    hub: MessageHub[CollectionChangedMessage[_Item]] = MessageHub()
    sut = KeyedServicedObservableCollection[str, _Item](lambda candidate: candidate.key, hub)
    for candidate in items:
        sut.append(candidate)
    local: list[CollectionChangedMessage[_Item]] = []
    external: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(local.append)
    hub.messages.subscribe(external.append)  # type: ignore[arg-type]
    return sut, local, external


@pytest.mark.conformance("COL-056")
def test_COL_056_lookup_uses_captured_keys_and_preserves_order() -> None:
    projections = 0

    def key_of(candidate: _Item) -> str:
        nonlocal projections
        projections += 1
        return candidate.key

    a, b, c = _item("a"), _item("b"), _item("c")
    sut = KeyedServicedObservableCollection[str, _Item](key_of)
    sut.extend([a, b, c])
    events: list[CollectionChangedMessage[_Item]] = []
    sut.on_collection_changed.subscribe(events.append)

    assert sut.get("a") is a
    assert sut.get("b") is b
    assert sut.get("c") is c
    assert sut.get("missing") is None
    assert sut.contains_key("a") is True
    assert sut.contains_key("missing") is False
    assert projections == 3
    assert sut[1] is b
    assert sut[:] == [a, b, c]
    assert list(sut) == [a, b, c]

    b.key = "renamed"
    assert sut.get("b") is b
    assert sut.get("renamed") is None
    assert projections == 3
    assert events == []


@pytest.mark.conformance("COL-057")
def test_COL_057_duplicate_and_projection_failures_are_atomic() -> None:
    a, b = _item("a"), _item("b")
    sut, local, external = _observed(a, b)

    with pytest.raises(ValueError):
        sut.append(_item("a", "duplicate"))
    with pytest.raises(ValueError):
        sut.insert(1, _item("b", "duplicate"))
    with pytest.raises(ValueError):
        sut.replace(0, _item("b", "duplicate"))
    with pytest.raises(ValueError):
        sut.replace_all([_item("x"), _item("x")])
    with pytest.raises(ValueError):
        sut[0:0] = [_item("b", "duplicate")]

    assert list(sut) == [a, b]
    assert sut.get("a") is a
    assert sut.get("b") is b
    assert local == external == []

    projection_error = RuntimeError("projection failed")

    def key_of(candidate: _Item) -> str:
        if candidate.key == "bad":
            raise projection_error
        return candidate.key

    failing = KeyedServicedObservableCollection[str, _Item](key_of)
    failing.append(a)
    failures: list[CollectionChangedMessage[_Item]] = []
    failing.on_collection_changed.subscribe(failures.append)
    for operation in (
        lambda: failing.append(_item("bad")),
        lambda: failing.insert(0, _item("bad")),
        lambda: failing.replace(0, _item("bad")),
        lambda: failing.replace_all([_item("ok"), _item("bad")]),
        lambda: failing.upsert(_item("bad")),
        lambda: failing.__setitem__(slice(0, 1), [_item("bad")]),
    ):
        with pytest.raises(RuntimeError, match="projection failed"):
            operation()

    assert list(failing) == [a]
    assert failing.get("a") is a
    assert failures == []


@pytest.mark.conformance("COL-058")
def test_COL_058_upsert_adds_or_replaces_at_the_stable_position() -> None:
    a, b, c = _item("a"), _item("b"), _item("c")
    b2 = _item("b", "b2")
    sut, local, external = _observed(a, b)

    assert sut.upsert(c) is True
    assert sut.upsert(b2) is False
    assert sut.upsert(b2) is False

    assert list(sut) == [a, b2, c]
    assert sut.get("b") is b2
    assert [message.action for message in local] == ["add", "replace", "replace"]
    assert external == local
    assert local[0].new_items == (c,)
    assert local[0].index == local[0].new_index == 2
    assert local[1].old_items == (b,)
    assert local[1].new_items == (b2,)
    assert local[1].index == local[1].old_index == local[1].new_index == 1
    assert local[2].old_items == local[2].new_items == (b2,)


@pytest.mark.conformance("COL-059")
def test_COL_059_keyed_delete_reports_success_and_pre_removal_position() -> None:
    a, b, c = _item("a"), _item("b"), _item("c")
    sut, local, external = _observed(a, b, c)

    assert sut.delete("b") is True
    assert list(sut) == [a, c]
    assert sut.get("b") is None
    assert sut.get("c") is c
    assert len(local) == 1
    assert external == local
    assert local[0].action == "remove"
    assert local[0].old_items == (b,)
    assert local[0].index == local[0].old_index == 1
    assert local[0].new_index == -1

    assert sut.delete("missing") is False
    assert len(local) == len(external) == 1


@pytest.mark.conformance("COL-060")
def test_COL_060_removal_and_explicit_rekey_keep_the_index_synchronized() -> None:
    a = _item("a", "equal")
    equal_a = _item("a2", "equal")
    b, c = _item("b"), _item("c")
    sut, local, _ = _observed(a, equal_a, b, c)

    sut.remove(_item("ignored", "equal"))
    assert sut.remove_at(1) is b
    assert list(sut) == [equal_a, c]
    assert sut.get("a") is None
    assert sut.get("b") is None
    assert sut.get("a2") is equal_a
    assert sut.get("c") is c

    equal_a.key = "rekeyed"
    assert sut.replace(0, equal_a) is equal_a
    assert sut.get("a2") is None
    assert sut.get("rekeyed") is equal_a
    assert local[-1].action == "replace"
    with pytest.raises(ValueError):
        sut.replace(0, _item("c"))
    assert sut.get("rekeyed") is equal_a

    same = _item("old")
    duplicated = KeyedServicedObservableCollection[str, _Item](lambda candidate: candidate.key)
    duplicated.append(same)
    same.key = "new"
    assert duplicated.upsert(same) is True
    assert list(duplicated) == [same, same]
    assert duplicated.get("old") is same
    assert duplicated.get("new") is same


@pytest.mark.conformance("COL-061")
def test_COL_061_replace_all_preflights_and_handles_self_input() -> None:
    a, b = _item("a"), _item("b")
    x, y = _item("x"), _item("y")
    sut, local, external = _observed(a, b)

    sut.replace_all([x, y])
    sut.replace_all(sut)
    assert list(sut) == [x, y]
    assert [message.action for message in local] == ["reset", "reset"]
    assert external == local

    def failing_input() -> Iterator[_Item]:
        yield _item("z")
        raise RuntimeError("iteration failed")

    with pytest.raises(ValueError):
        sut.replace_all([_item("z"), _item("z")])
    with pytest.raises(RuntimeError, match="iteration failed"):
        sut.replace_all(failing_input())
    assert list(sut) == [x, y]
    assert sut.get("x") is x
    assert sut.get("y") is y
    assert len(local) == len(external) == 2

    empty = KeyedServicedObservableCollection[str, _Item](lambda candidate: candidate.key)
    events: list[CollectionChangedMessage[_Item]] = []
    empty.on_collection_changed.subscribe(events.append)
    empty.replace_all([])
    assert events == []


class _LifecycleItem:
    def __init__(self, key: str) -> None:
        self.key = key
        self.calls: list[str] = []
        self.parent: object | None = None

    def construct(self) -> None:
        self.calls.append("construct")

    def destruct(self) -> None:
        self.calls.append("destruct")

    def dispose(self) -> None:
        self.calls.append("dispose")


@pytest.mark.conformance("COL-062")
def test_COL_062_slice_move_clear_and_conveniences_preserve_invariants_and_ownership() -> None:
    a, old_b, c = _LifecycleItem("a"), _LifecycleItem("b"), _LifecycleItem("c")
    replacement = _LifecycleItem("b")
    hub: MessageHub[CollectionChangedMessage[_LifecycleItem]] = MessageHub()
    sut = KeyedServicedObservableCollection[str, _LifecycleItem](
        lambda candidate: candidate.key, hub
    )
    sut.extend([a, old_b, c])
    local: list[CollectionChangedMessage[_LifecycleItem]] = []
    external: list[CollectionChangedMessage[_LifecycleItem]] = []
    sut.on_collection_changed.subscribe(local.append)
    hub.messages.subscribe(external.append)  # type: ignore[arg-type]

    sut[1:2] = [replacement]
    assert list(sut) == [a, replacement, c]
    assert sut.get("b") is replacement
    assert local[-1].action == "reset"

    before = list(sut)
    with pytest.raises(ValueError):
        sut[1:1] = [_LifecycleItem("a")]
    with pytest.raises(ValueError):
        sut[1:2] = [_LifecycleItem("c"), _LifecycleItem("c")]
    with pytest.raises(ValueError):
        sut[::2] = [_LifecycleItem("x"), _LifecycleItem("x")]
    assert list(sut) == before
    assert len(local) == len(external) == 1

    del sut[1:2]
    assert list(sut) == [a, c]
    assert sut.get("b") is None
    assert local[-1].action == "reset"
    sut.move(1, 0)
    assert list(sut) == [c, a]
    assert sut.get("a") is a
    assert sut.get("c") is c
    sut.reverse()
    assert list(sut) == [a, c]
    assert local[-1].action == "reset"
    assert sut.pop() is c
    assert list(sut) == [a]
    before_noop = len(local)
    sut.reverse()
    assert len(local) == before_noop
    sut.move(0, 0)
    sut.clear()
    sut.clear()
    assert len(sut) == 0
    assert sut.contains_key("c") is False
    assert external == local
    assert all(candidate.calls == [] for candidate in (a, old_b, c, replacement))
    assert all(candidate.parent is None for candidate in (a, old_b, c, replacement))


@pytest.mark.conformance("COL-063")
def test_COL_063_delivery_is_local_before_hub_and_respects_hub_transactions() -> None:
    hub: MessageHub[CollectionChangedMessage[_Item]] = MessageHub()
    sut = KeyedServicedObservableCollection[str, _Item](lambda candidate: candidate.key, hub)
    deliveries: list[tuple[str, str, list[str], bool]] = []
    sut.on_collection_changed.subscribe(
        lambda message: deliveries.append(
            ("local", message.action, [candidate.key for candidate in sut], sut.contains_key("a"))
        )
    )
    hub.messages.subscribe(  # type: ignore[arg-type]
        lambda message: deliveries.append(
            ("hub", message.action, [candidate.key for candidate in sut], sut.contains_key("a"))
        )
    )

    sut.append(_item("a"))
    assert deliveries == [
        ("local", "add", ["a"], True),
        ("hub", "add", ["a"], True),
    ]
    deliveries.clear()

    with hub.batch():
        sut.append(_item("b"))
        sut.delete("a")
        assert deliveries == [
            ("local", "add", ["a", "b"], True),
            ("local", "remove", ["b"], False),
        ]
    assert deliveries == [
        ("local", "add", ["a", "b"], True),
        ("local", "remove", ["b"], False),
        ("hub", "add", ["b"], False),
        ("hub", "remove", ["b"], False),
    ]


@pytest.mark.conformance("COL-064")
def test_COL_064_reentrant_mutation_preserves_consistency_and_partial_order() -> None:
    hub: MessageHub[CollectionChangedMessage[_Item]] = MessageHub()
    sut = KeyedServicedObservableCollection[str, _Item](lambda candidate: candidate.key, hub)
    order: list[str] = []
    nested = False

    def record_local(message: CollectionChangedMessage[_Item]) -> None:
        nonlocal nested
        key = (message.new_items or message.old_items)[0].key
        order.append(f"local:{key}")
        assert all(sut.get(candidate.key) is candidate for candidate in sut)
        if not nested:
            nested = True
            sut.append(_item("nested"))

    def record_hub(message: CollectionChangedMessage[_Item]) -> None:
        key = (message.new_items or message.old_items)[0].key
        order.append(f"hub:{key}")
        assert sut.get("outer") is not None
        assert sut.get("nested") is not None

    sut.on_collection_changed.subscribe(record_local)
    hub.messages.subscribe(record_hub)  # type: ignore[arg-type]
    sut.append(_item("outer"))

    assert order.index("local:outer") < order.index("hub:outer")
    assert order.index("local:nested") < order.index("hub:nested")
    assert [candidate.key for candidate in sut] == ["outer", "nested"]

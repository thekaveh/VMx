"""Conformance tests: COL-048..COL-055 — serviced collection parity."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from vmx.collections.serviced_observable_collection import ServicedObservableCollection
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.services.message_hub import MessageHub


def _observed_collection(
    values: list[object],
) -> tuple[
    ServicedObservableCollection[object],
    list[CollectionChangedMessage[object]],
    list[CollectionChangedMessage[object]],
]:
    hub: MessageHub[CollectionChangedMessage[object]] = MessageHub()
    sut: ServicedObservableCollection[object] = ServicedObservableCollection(hub)
    for value in values:
        sut.append(value)
    local: list[CollectionChangedMessage[object]] = []
    external: list[CollectionChangedMessage[object]] = []
    sut.on_collection_changed.subscribe(local.append)
    hub.messages.subscribe(external.append)  # type: ignore[arg-type]
    return sut, local, external


def _assert_remove(message: CollectionChangedMessage[object], item: object, index: int) -> None:
    assert message.action == "remove"
    assert message.new_items == ()
    assert message.old_items == (item,)
    assert message.index == index
    assert message.old_index == index
    assert message.new_index == -1


@pytest.mark.conformance("COL-048")
def test_COL_048_value_removal_targets_first_duplicate_and_stays_list_like() -> None:
    sut, local, external = _observed_collection(["a", "b", "a"])

    result = sut.remove("a")

    assert result is None
    assert list(sut) == ["b", "a"]
    assert len(local) == len(external) == 1
    _assert_remove(local[0], "a", 0)
    _assert_remove(external[0], "a", 0)

    with pytest.raises(ValueError):
        sut.remove("missing")

    assert list(sut) == ["b", "a"]
    assert len(local) == len(external) == 1


@pytest.mark.conformance("COL-049")
def test_COL_049_indexed_removal_resolves_negative_indices_and_is_atomic() -> None:
    for requested_index in (1, -2):
        sut, local, external = _observed_collection(["a", "b", "c"])

        removed = sut.remove_at(requested_index)

        assert removed == "b"
        assert list(sut) == ["a", "c"]
        assert len(local) == len(external) == 1
        _assert_remove(local[0], "b", 1)
        _assert_remove(external[0], "b", 1)

    sut, local, external = _observed_collection(["a", "b", "c"])

    for invalid_index in (-4, 3):
        with pytest.raises(IndexError):
            sut.remove_at(invalid_index)

    assert list(sut) == ["a", "b", "c"]
    assert local == external == []


@pytest.mark.conformance("COL-050")
def test_COL_050_named_replacement_reports_positions_and_is_atomic() -> None:
    sut, local, external = _observed_collection(["a", "b"])

    old = sut.replace(-1, "c")

    assert old == "b"
    assert list(sut) == ["a", "c"]
    assert len(local) == len(external) == 1
    for message in (local[0], external[0]):
        assert message.action == "replace"
        assert message.new_items == ("c",)
        assert message.old_items == ("b",)
        assert message.index == 1
        assert message.old_index == 1
        assert message.new_index == 1

    assert sut.replace(1, "c") == "c"
    assert len(local) == len(external) == 2
    assert local[-1].action == external[-1].action == "replace"

    for invalid_index in (-3, 2):
        with pytest.raises(IndexError):
            sut.replace(invalid_index, "x")

    assert list(sut) == ["a", "c"]
    assert len(local) == len(external) == 2


@pytest.mark.conformance("COL-051")
def test_COL_051_replace_all_snapshots_and_emits_one_reset_when_effective() -> None:
    sut, local, external = _observed_collection(["a", "b"])

    sut.replace_all(sut)

    assert list(sut) == ["a", "b"]
    assert len(local) == len(external) == 1
    for message in (local[0], external[0]):
        assert message.action == "reset"
        assert message.new_items == message.old_items == ()
        assert message.index == message.old_index == message.new_index == -1

    def failing_values() -> Iterator[str]:
        yield "new"
        raise RuntimeError("iteration failed")

    with pytest.raises(RuntimeError, match="iteration failed"):
        sut.replace_all(failing_values())

    assert list(sut) == ["a", "b"]
    assert len(local) == len(external) == 1

    live_view = (item.upper() for item in sut)
    sut.replace_all(live_view)
    assert list(sut) == ["A", "B"]
    assert len(local) == len(external) == 2

    empty, empty_local, empty_external = _observed_collection([])
    empty.replace_all([])
    assert list(empty) == []
    assert empty_local == empty_external == []


@pytest.mark.conformance("COL-052")
def test_COL_052_move_preserves_identity_and_reports_precise_positions() -> None:
    a, b, c = object(), object(), object()

    for source, destination, expected in (
        (0, 2, [b, c, a]),
        (2, 0, [c, a, b]),
    ):
        sut, local, external = _observed_collection([a, b, c])

        sut.move(source, destination)

        assert list(sut) == expected
        assert len(local) == len(external) == 1
        moved = [a, b, c][source]
        assert sut[destination] is moved
        for message in (local[0], external[0]):
            assert message.action == "move"
            assert message.new_items == (moved,)
            assert message.old_items == (moved,)
            assert message.index == destination
            assert message.old_index == source
            assert message.new_index == destination


@pytest.mark.conformance("COL-053")
def test_COL_053_move_noop_and_bounds_are_strict_and_atomic() -> None:
    sut, local, external = _observed_collection(["a", "b", "c"])

    sut.move(1, 1)

    assert list(sut) == ["a", "b", "c"]
    assert local == external == []

    for source, destination in ((-1, 0), (0, -1), (3, 0), (0, 3)):
        with pytest.raises(IndexError):
            sut.move(source, destination)

    assert list(sut) == ["a", "b", "c"]
    assert local == external == []


@pytest.mark.conformance("COL-054")
def test_COL_054_every_mutation_is_local_before_hub_with_final_state_visible() -> None:
    hub: MessageHub[CollectionChangedMessage[str]] = MessageHub()
    sut: ServicedObservableCollection[str] = ServicedObservableCollection(hub)
    deliveries: list[tuple[str, str, list[str]]] = []
    sut.on_collection_changed.subscribe(
        lambda message: deliveries.append(("local", message.action, list(sut)))
    )
    hub.messages.subscribe(  # type: ignore[arg-type]
        lambda message: deliveries.append(("hub", message.action, list(sut)))
    )

    operations = (
        (lambda: sut.append("a"), "add", ["a"]),
        (lambda: sut.append("b"), "add", ["a", "b"]),
        (lambda: sut.remove("a"), "remove", ["b"]),
        (lambda: sut.replace(0, "c"), "replace", ["c"]),
        (lambda: sut.replace_all(["x", "y"]), "reset", ["x", "y"]),
        (lambda: sut.move(0, 1), "move", ["y", "x"]),
        (sut.clear, "reset", []),
    )

    for operation, action, expected_state in operations:
        before = len(deliveries)
        operation()
        assert deliveries[before:] == [
            ("local", action, expected_state),
            ("hub", action, expected_state),
        ]


class _LifecycleProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def construct(self) -> None:
        self.calls.append("construct")

    def destruct(self) -> None:
        self.calls.append("destruct")

    def dispose(self) -> None:
        self.calls.append("dispose")


@pytest.mark.conformance("COL-055")
def test_COL_055_clear_noop_and_all_mutations_preserve_caller_ownership() -> None:
    hub: MessageHub[CollectionChangedMessage[_LifecycleProbe]] = MessageHub()
    sut: ServicedObservableCollection[_LifecycleProbe] = ServicedObservableCollection(hub)
    local: list[CollectionChangedMessage[_LifecycleProbe]] = []
    external: list[CollectionChangedMessage[_LifecycleProbe]] = []
    sut.on_collection_changed.subscribe(local.append)
    hub.messages.subscribe(external.append)  # type: ignore[arg-type]

    sut.clear()
    assert local == external == []

    probes = [_LifecycleProbe() for _ in range(7)]
    for probe in probes[:4]:
        sut.append(probe)
    local.clear()
    external.clear()

    sut.remove(probes[0])
    sut.remove_at(0)
    sut.replace(0, probes[4])
    sut.replace_all(probes[5:])
    sut.move(0, 1)
    sut.clear()

    assert [message.action for message in local] == [
        "remove",
        "remove",
        "replace",
        "reset",
        "move",
        "reset",
    ]
    assert [message.action for message in external] == [
        "remove",
        "remove",
        "replace",
        "reset",
        "move",
        "reset",
    ]
    for message in (local[-1], external[-1]):
        assert message.new_items == message.old_items == ()
        assert message.index == message.old_index == message.new_index == -1
    assert all(probe.calls == [] for probe in probes)

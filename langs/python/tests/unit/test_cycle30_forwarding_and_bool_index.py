"""Cycle-30 regressions: full ForwardingCompositeVM delegation and bool indexes.

* ForwardingCompositeVM must delegate the whole wrapped-composite surface
  (spec/09 §0/§2, FWD-001), including the membership-source members that
  ``AggregateChangeStream`` consumes and the parent child-selection surface.
* ``bool`` is an ``int`` subclass; it must not be accepted as an index by
  ``move`` / ``remove_at`` (it previously leaked ``True``/``False`` into
  collection-changed payloads).
"""

from __future__ import annotations

from typing import Any

import pytest
import reactivex as rx

from vmx import (
    AggregateChangeStream,
    ComponentVM,
    CompositeVM,
    ForwardingCompositeVM,
    GroupVM,
    KeyedServicedObservableCollection,
    MessageHub,
    RxDispatcher,
    ServicedObservableCollection,
)


def _leaf(name: str) -> ComponentVM:
    return ComponentVM.builder().name(name).with_null_services().build()


def _composite(*children: ComponentVM) -> CompositeVM[ComponentVM]:
    composite: CompositeVM[ComponentVM] = (
        CompositeVM[ComponentVM]
        .builder()
        .name("parent")
        .children(lambda: list(children))
        .services(MessageHub(), RxDispatcher.immediate())
        .build()
    )
    composite.construct()
    return composite


# ── ForwardingCompositeVM delegation ─────────────────────────────────────────


def test_forwarding_composite_is_an_aggregate_change_stream_source() -> None:
    a, b = _leaf("a"), _leaf("b")
    inner = _composite(a, b)
    fwd = ForwardingCompositeVM(inner)

    assert fwd.snapshot() == (a, b)
    pulses: list[int] = []
    subscription = fwd.subscribe_membership(lambda: pulses.append(1))
    c = _leaf("c")
    fwd.append(c)
    assert pulses == [1]
    subscription.dispose()

    stream: AggregateChangeStream[ComponentVM] = AggregateChangeStream(
        fwd, lambda _item: rx.never()
    )
    reasons: list[Any] = []
    stream.observe().subscribe(lambda change: reasons.append(change.reason))
    del fwd[0]
    assert inner.snapshot() == (b, c)
    assert reasons  # the membership change reached the stream through the wrapper


def test_forwarding_composite_delegates_sequence_and_child_selection_surface() -> None:
    a, b = _leaf("a"), _leaf("b")
    inner = _composite(a, b)
    fwd = ForwardingCompositeVM(inner)

    assert fwd.index(b) == 1
    with pytest.raises(ValueError):
        fwd.index(_leaf("absent"))
    target: list[ComponentVM | None] = [None, None, None]
    fwd.copy_to(target, 1)  # type: ignore[arg-type]
    assert target == [None, a, b]

    assert fwd.supports_child_selection is inner.supports_child_selection is True
    fwd.select_child(b)
    assert inner.current is b
    assert fwd.current_child is b
    fwd.deselect_child(b)
    assert inner.current is None
    assert fwd.current_child is None


# ── bool indexes are rejected before any mutation ────────────────────────────


def test_composite_move_and_remove_at_reject_bool() -> None:
    a, b = _leaf("a"), _leaf("b")
    inner = _composite(a, b)
    events: list[object] = []
    inner.on_collection_changed.subscribe(events.append)
    with pytest.raises(TypeError):
        inner.move(True, 0)
    with pytest.raises(TypeError):
        inner.move(0, True)
    with pytest.raises(TypeError):
        inner.remove_at(True)
    with pytest.raises(TypeError):
        del inner[False]
    assert inner.snapshot() == (a, b)
    assert events == []


def test_group_move_and_remove_at_reject_bool() -> None:
    a, b = _leaf("a"), _leaf("b")
    group: GroupVM[ComponentVM] = GroupVM.create(
        name="grp",
        children=lambda: [a, b],
        hub=MessageHub(),
        dispatcher=RxDispatcher.immediate(),
    )
    group.construct()
    events: list[object] = []
    group.on_collection_changed.subscribe(events.append)
    with pytest.raises(TypeError):
        group.move(True, 0)
    with pytest.raises(TypeError):
        group.move(0, True)
    with pytest.raises(TypeError):
        group.remove_at(True)
    assert group.snapshot() == (a, b)
    assert events == []


def test_serviced_collection_move_remove_replace_reject_bool() -> None:
    sut: ServicedObservableCollection[str] = ServicedObservableCollection()
    sut.extend(["x", "y"])
    events: list[object] = []
    sut.on_collection_changed.subscribe(events.append)
    with pytest.raises(TypeError):
        sut.move(True, 0)
    with pytest.raises(TypeError):
        sut.move(0, True)
    with pytest.raises(TypeError):
        sut.remove_at(True)
    with pytest.raises(TypeError):
        sut.replace(True, "z")
    assert list(sut) == ["x", "y"]
    assert events == []


def test_keyed_collection_move_remove_replace_reject_bool() -> None:
    sut: KeyedServicedObservableCollection[str, str] = KeyedServicedObservableCollection(
        lambda item: item
    )
    sut.extend(["x", "y"])
    events: list[object] = []
    sut.on_collection_changed.subscribe(events.append)
    with pytest.raises(TypeError):
        sut.move(True, 0)
    with pytest.raises(TypeError):
        sut.move(0, True)
    with pytest.raises(TypeError):
        sut.remove_at(True)
    with pytest.raises(TypeError):
        sut.replace(False, "z")
    assert list(sut) == ["x", "y"]
    assert events == []

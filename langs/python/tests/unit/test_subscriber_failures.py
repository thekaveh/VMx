"""ADR-0191 regressions — a failing subscriber stops no delivery and detaches nothing.

These cover the channels that the conformance IDs do not name: the hub
helpers, the container channels and their completion, the completion of the
stream-fed channels, a failing item supplier, and the command decorators.
Per spec/03-messages.md §3.6 (#1304, #1311).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest
from reactivex import operators as ops
from reactivex.internal.exceptions import DisposedException
from reactivex.subject import BehaviorSubject, Subject

from vmx._subscriber_failures import FanOutSubject
from vmx.capabilities.searchable_state import SearchableState
from vmx.commands.composite_command import CompositeCommand
from vmx.commands.decorator_command import DecoratorCommand
from vmx.commands.relay_command import RelayCommand
from vmx.components.component_vm import ComponentVM
from vmx.composites.composite_vm import CompositeVM
from vmx.groups.builders import GroupVMBuilder
from vmx.messages.collection_changed import CollectionChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.messages.property_value_changed import property_value_changed_messages_for
from vmx.messages.when_property_changed import when_property_changed
from vmx.properties import from_one
from vmx.services.message_hub import MessageHub
from vmx.services.null_dispatcher import NULL_DISPATCHER


class SubscriberError(Exception):
    """Raised by the failing subscriber."""


def _failing(record: list[Any]) -> Callable[[Any], None]:
    def handler(value: Any) -> None:
        record.append(value)
        raise SubscriberError

    return handler


def _raise_completion() -> None:
    raise SubscriberError


# ---------------------------------------------------------------------------
# FanOutSubject
# ---------------------------------------------------------------------------


def test_fan_out_subject_delivers_to_every_observer_then_raises_first_failure() -> None:
    subject: FanOutSubject[int] = FanOutSubject()
    first = SubscriberError("first")
    seen: list[str] = []

    def a(_: int) -> None:
        seen.append("a")
        raise first

    def b(_: int) -> None:
        seen.append("b")
        raise SubscriberError("second")

    subject.subscribe(a)
    subject.subscribe(b)
    subject.subscribe(lambda _: seen.append("c"))

    with pytest.raises(SubscriberError) as raised:
        subject.on_next(1)

    assert raised.value is first
    assert seen == ["a", "b", "c"]
    with pytest.raises(SubscriberError):
        subject.on_next(2)
    assert seen == ["a", "b", "c"] * 2


def test_fan_out_subject_completes_every_observer_then_raises_first_failure() -> None:
    subject: FanOutSubject[int] = FanOutSubject()
    completed: list[str] = []
    subject.subscribe(on_completed=_raise_completion)
    subject.subscribe(on_completed=lambda: completed.append("b"))

    with pytest.raises(SubscriberError):
        subject.on_completed()

    assert completed == ["b"]
    assert subject.observers == []


# ---------------------------------------------------------------------------
# Hub helpers (spec/03 §7.1, §7.2)
# ---------------------------------------------------------------------------


_HELPERS: dict[str, Callable[[MessageHub[Any], object], Any]] = {
    "property_value_changed_messages_for": lambda hub, sender: property_value_changed_messages_for(
        hub, sender, "real"
    ),
    "when_property_changed": lambda hub, sender: when_property_changed(hub, sender, "real"),
    "when_property_changed_many": lambda hub, sender: when_property_changed(
        hub, sender, "real", "other"
    ),
}


class _Sender:
    real = 7


@pytest.mark.parametrize("helper", list(_HELPERS))
def test_helper_subscriber_failure_keeps_every_subscriber_attached(
    helper: str, caplog: pytest.LogCaptureFixture
) -> None:
    hub: MessageHub[Any] = MessageHub()
    sender = _Sender()
    a_seen: list[object] = []
    b_seen: list[object] = []
    stream = _HELPERS[helper](hub, sender)
    stream.subscribe(_failing(a_seen))
    stream.subscribe(b_seen.append)

    with caplog.at_level(logging.ERROR):
        hub.send(PropertyChangedMessage.create(sender, "sender", "real"))
        hub.send(PropertyChangedMessage.create(sender, "sender", "real"))

    assert len(a_seen) == 2
    assert len(b_seen) == 2
    hub.dispose()


# ---------------------------------------------------------------------------
# CompositeVM and GroupVM local channel (spec/01 §1.4, chapter 06)
# ---------------------------------------------------------------------------


def _child(name: str) -> ComponentVM:
    return ComponentVM.builder().name(name).services(MessageHub(), NULL_DISPATCHER).build()


def _composite(hub: MessageHub[Any]) -> tuple[Any, Callable[[str], None]]:
    container: CompositeVM[ComponentVM] = (
        CompositeVM.builder()
        .name("composite")
        .services(hub, NULL_DISPATCHER)
        .children(lambda: [])
        .build()
    )
    container.construct()
    return container, lambda name: container.append(_child(name))


def _group(hub: MessageHub[Any]) -> tuple[Any, Callable[[str], None]]:
    container: Any = (
        GroupVMBuilder().name("group").services(hub, NULL_DISPATCHER).children(lambda: []).build()
    )
    container.construct()
    return container, lambda name: container.add(_child(name))


_CONTAINERS: dict[str, Callable[[MessageHub[Any]], tuple[Any, Callable[[str], None]]]] = {
    "CompositeVM": _composite,
    "GroupVM": _group,
}


@pytest.mark.parametrize("kind", list(_CONTAINERS))
def test_container_failing_local_subscriber_does_not_stop_later_subscriber(kind: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    container, add = _CONTAINERS[kind](hub)
    order: list[str] = []
    hub.messages.subscribe(
        lambda m: order.append("hub") if isinstance(m, CollectionChangedMessage) else None
    )

    def failing(_: object) -> None:
        order.append("a")
        raise SubscriberError

    container.on_collection_changed.subscribe(failing)
    container.on_collection_changed.subscribe(lambda _: order.append("b"))

    with pytest.raises(SubscriberError):
        add("one")
    with pytest.raises(SubscriberError):
        add("two")

    assert len(container) == 2
    assert order == ["a", "b", "hub", "a", "b", "hub"]


@pytest.mark.parametrize("kind", list(_CONTAINERS))
def test_container_dispose_completes_every_observer(kind: str) -> None:
    container, _add = _CONTAINERS[kind](MessageHub())
    completed: list[str] = []
    container.on_collection_changed.subscribe(on_completed=_raise_completion)
    container.on_collection_changed.subscribe(on_completed=lambda: completed.append("b"))

    with pytest.raises(SubscriberError):
        container.dispose()

    assert completed == ["b"]
    # The failing observer does not skip the subject dispose (#1072).
    with pytest.raises(DisposedException):
        container.on_collection_changed.subscribe(on_completed=lambda: None)


# ---------------------------------------------------------------------------
# Completion of the stream-fed channels
# ---------------------------------------------------------------------------


def test_derived_property_dispose_completes_every_value_changed_observer() -> None:
    dp = from_one(BehaviorSubject(1), lambda x: x)
    completed: list[str] = []
    dp.value_changed.subscribe(on_completed=_raise_completion)
    dp.value_changed.subscribe(on_completed=lambda: completed.append("b"))

    with pytest.raises(SubscriberError):
        dp.dispose()

    assert completed == ["b"]


def test_searchable_state_dispose_completes_every_filtered_observer() -> None:
    state = SearchableState(items=lambda: ["a"], predicate=lambda _i, _t: True, debounce_seconds=0)
    completed: list[str] = []
    state.filtered.subscribe(on_completed=_raise_completion)
    state.filtered.subscribe(on_completed=lambda: completed.append("b"))

    with pytest.raises(SubscriberError):
        state.dispose()

    assert completed == ["b"]


def test_searchable_state_failing_item_supplier_keeps_last_snapshot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fail = False

    def items() -> list[str]:
        if fail:
            raise SubscriberError
        return ["apple", "banana"]

    state = SearchableState(items=items, predicate=lambda i, t: t in i, debounce_seconds=0)
    seen: list[list[str]] = []
    state.filtered.subscribe(seen.append)

    fail = True
    with caplog.at_level(logging.ERROR):
        state.search_term = "an"
        state.search()
    assert seen == [["apple", "banana"]]
    assert any(
        r.exc_info is not None and isinstance(r.exc_info[1], SubscriberError)
        for r in caplog.records
    )

    fail = False
    state.search()
    assert seen == [["apple", "banana"], ["banana"]]
    state.dispose()


# ---------------------------------------------------------------------------
# Command decorators forward under the same rule (ADR-0191 §2.2 item 4)
# ---------------------------------------------------------------------------


_WRAPPERS: dict[str, Callable[[RelayCommand], Any]] = {
    "DecoratorCommand": DecoratorCommand,
    "CompositeCommand": CompositeCommand,
}


@pytest.mark.parametrize("wrapper", list(_WRAPPERS))
def test_wrapped_command_failing_handler_does_not_stop_later_handler(
    wrapper: str, caplog: pytest.LogCaptureFixture
) -> None:
    trigger: Subject[int] = Subject()
    inner = RelayCommand.builder().triggers(trigger.pipe(ops.map(lambda _: None))).build()
    command = _WRAPPERS[wrapper](inner)
    a_seen: list[object] = []
    b_seen: list[object] = []
    command.can_execute_changed.subscribe(_failing(a_seen))
    command.can_execute_changed.subscribe(b_seen.append)

    with caplog.at_level(logging.ERROR):
        trigger.on_next(1)
        trigger.on_next(2)
    assert (len(a_seen), len(b_seen)) == (2, 2)

    with pytest.raises(SubscriberError):
        inner.raise_can_execute_changed()
    assert (len(a_seen), len(b_seen)) == (3, 3)

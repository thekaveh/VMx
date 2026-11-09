"""Conformance tests: COMP-050..COMP-052 — disposed children and silent refusals.

COMP-050: disposing the current child clears ``current`` (ADR-0189).
COMP-051: a selection while the composite is Destructing changes nothing
(ADR-0188).
COMP-052: a refused child ``select()`` or ``deselect()`` changes nothing and
raises nothing (ADR-0188).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.messages.construction_status_changed import ConstructionStatusChangedMessage
from vmx.messages.property_changed import PropertyChangedMessage
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

S = ConstructionStatus


def _child(
    hub: MessageHub[object],
    dispatcher: RxDispatcher,
    name: str,
    *,
    on_construct: Callable[[], None] | None = None,
    on_destruct: Callable[[], None] | None = None,
) -> ComponentVM:
    builder = ComponentVMBuilder().name(name).services(hub, dispatcher)
    if on_construct is not None:
        builder = builder.on_construct(on_construct)
    if on_destruct is not None:
        builder = builder.on_destruct(on_destruct)
    return builder.build()


def _attempt(errors: list[BaseException], action: Callable[[], object]) -> None:
    try:
        action()
    except BaseException as error:
        errors.append(error)


@pytest.mark.conformance("COMP-050")
def test_COMP_050_disposing_the_current_child_clears_current() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    a = _child(hub, dispatcher, "a")
    b = _child(hub, dispatcher, "b")
    changes: list[ComponentVM | None] = []
    p: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("p")
        .services(hub, dispatcher)
        .children(lambda: [a, b])
        .on_current_changed(changes.append)
        .build()
    )
    p.construct()
    p.current = a
    log: list[tuple[str, str]] = []

    def record(message: object) -> None:
        if isinstance(message, PropertyChangedMessage) and message.sender in (p, a):
            log.append((message.sender_name, message.property_name))
        elif isinstance(message, ConstructionStatusChangedMessage) and message.sender is a:
            log.append(("a", message.status.name))

    hub.messages.subscribe(record)
    changes.clear()

    a.dispose()

    assert p.current is None
    assert a.is_current is False
    assert log.count(("p", "current")) == 1
    assert changes == [None]
    disposed_at = log.index(("a", "DISPOSED"))
    assert ("a", "is_current") not in log[disposed_at:]
    assert p.can_select_component(a) is False
    with pytest.raises(ValueError, match="not a member"):
        p.current = a
    assert p.current is None

    p.current = b
    log.clear()

    p.dispose()

    assert b.status is S.DISPOSED
    assert ("p", "current") not in log


@pytest.mark.conformance("COMP-051")
def test_COMP_051_selection_while_destructing_changes_nothing() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    errors: list[BaseException] = []
    can_select_c: list[bool] = []
    changes: list[ComponentVM | None] = []

    def on_changed(value: ComponentVM | None) -> None:
        changes.append(value)
        if value is None and p.status is S.DESTRUCTING:
            _attempt(errors, lambda: setattr(p, "current", b))
            _attempt(errors, lambda: p.select_component(b))
            _attempt(errors, b.select)

    def b_destruct() -> None:
        _attempt(errors, lambda: setattr(p, "current", c))
        _attempt(errors, c.select)
        can_select_c.append(p.can_select_component(c))
        _attempt(errors, lambda: setattr(p, "current", a))
        _attempt(errors, lambda: setattr(p, "current", None))

    a = _child(hub, dispatcher, "a")
    b = _child(hub, dispatcher, "b", on_destruct=b_destruct)
    c = _child(hub, dispatcher, "c")
    p: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("p")
        .services(hub, dispatcher)
        .children(lambda: [a, b, c])
        .on_current_changed(on_changed)
        .build()
    )
    current_messages: list[PropertyChangedMessage] = []
    hub.messages.subscribe(
        lambda m: (
            current_messages.append(m)
            if isinstance(m, PropertyChangedMessage)
            and m.sender is p
            and m.property_name == "current"
            else None
        )
    )

    def run_and_check(operation: Callable[[], None], final: ConstructionStatus) -> None:
        errors.clear()
        can_select_c.clear()
        changes.clear()
        current_messages.clear()

        operation()

        assert errors == []
        assert p.status is final
        assert p.current is None
        assert can_select_c == [False]
        assert len(current_messages) == 1
        assert changes == [None]
        assert not (a.is_current or b.is_current or c.is_current)

    p.construct()
    p.current = a
    run_and_check(p.destruct, S.DESTRUCTED)
    assert [vm.status for vm in (a, b, c)] == [S.DESTRUCTED] * 3

    p.construct()
    p.current = a
    run_and_check(p.reconstruct, S.CONSTRUCTED)
    assert [vm.status for vm in (a, b, c)] == [S.CONSTRUCTED] * 3


@pytest.mark.conformance("COMP-052")
def test_COMP_052_refused_child_select_and_deselect_change_nothing() -> None:
    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    errors: list[BaseException] = []
    seen_in_callback: list[ComponentVM | None] = []

    def on_changed(value: ComponentVM | None) -> None:
        if value is c:
            _attempt(errors, p.dispose)
            _attempt(errors, a.select)
            seen_in_callback.append(p.current)

    a = _child(hub, dispatcher, "a")
    b = _child(hub, dispatcher, "b")
    c = _child(hub, dispatcher, "c")
    d = _child(hub, dispatcher, "d", on_construct=lambda: _attempt(errors, a.select))
    p: CompositeVM[ComponentVM] = (
        CompositeVMBuilder()
        .name("p")
        .services(hub, dispatcher)
        .auto_construct_on_add(True)
        .children(lambda: [])
        .on_current_changed(on_changed)
        .build()
    )
    p.construct()
    for child in (a, b, c):
        p.add(child)
    b.destruct()
    assert (a.status, b.status, c.status) == (S.CONSTRUCTED, S.DESTRUCTED, S.CONSTRUCTED)
    current_messages: list[object] = []
    hub.messages.subscribe(
        lambda m: (
            current_messages.append(m)
            if isinstance(m, PropertyChangedMessage)
            and m.sender is p
            and m.property_name == "current"
            else None
        )
    )

    _attempt(errors, b.select)
    _attempt(errors, a.deselect)
    _attempt(errors, lambda: p.add(d))

    assert errors == []
    assert p.current is None
    assert d.status is S.CONSTRUCTED
    assert current_messages == []

    p.current = c

    assert errors == []
    assert seen_in_callback == [c]
    assert len(current_messages) == 1
    assert not a.is_current
    assert p.status is S.DISPOSED

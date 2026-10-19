"""spec/09 §1-2 (FWD-002/FWD-004): a ForwardingCompositeVM held by a parent
shares one ownership identity with the composite it wraps, so parent links,
``is_current``, and single-parent transfer reach it. Mirrors the C#
ForwardingCompositeMembershipTests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vmx import (
    CompositeVM,
    ConstructionStatus,
    ForwardingCompositeVM,
    MessageHub,
    RxDispatcher,
)


def _composite(
    name: str,
    on_construct: Callable[[], None] | None = None,
    on_destruct: Callable[[], None] | None = None,
) -> CompositeVM[Any]:
    builder = (
        CompositeVM[Any]
        .builder()
        .name(name)
        .services(MessageHub(), RxDispatcher.immediate())
        .children(lambda: [])
    )
    if on_construct is not None:
        builder = builder.on_construct(on_construct)
    if on_destruct is not None:
        builder = builder.on_destruct(on_destruct)
    return builder.build()


def test_selecting_decorator_marks_it_current() -> None:
    parent = _composite("parent")
    decorator: ForwardingCompositeVM[Any] = ForwardingCompositeVM(_composite("inner"))
    parent.construct()
    parent.add(decorator)
    decorator.construct()

    parent.current = decorator

    assert parent.current is decorator
    assert decorator.is_current
    assert decorator.can_deselect()

    parent.current = None
    assert not decorator.is_current
    assert decorator.can_select()

    decorator.select()
    assert parent.current is decorator
    assert decorator.is_current


def test_adding_decorator_to_second_parent_moves_it() -> None:
    first = _composite("first")
    second = _composite("second")
    decorator: ForwardingCompositeVM[Any] = ForwardingCompositeVM(_composite("inner"))

    first.add(decorator)
    second.add(decorator)

    assert len(first) == 0
    assert len(second) == 1


def test_decorator_and_wrapped_composite_are_one_ownership_identity() -> None:
    first = _composite("first")
    second = _composite("second")
    inner = _composite("inner")
    decorator: ForwardingCompositeVM[Any] = ForwardingCompositeVM(inner)

    first.add(decorator)
    second.add(inner)

    assert len(first) == 0
    assert len(second) == 1
    assert second[0] is inner


def test_parent_destruct_and_dispose_cascade_once() -> None:
    calls: list[str] = []
    inner = _composite(
        "inner",
        on_construct=lambda: calls.append("construct"),
        on_destruct=lambda: calls.append("destruct"),
    )
    decorator: ForwardingCompositeVM[Any] = ForwardingCompositeVM(inner)
    parent = _composite("parent")
    parent.add(decorator)

    parent.construct()
    parent.destruct()
    parent.dispose()

    assert calls == ["construct", "destruct"]
    assert inner.status is ConstructionStatus.DISPOSED


def test_forwarding_component_background_child_is_joined_by_its_composite() -> None:
    from reactivex.testing import TestScheduler

    from vmx import ComponentVM, CompositeVM, ForwardingComponentVM, MessageHub, RxDispatcher
    from vmx.lifecycle import ConstructionStatus

    foreground, background = TestScheduler(), TestScheduler()
    dispatcher = RxDispatcher(foreground, background)
    hub = MessageHub()
    leaf = ComponentVM.builder().name("leaf").services(hub, dispatcher).background(True).build()
    decorator = ForwardingComponentVM(leaf)
    composite = (
        CompositeVM.builder()
        .name("c")
        .services(hub, dispatcher)
        .children(lambda: [decorator])
        .build()
    )

    composite.construct()
    background.start()
    foreground.start()

    assert composite.status is ConstructionStatus.CONSTRUCTED
    assert leaf.status is ConstructionStatus.CONSTRUCTED

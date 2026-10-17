"""Members documented as inert after dispose stay inert (disposal contract)."""

from __future__ import annotations

import pytest
from reactivex.subject import BehaviorSubject

from vmx import ComponentVM, CompositeVM, MessageHub, RxDispatcher
from vmx.messages import Message
from vmx.properties import from_sources


def test_a_disposed_child_does_not_change_its_parents_selection() -> None:
    hub: MessageHub[Message] = MessageHub()
    kids = [
        ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build()
        for name in ("a", "b")
    ]
    parent = (
        CompositeVM[ComponentVM]
        .builder()
        .name("p")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: kids)
        .build()
    )
    parent.construct()
    parent.select_component(kids[0])
    kids[0].dispose()
    kids[1].dispose()

    assert kids[0].can_deselect() is False
    kids[0].deselect()
    kids[1].select()

    assert parent.current is kids[0]


def test_a_disposed_derived_property_rejects_writes() -> None:
    writes: list[int] = []
    source: BehaviorSubject[int] = BehaviorSubject(1)
    prop = from_sources(
        source,
        transform=lambda value: value,
        can_set=lambda _: True,
        set_action=writes.append,
    )
    prop.dispose()

    assert prop.can_set(7) is False
    with pytest.raises(ValueError, match="can_set"):
        prop.set_value(7)
    assert writes == []

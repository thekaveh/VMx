"""A raising ``on_current_changed`` must not lose the collection event."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx import ComponentVM, CompositeVM, MessageHub, RxDispatcher
from vmx.messages import Message


def _set_up() -> tuple[CompositeVM[ComponentVM], list[str]]:
    hub: MessageHub[Message] = MessageHub()
    kids = [
        ComponentVM.builder().name(name).services(hub, RxDispatcher.immediate()).build()
        for name in ("a", "b")
    ]
    armed = [False]

    def on_current_changed(_: ComponentVM | None) -> None:
        if armed[0]:
            raise RuntimeError("callback")

    composite = (
        CompositeVM[ComponentVM]
        .builder()
        .name("c")
        .services(hub, RxDispatcher.immediate())
        .children(lambda: kids)
        .on_current_changed(on_current_changed)
        .build()
    )
    composite.construct()
    composite.select_component(kids[0])
    armed[0] = True
    actions: list[str] = []
    composite.on_collection_changed.subscribe(lambda event: actions.append(event.action))
    return composite, actions


def _replace_first(composite: CompositeVM[ComponentVM]) -> None:
    hub: MessageHub[Message] = MessageHub()
    composite[0] = ComponentVM.builder().name("z").services(hub, RxDispatcher.immediate()).build()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda c: c.remove_at(0), ["remove"]),
        (lambda c: c.remove(c[0]), ["remove"]),
        (lambda c: c.clear(), ["reset"]),
        (_replace_first, ["remove", "add"]),
    ],
)
def test_collection_event_survives_a_raising_on_current_changed(
    mutate: Callable[[CompositeVM[ComponentVM]], None], expected: list[str]
) -> None:
    composite, actions = _set_up()

    with pytest.raises(RuntimeError, match="callback"):
        mutate(composite)

    assert actions == expected
    assert composite.current is None

"""A None child in a selection call gets the documented error (spec/06 §3.1, #1467).

A None value is never a child, so ``can_select_component`` returns False and
``select_component`` raises its predicate error instead of ``AttributeError``.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx.components.builders import ComponentVMBuilder
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


def _setup() -> tuple[Any, ComponentVM]:
    hub = MessageHub()
    dispatcher = RxDispatcher.immediate()
    a = ComponentVMBuilder().name("a").services(hub, dispatcher).build()
    b = ComponentVMBuilder().name("b").services(hub, dispatcher).build()
    composite: Any = (
        CompositeVMBuilder().name("c").services(hub, dispatcher).children(lambda: [a, b]).build()
    )
    composite.construct()
    return composite, a


def test_can_select_component_of_none_returns_false() -> None:
    composite, _ = _setup()

    assert composite.can_select_component(None) is False


def test_select_component_of_none_raises_the_predicate_error() -> None:
    composite, a = _setup()
    composite.current = a

    with pytest.raises(ValueError, match="can_select_component returned False"):
        composite.select_component(None)

    assert composite.current is a


def test_deselect_component_of_none_with_a_current_child_raises() -> None:
    composite, a = _setup()
    composite.current = a

    with pytest.raises(ValueError, match="not the current selection"):
        composite.deselect_component(None)

    assert composite.current is a


def test_deselect_component_of_none_with_no_current_child_does_nothing() -> None:
    composite, _ = _setup()

    composite.deselect_component(None)

    assert composite.current is None

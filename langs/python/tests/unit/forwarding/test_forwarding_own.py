"""Owned resources registered through a forwarding decorator (spec/09 §1, ADR-0151).

FWD-005 covers the catalog scenario; these tests cover the composite decorator
and the shared LIFO order.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vmx.components.builders import ComponentVMOfBuilder
from vmx.composites.builders import CompositeVMBuilder
from vmx.forwarding.component import ForwardingComponentVM
from vmx.forwarding.composite import ForwardingCompositeVM
from vmx.lifecycle.status import ConstructionStatus
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


class _OwningComponentDecorator(ForwardingComponentVM[str]):
    def register(self, resource: Callable[[], None]) -> None:
        self._own(resource)


class _OwningCompositeDecorator(ForwardingCompositeVM[Any]):
    def register(self, resource: Callable[[], None]) -> None:
        self._own(resource)


def _make_inner() -> Any:
    return ComponentVMOfBuilder[str]().name("inner").model("m").with_null_services().build()


def test_composite_decorator_registers_on_the_wrapped_composite() -> None:
    composite = (
        CompositeVMBuilder[Any]()
        .name("composite")
        .services(MessageHub(), RxDispatcher.immediate())
        .children(lambda: ())
        .build()
    )
    decorator = _OwningCompositeDecorator(composite)
    released: list[str] = []
    decorator.register(lambda: released.append("r1"))
    decorator.register(lambda: released.append("r2"))

    decorator.dispose()

    assert composite.status is ConstructionStatus.DISPOSED
    assert released == ["r2", "r1"]
    decorator.register(lambda: released.append("r3"))
    assert released == ["r2", "r1", "r3"]


def test_registration_after_decorator_disposal_is_released_once() -> None:
    decorator = _OwningComponentDecorator(_make_inner())
    released: list[str] = []
    decorator.dispose()

    decorator.register(lambda: released.append("late"))
    decorator.dispose()

    assert released == ["late"]


def test_decorator_and_wrapped_registrations_share_one_lifo_order() -> None:
    inner = _make_inner()
    decorator = _OwningComponentDecorator(inner)
    released: list[str] = []
    inner._own(lambda: released.append("inner-1"))
    decorator.register(lambda: released.append("decorator"))
    inner._own(lambda: released.append("inner-2"))

    decorator.dispose()

    assert released == ["inner-2", "decorator", "inner-1"]

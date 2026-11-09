"""An unknown ``destruct_order`` value raises ``TypeError`` (#1397).

``_in_destruct_order`` reverses only for ``ChildOrder.REVERSE``; any other
value would silently give insertion order. The builders and the container
constructors therefore reject a value that is not a ``ChildOrder`` member,
including its string value ``"reverse"``.
"""

from __future__ import annotations

from typing import Any

import pytest

from vmx import ChildOrder
from vmx.composites.builders import CompositeVMBuilder, CompositeVMOfBuilder
from vmx.composites.composite_vm import CompositeVM, CompositeVMOf
from vmx.groups.builders import GroupVMBuilder
from vmx.groups.group_vm import GroupVM
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

HUB: MessageHub[object] = MessageHub()
DISPATCHER = RxDispatcher.immediate()
UNKNOWN: Any = "reverse"


@pytest.mark.parametrize(
    "builder",
    [GroupVMBuilder, CompositeVMBuilder, CompositeVMOfBuilder],
    ids=["GroupVMBuilder", "CompositeVMBuilder", "CompositeVMOfBuilder"],
)
def test_builder_rejects_unknown_order(builder: Any) -> None:
    with pytest.raises(TypeError, match="ChildOrder"):
        builder().destruct_order(UNKNOWN)


def test_group_create_rejects_unknown_order() -> None:
    with pytest.raises(TypeError, match="ChildOrder"):
        GroupVM.create(
            name="g", hub=HUB, dispatcher=DISPATCHER, children=lambda: [], destruct_order=UNKNOWN
        )


def test_composite_create_rejects_unknown_order() -> None:
    with pytest.raises(TypeError, match="ChildOrder"):
        CompositeVM.create(
            name="c", hub=HUB, dispatcher=DISPATCHER, children=lambda: [], destruct_order=UNKNOWN
        )


def test_group_constructor_rejects_unknown_order() -> None:
    with pytest.raises(TypeError, match="ChildOrder"):
        GroupVM(name="g", hub=HUB, dispatcher=DISPATCHER, destruct_order=UNKNOWN)


def test_composite_constructor_rejects_unknown_order() -> None:
    with pytest.raises(TypeError, match="ChildOrder"):
        CompositeVM(name="c", hub=HUB, dispatcher=DISPATCHER, destruct_order=UNKNOWN)


def test_composite_of_constructor_rejects_unknown_order() -> None:
    with pytest.raises(TypeError, match="ChildOrder"):
        CompositeVMOf(
            name="c",
            hub=HUB,
            dispatcher=DISPATCHER,
            children_models=lambda: [],
            child_model_to_child_vm=lambda model: model,
            destruct_order=UNKNOWN,
        )


@pytest.mark.parametrize("order", list(ChildOrder))
def test_members_are_accepted(order: ChildOrder) -> None:
    group = GroupVMBuilder().destruct_order(order)
    assert group is not None

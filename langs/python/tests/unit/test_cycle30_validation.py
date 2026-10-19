"""Validate-before-mutate regressions: FormVM.set_model(None) during an
approval and CompositeVM.copy_to bounds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from vmx.components.component_vm import ComponentVM
from vmx.composites.composite_vm import CompositeVM
from vmx.forms.form_vm import FormVM
from vmx.services.null_dispatcher import NULL_DISPATCHER
from vmx.services.null_message_hub import NULL_MESSAGE_HUB


@dataclass
class _Model:
    value: str


async def _noop(_model: _Model) -> None:
    return None


@pytest.mark.asyncio
async def test_set_model_none_during_approval_raises_to_the_caller() -> None:
    form = FormVM(
        _Model("saved"),
        _noop,
        validators={"value": lambda model: "required" if not model.value else None},
        reset_on_approved=lambda _: _Model(""),
    )
    raised: list[type[BaseException]] = []

    def observer(_errors: object) -> None:
        try:
            form.set_model(None)  # type: ignore[arg-type]
        except ValueError as error:
            raised.append(type(error))

    form.errors_changed.subscribe(observer)

    await form.approve_async()

    assert raised == [ValueError]


def _composite(*names: str) -> CompositeVM[ComponentVM]:
    vm: CompositeVM[ComponentVM] = (
        CompositeVM.builder()
        .name("c")
        .services(NULL_MESSAGE_HUB, NULL_DISPATCHER)
        .children(lambda: [])
        .build()
    )
    for name in names:
        vm.append(ComponentVM.builder().name(name).with_null_services().build())
    return vm


def test_copy_to_validates_before_writing() -> None:
    sut = _composite("a", "b", "c")
    small: list[Any] = ["x", "y"]
    with pytest.raises(IndexError):
        sut.copy_to(small, 0)
    assert small == ["x", "y"]

    target: list[Any] = [None, None, None]
    with pytest.raises(IndexError):
        sut.copy_to(target, -1)
    assert target == [None, None, None]

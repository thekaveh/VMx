"""DISP-014 — modeled assignment after disposal is inert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from vmx.components import ComponentVMOf
from vmx.forms import FormVM
from vmx.messages import PropertyChangedMessage
from vmx.services import MessageHub, RxDispatcher


class CountingModel:
    def __init__(self, value: int, equality_calls: list[int]) -> None:
        self.value = value
        self._equality_calls = equality_calls

    def __eq__(self, other: object) -> bool:
        self._equality_calls.append(1)
        return isinstance(other, CountingModel) and self.value == other.value


@dataclass(frozen=True)
class FormModel:
    name: str


@pytest.mark.conformance("DISP-014")
def test_disp_014_modeled_assignment_after_disposal_is_inert() -> None:
    component_hub: MessageHub[object] = MessageHub()
    equality_calls: list[int] = []
    hinter_calls: list[int] = []
    callback_calls: list[CountingModel] = []
    initial = CountingModel(1, equality_calls)
    replacement = CountingModel(2, equality_calls)

    def modeled_hinter(model: CountingModel) -> str:
        hinter_calls.append(model.value)
        return f"hint:{model.value}"

    component = (
        ComponentVMOf.builder()
        .name("component")
        .model(initial)
        .modeled_hinter(modeled_hinter)
        .on_model_changed(callback_calls.append)
        .services(component_hub, RxDispatcher.immediate())
        .build()
    )
    local_changes: list[str] = []
    component_hub_changes: list[PropertyChangedMessage] = []
    component.property_changed.subscribe(local_changes.append)
    component_hub.messages.subscribe(
        lambda message: (
            component_hub_changes.append(message)
            if isinstance(message, PropertyChangedMessage)
            else None
        )
    )

    component.dispose()
    equality_calls.clear()
    hinter_calls.clear()
    callback_calls.clear()
    local_changes.clear()
    component_hub_changes.clear()

    def late_component_completion() -> None:
        component.model = replacement

    late_component_completion()

    assert component.model is initial
    assert component.modeled_hint == "hint:1"
    assert equality_calls == []
    assert hinter_calls == []
    assert callback_calls == []
    assert local_changes == []
    assert component_hub_changes == []

    form_hub: MessageHub[object] = MessageHub()
    validator_calls: list[str] = []

    async def persist(_: FormModel) -> None:
        return None

    def validate(model: FormModel) -> str | None:
        validator_calls.append(model.name)
        return "required" if not model.name else None

    form = FormVM(
        FormModel("valid"),
        persist,
        hub=form_hub,
        strict=True,
        validators={"name": validate},
    )
    initial_form_model = form.model
    initial_snapshot = form.snapshot
    initial_errors = form.errors
    initial_dirty = form.is_dirty
    initial_valid = form.is_valid
    errors_signals: list[dict[str, str]] = []
    command_signals: list[None] = []
    form_hub_changes: list[Any] = []
    form.errors_changed.subscribe(errors_signals.append)
    form.approve_command.can_execute_changed.subscribe(command_signals.append)
    form_hub.messages.subscribe(form_hub_changes.append)

    form.dispose()
    validator_calls.clear()
    errors_signals.clear()
    command_signals.clear()
    form_hub_changes.clear()

    def late_form_completion() -> None:
        form.set_model(FormModel(""))

    late_form_completion()

    assert form.model == initial_form_model
    assert form.snapshot == initial_snapshot
    assert form.errors == initial_errors
    assert form.is_dirty is initial_dirty
    assert form.is_valid is initial_valid
    assert validator_calls == []
    assert errors_signals == []
    assert command_signals == []
    assert form_hub_changes == []

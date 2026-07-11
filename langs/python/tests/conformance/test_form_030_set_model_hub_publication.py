"""FORM-030 — settled FormVM model hub publication."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from vmx.forms import FormVM
from vmx.messages import FormRevertedMessage, PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class _Model:
    value: str


async def _persist(_: _Model) -> None:
    return None


@pytest.mark.conformance("FORM-030")
async def test_form_030_set_model_publishes_one_settled_hub_message() -> None:
    trace: list[str] = []
    hub: MessageHub[Any] = MessageHub()

    def validate(model: _Model) -> str | None:
        trace.append("validate")
        return "required" if not model.value else None

    form = FormVM(
        _Model(""),
        _persist,
        hub=hub,
        strict=True,
        snapshotter=lambda model: model,
        validators={"value": validate},
    )
    trace.clear()

    errors_sub = form.errors_changed.subscribe(lambda _: trace.append("errors"))
    command_sub = form.approve_command.can_execute_changed.subscribe(
        lambda _: trace.append("can_execute")
    )
    observed: list[tuple[str, bool, bool]] = []
    reentered = False

    def observe(message: Any) -> None:
        nonlocal reentered
        if not (
            isinstance(message, PropertyChangedMessage)
            and message.sender is form
            and message.property_name == "model"
        ):
            return
        observed.append((form.model.value, form.is_valid, form.approve_command.can_execute()))
        trace.append("model")
        if not reentered:
            reentered = True
            form.set_model(_Model("nested"))

    hub_sub = hub.messages.subscribe(observe)

    form.set_model(_Model("outer"))

    assert observed == [("outer", True, True), ("nested", True, True)]
    assert trace == [
        "validate",
        "errors",
        "can_execute",
        "model",
        "validate",
        "model",
    ]

    retained = form.model
    trace_before_equal = len(trace)
    form.set_model(_Model("nested"))
    assert form.model is retained
    assert len(trace) == trace_before_equal

    form.dispose()
    trace_after_dispose = len(trace)
    form.set_model(_Model("late"))
    assert form.model is retained
    assert len(trace) == trace_after_dispose

    null_hub_form = FormVM(_Model("initial"), _persist, hub=None, snapshotter=lambda model: model)
    null_hub_form.set_model(_Model("changed"))
    assert null_hub_form.model.value == "changed"

    deny_hub: MessageHub[Any] = MessageHub()
    deny_messages: list[Any] = []
    deny_sub = deny_hub.messages.subscribe(deny_messages.append)
    deny_form = FormVM(
        _Model("initial"),
        _persist,
        hub=deny_hub,
        snapshotter=lambda model: model,
    )
    deny_form.set_model(_Model("changed"))
    deny_messages.clear()
    deny_form.deny_command.execute()
    assert len(deny_messages) == 2
    assert isinstance(deny_messages[0], FormRevertedMessage)
    assert isinstance(deny_messages[1], PropertyChangedMessage)
    assert deny_messages[1].property_name == "model"

    reset_hub: MessageHub[Any] = MessageHub()
    reset_messages: list[Any] = []
    reset_sub = reset_hub.messages.subscribe(reset_messages.append)
    reset_form = FormVM(
        _Model("initial"),
        _persist,
        hub=reset_hub,
        snapshotter=lambda model: model,
        reset_on_approved=lambda _: _Model("reset"),
    )
    reset_form.set_model(_Model("saved"))
    reset_messages.clear()

    await reset_form.approve_async()

    assert reset_form.model.value == "reset"
    assert not [
        message
        for message in reset_messages
        if isinstance(message, PropertyChangedMessage) and message.property_name == "model"
    ]

    for subscription in (
        errors_sub,
        command_sub,
        hub_sub,
        deny_sub,
        reset_sub,
    ):
        subscription.dispose()

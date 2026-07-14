"""FORM-030 — settled FormVM model hub publication."""

from __future__ import annotations

import dataclasses
from threading import Event, Thread
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


def test_admitted_set_model_finishes_before_concurrent_dispose() -> None:
    validation_started = Event()
    release_validation = Event()
    dispose_finished = Event()

    def validate(model: _Model) -> str | None:
        if model.value == "accepted":
            validation_started.set()
            assert release_validation.wait(1)
        return None

    form = FormVM(
        _Model("initial"),
        _persist,
        snapshotter=lambda model: model,
        validators={"value": validate},
    )

    setter = Thread(target=lambda: form.set_model(_Model("accepted")), daemon=True)
    setter.start()
    assert validation_started.wait(1)

    disposer = Thread(
        target=lambda: (form.dispose(), dispose_finished.set()),
        daemon=True,
    )
    disposer.start()
    disposed_during_validation = dispose_finished.wait(0.1)
    release_validation.set()

    setter.join(timeout=1)
    disposer.join(timeout=1)

    assert not setter.is_alive()
    assert not disposer.is_alive()
    assert not disposed_during_validation
    assert form.model == _Model("accepted")


def test_validator_observes_the_accepted_live_model() -> None:
    form: FormVM[_Model] | None = None

    def validate(candidate: _Model) -> str | None:
        if candidate.value == "accepted":
            assert form is not None
            assert form.model == candidate
        return None

    form = FormVM(
        _Model("initial"),
        _persist,
        snapshotter=lambda model: model,
        validators={"value": validate},
    )

    form.set_model(_Model("accepted"))

    assert form.model == _Model("accepted")


def test_admitted_set_model_completes_when_validator_disposes_reentrantly() -> None:
    hub: MessageHub[Any] = MessageHub()
    messages: list[Any] = []
    subscription = hub.messages.subscribe(messages.append)
    form: FormVM[_Model] | None = None

    def validate(candidate: _Model) -> str | None:
        if candidate.value == "accepted":
            assert form is not None
            form.dispose()
        return None

    form = FormVM(
        _Model("initial"),
        _persist,
        hub=hub,
        snapshotter=lambda model: model,
        validators={"value": validate},
    )

    form.set_model(_Model("accepted"))
    form.set_model(_Model("late"))

    assert form.model == _Model("accepted")
    assert len([m for m in messages if isinstance(m, PropertyChangedMessage)]) == 1
    subscription.dispose()


@pytest.mark.parametrize("deny", [False, True])
def test_form_mutation_does_not_hold_gate_while_waiting_for_hub_delivery(
    deny: bool,
) -> None:
    inner_hub: MessageHub[Any] = MessageHub()
    blocker_sender = object()
    blocker_entered = Event()
    release_blocker = Event()
    form_send_started = Event()
    reentry_finished = Event()
    armed = False

    class SignalingHub:
        @property
        def messages(self) -> Any:
            return inner_hub.messages

        def send(self, message: Any) -> None:
            if armed and (
                (deny and isinstance(message, FormRevertedMessage))
                or (not deny and isinstance(message, PropertyChangedMessage))
            ):
                form_send_started.set()
            inner_hub.send(message)

    form = FormVM(
        _Model("initial"),
        _persist,
        hub=SignalingHub(),
        snapshotter=lambda model: model,
    )
    if deny:
        form.set_model(_Model("dirty"))
    armed = True

    def observe(message: Any) -> None:
        if not (isinstance(message, FormRevertedMessage) and message.sender is blocker_sender):
            return
        blocker_entered.set()
        assert release_blocker.wait(1)
        form.set_model(_Model("nested"))
        reentry_finished.set()

    subscription = inner_hub.messages.subscribe(observe)
    blocker = Thread(
        target=lambda: inner_hub.send(
            FormRevertedMessage(sender=blocker_sender, sender_name="blocker")
        ),
        daemon=True,
    )
    blocker.start()
    assert blocker_entered.wait(1)

    mutator = Thread(
        target=(form.deny_command.execute if deny else lambda: form.set_model(_Model("outer"))),
        daemon=True,
    )
    mutator.start()
    assert form_send_started.wait(1)
    release_blocker.set()

    reentered_without_deadlock = reentry_finished.wait(0.1)
    if not reentered_without_deadlock:
        inner_hub.dispose()
    mutator.join(timeout=1)
    blocker.join(timeout=1)
    if reentered_without_deadlock:
        inner_hub.dispose()
    subscription.dispose()

    assert not mutator.is_alive()
    assert not blocker.is_alive()
    assert reentered_without_deadlock

"""FORM-041..042 — nested FormVM updates notify at the outermost update.

Per spec/20-form-vm.md §5.2, §5.4 (*Nested updates*), §5.5 and §10, and
ADR-0180. A ``set_model``, deny, or approve call nested in a preparation
callback, or in an ``errors_changed`` observer of the outermost update, sends
nothing before it returns. The outermost update sends the queue before it
returns: error maps first, then the other notifications. Once the form is
disposed, the queued notifications are dropped, and a ``dispose()`` before a
scheduled persister start prevents the persister call.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx.forms import FormVM
from vmx.messages import FormRevertedMessage, PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class _Model:
    value: str


# RelayCommand.dispose raises one terminal can-execute notification, then
# completes; it is disposal, not an update publication.
TEARDOWN_EVENTS = ["can_execute", "can_execute_completed"]
# A bounded wait that lets a scheduled persister task run if one exists.
SETTLE = 0.05


async def _noop(_: object) -> None:
    return None


def _rejects(*values: str) -> Any:
    def validate(model: _Model) -> str | None:
        return "rejected" if model.value in values else None

    return validate


class _Log:
    """Logs every FormVM notification, in order, with the test's own markers."""

    def __init__(self, form: FormVM[Any], hub: MessageHub[Any]) -> None:
        self._form = form
        self.events: list[str] = []
        self.maps: list[dict[str, str]] = []
        self.approved: list[Any] = []
        self.approve_errors: list[BaseException] = []
        form.errors_changed.subscribe(self._on_errors)
        form.approve_command.can_execute_changed.subscribe(
            on_next=lambda _: self.events.append("can_execute"),
            on_completed=lambda: self.events.append("can_execute_completed"),
        )
        form.on_approved.subscribe(self.approved.append)
        form.approve_errors.subscribe(self.approve_errors.append)
        hub.messages.subscribe(self._on_message)

    def _on_errors(self, errors: dict[str, str]) -> None:
        self.events.append("errors")
        self.maps.append(errors)

    def _on_message(self, message: Any) -> None:
        if getattr(message, "sender", None) is not self._form:
            return
        if isinstance(message, FormRevertedMessage):
            self.events.append("reverted")
        elif isinstance(message, PropertyChangedMessage) and message.property_name == "model":
            self.events.append("model")


# ---------------------------------------------------------------------------
# FORM-041 — a nested update notifies after it returns
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-041")
def test_form_041_nested_set_model_from_a_validator_notifies_after_it_returns() -> None:
    form: FormVM[_Model] | None = None
    log: _Log | None = None
    nested = False
    rejects_b = _rejects("b")

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None and log is not None
            form.set_model(_Model("b"))
            log.events.append("nested returned")
        return rejects_b(model)

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(_Model("initial"), _noop, hub=hub, validators={"value": validate})
    log = _Log(form, hub)

    form.set_model(_Model("a"))
    log.events.append("outer returned")

    assert log.events == ["nested returned", "errors", "can_execute", "model", "outer returned"]
    assert form.model == _Model("b")
    assert form.errors == {"value": "rejected"}


@pytest.mark.conformance("FORM-041")
def test_form_041_nested_deny_from_a_validator_notifies_after_it_returns() -> None:
    form: FormVM[_Model] | None = None
    log: _Log | None = None
    nested = False
    rejects_x = _rejects("x")

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None and log is not None
            form.deny_command.execute()
            log.events.append("nested returned")
        return rejects_x(model)

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(_Model("initial"), _noop, hub=hub, validators={"value": validate})
    form.set_model(_Model("x"))
    assert form.is_dirty and not form.is_valid
    log = _Log(form, hub)

    form.set_model(_Model("a"))
    log.events.append("outer returned")

    assert log.events == [
        "nested returned",
        "errors",
        "reverted",
        "model",
        "can_execute",
        "outer returned",
    ]
    assert form.model == form.snapshot
    assert form.is_valid


@pytest.mark.conformance("FORM-041")
def test_form_041_update_from_an_errors_changed_observer_notifies_in_commit_order() -> None:
    hub: MessageHub[Any] = MessageHub()
    form = FormVM(_Model("initial"), _noop, hub=hub, validators={"value": _rejects("a")})
    log = _Log(form, hub)

    def on_errors(_: dict[str, str]) -> None:
        if len(log.maps) == 1:
            form.set_model(_Model("c"))
            log.events.append("nested returned")

    form.errors_changed.subscribe(on_errors)

    form.set_model(_Model("a"))
    log.events.append("outer returned")

    assert log.events == [
        "errors",
        "nested returned",
        "errors",
        "can_execute",
        "model",
        "can_execute",
        "model",
        "outer returned",
    ]
    assert log.maps == [{"value": "rejected"}, {}]
    assert form.model == _Model("c")


@pytest.mark.conformance("FORM-041")
async def test_form_041_nested_approval_starts_after_the_outermost_update_notifies() -> None:
    form: FormVM[_Model] | None = None
    log: _Log | None = None
    nested = False

    async def persist(model: _Model) -> None:
        assert log is not None
        log.events.append(f"persist {model.value}")

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None and log is not None
            form.approve_command.execute()
            log.events.append("nested returned")
        return None

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(_Model("initial"), persist, hub=hub, validators={"value": validate})
    form.set_model(_Model("edited"))
    log = _Log(form, hub)

    form.set_model(_Model("a"))
    log.events.append("outer returned")
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    await asyncio.wait_for(asyncio.gather(*pending), HANG_GUARD)

    # The admission notification precedes the outer model message, and the
    # persister task starts only after the outermost update returns.
    assert log.events == [
        "nested returned",
        "can_execute",
        "model",
        "outer returned",
        "persist edited",
        "can_execute",
    ]
    assert log.approved == [_Model("edited")]
    assert form.model == _Model("a")
    assert form.snapshot == _Model("edited")


# ---------------------------------------------------------------------------
# FORM-042 — disposal before the persister starts prevents the persister call
# ---------------------------------------------------------------------------


class _CountingPersister:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _: object) -> None:
        self.calls += 1


@pytest.mark.conformance("FORM-042")
async def test_form_042_nested_approval_then_dispose_never_calls_the_persister() -> None:
    persister = _CountingPersister()
    form: FormVM[_Model] | None = None
    nested = False

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "trigger" and not nested:
            nested = True
            assert form is not None
            form.approve_command.execute()
            form.dispose()
        return None

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(_Model("initial"), persister, hub=hub, validators={"value": validate})
    log = _Log(form, hub)

    form.set_model(_Model("trigger"))
    await asyncio.sleep(SETTLE)

    assert persister.calls == 0
    # No update or approval notification; only the teardown's terminal signal.
    assert log.events == TEARDOWN_EVENTS
    assert log.approved == []
    assert log.approve_errors == []


@pytest.mark.conformance("FORM-042")
def test_form_042_queued_notifications_are_dropped_once_the_form_is_disposed() -> None:
    form: FormVM[_Model] | None = None
    nested = False
    rejects_b = _rejects("b")

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None
            form.set_model(_Model("b"))
            form.dispose()
        return rejects_b(model)

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(_Model("initial"), _noop, hub=hub, validators={"value": validate})
    log = _Log(form, hub)

    form.set_model(_Model("a"))

    assert log.events == TEARDOWN_EVENTS
    assert log.maps == []


@pytest.mark.conformance("FORM-042")
async def test_form_042_dispose_before_the_scheduled_persister_starts_prevents_the_call() -> None:
    persister = _CountingPersister()
    form = FormVM(_Model("initial"), persister)
    approved: list[_Model] = []
    errors: list[BaseException] = []
    form.on_approved.subscribe(approved.append)
    form.approve_errors.subscribe(errors.append)

    form.approve_command.execute()
    # The persister task is scheduled on this loop and has not run yet.
    calls_after_execute = persister.calls
    form.dispose()
    await asyncio.sleep(SETTLE)

    assert calls_after_execute == 0
    assert persister.calls == calls_after_execute
    assert approved == []
    assert errors == []

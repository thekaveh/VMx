"""FORM-044 — a failed send of the outermost update's queue stops the later sends.

Per spec/20-form-vm.md §5.4 (*Nested updates*, rule 7) and ADR-0216. When a
send of the outermost update's queue fails, no later notification of that
queue is sent. A nested approval whose persister has not started never calls
it and is no longer in flight. Its awaiter completes normally, and nothing
reaches ``approve_errors``. The failure propagates from the outermost update
after its replays.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Coroutine
from typing import Any

import pytest
import reactivex as rx
from reactivex.subject import Subject

from vmx.forms import FormVM
from vmx.messages import PropertyChangedMessage

# A bounded wait that lets a scheduled persister task run if one exists.
SETTLE = 0.05


@dataclasses.dataclass(frozen=True)
class _Model:
    value: str


class SendError(Exception):
    """The hub's send failure."""


class _FailingHub:
    """A ``MessageHubProto`` whose ``send`` records each message, then fails once."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self._messages: Subject[Any] = Subject()

    @property
    def messages(self) -> rx.Observable[Any]:
        return self._messages

    def send(self, message: Any) -> None:
        self.sent.append(message)
        if isinstance(message, PropertyChangedMessage) and len(self.sent) == 1:
            raise SendError("hub send")

    def model_messages(self) -> int:
        return sum(
            1
            for message in self.sent
            if isinstance(message, PropertyChangedMessage) and message.property_name == "model"
        )


class _CountingPersister:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _: object) -> None:
        self.calls += 1


@pytest.mark.conformance("FORM-044")
async def test_form_044_a_failed_send_stops_the_queue_and_releases_a_nested_command_approval() -> (
    None
):
    hub = _FailingHub()
    persister = _CountingPersister()
    form: FormVM[_Model] | None = None
    nested = False

    def validate(model: _Model) -> str | None:
        nonlocal nested
        if model.value == "a" and not nested:
            nested = True
            assert form is not None
            form.approve_command.execute()
            form.set_model(_Model("b"))
            form.set_model(_Model("c"))
        return None

    form = FormVM(_Model("initial"), persister, hub=hub, validators={"value": validate})
    approve_errors: list[BaseException] = []
    form.approve_errors.subscribe(approve_errors.append)
    can_execute_changes: list[None] = []
    form.approve_command.can_execute_changed.subscribe(can_execute_changes.append)

    with pytest.raises(SendError):
        form.set_model(_Model("a"))
    await asyncio.sleep(SETTLE)

    # The model message of "b" failed; the one of "c" was never sent.
    assert hub.model_messages() == 1
    # The admission edge and the release edge.
    assert len(can_execute_changes) == 2
    assert persister.calls == 0
    assert approve_errors == []
    assert form.approve_command.can_execute()
    assert form.model == _Model("c")


@pytest.mark.conformance("FORM-044")
async def test_form_044_a_released_nested_approve_async_completes_normally() -> None:
    hub = _FailingHub()
    persister = _CountingPersister()
    coroutines: list[Coroutine[Any, Any, None]] = []
    form: FormVM[_Model] | None = None

    def validate(model: _Model) -> str | None:
        if model.value == "a" and not coroutines:
            assert form is not None
            # Run the coroutine to its first suspension: the call is admitted
            # here and waits for the outermost update to start it.
            coroutine = form.approve_async()
            coroutine.send(None)
            coroutines.append(coroutine)
            form.set_model(_Model("b"))
        return None

    form = FormVM(_Model("initial"), persister, hub=hub, validators={"value": validate})
    approve_errors: list[BaseException] = []
    form.approve_errors.subscribe(approve_errors.append)

    with pytest.raises(SendError):
        form.set_model(_Model("a"))
    await asyncio.sleep(0)  # the release resolves the awaiter on this loop
    with pytest.raises(StopIteration):
        coroutines[0].send(None)

    assert persister.calls == 0
    assert approve_errors == []
    assert form.approve_command.can_execute()
    assert form.model == _Model("b")

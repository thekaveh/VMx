"""FORM-039..040 — FormVM queues updates made during approval publication.

Per spec/20-form-vm.md §5.1, §5.3 and §5.4, and ADR-0174. A ``set_model`` or
deny that the approving thread makes in an approval's pre-publication window
(the post-persist commit and settlement steps 2 and 3) prepares at call time,
publishes nothing, and replays in call order after ``on_approved``. Replays
run in isolation, and the first replay failure reaches the approval's own
failure route unless the approval already carries a failure.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx.forms import FormVM
from vmx.messages import FormRevertedMessage, PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class Model:
    value: str


@dataclasses.dataclass(frozen=True)
class Num:
    n: int


class BoomError(Exception):
    """A consumer callback failure."""


async def _noop(_: object) -> None:
    return None


async def _approve(form: FormVM[Any], path: str) -> BaseException | None:
    """Run one approval on *path* and return the failure its route received.

    ``"async"`` awaits ``approve_async``; ``"command"`` executes the command
    and waits for the approval task it scheduled on this loop.
    """
    if path == "async":
        try:
            await asyncio.wait_for(form.approve_async(), HANG_GUARD)
        except BoomError as error:
            return error
        return None
    form.approve_command.execute()
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), HANG_GUARD)
    return None


class Log:
    """Records every FormVM signal and hub message in delivery order."""

    def __init__(self, form: FormVM[Any], hub: MessageHub[Any]) -> None:
        self.events: list[tuple[str, object]] = []
        self.approved: list[object] = []
        self.approve_errors: list[BaseException] = []
        self.errors_changed: list[dict[str, str]] = []
        self._form = form
        form.errors_changed.subscribe(self._on_errors)
        form.approve_command.can_execute_changed.subscribe(
            lambda _: self.events.append(("can_execute", None))
        )
        form.on_approved.subscribe(self._on_approved)
        form.approve_errors.subscribe(self.approve_errors.append)
        hub.messages.subscribe(self._on_message)

    def _on_errors(self, errors: dict[str, str]) -> None:
        self.errors_changed.append(errors)
        self.events.append(("errors", errors))

    def _on_approved(self, approved: object) -> None:
        self.approved.append(approved)
        self.events.append(("approved", approved))

    def _on_message(self, message: object) -> None:
        if isinstance(message, FormRevertedMessage):
            self.events.append(("reverted", None))
        elif isinstance(message, PropertyChangedMessage):
            self.events.append(("model", self._form.model))

    def split(self) -> tuple[list[tuple[str, object]], list[tuple[str, object]]]:
        """Return the events before and after the one ``on_approved`` emission."""
        index = [kind for kind, _ in self.events].index("approved")
        return self.events[:index], self.events[index + 1 :]


def _settlement_observer(form: FormVM[Any], action: Callable[[], None]) -> None:
    """Run *action* once from the settlement ``can_execute_changed``.

    Admission raises the edge while the approval is in flight, so the command
    is disabled; the settlement edge is the first one with it enabled.
    """
    armed = [True]

    def on_can_execute(_: None) -> None:
        if armed[0] and form.approve_command.can_execute():
            armed[0] = False
            action()

    form.approve_command.can_execute_changed.subscribe(on_can_execute)


# ---------------------------------------------------------------------------
# FORM-039 — updates during approval publication replay after on_approved
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-039")
async def test_form_039_reset_set_model_replays_after_on_approved() -> None:
    hub: MessageHub[Any] = MessageHub()
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        form.set_model(Model("x"))
        return Model("pristine")

    form = FormVM(
        Model("initial"),
        _noop,
        hub=hub,
        validators={"value": lambda m: "rejected" if m.value == "x" else None},
        reset_on_approved=reset,
    )
    form.set_model(Model("edited"))
    log = Log(form, hub)
    seen: list[tuple[Model, bool, bool]] = []
    form.on_approved.subscribe(lambda _: seen.append((form.model, form.is_dirty, form.is_valid)))

    await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    before, after = log.split()
    # Only the admission and settlement edges precede on_approved: the queued
    # call published no ErrorsChanged, CanExecuteChanged, or model message.
    assert before == [("can_execute", None), ("can_execute", None)]
    assert seen == [(Model("pristine"), False, True)]
    assert form.model == Model("x")
    assert form.errors == {"value": "rejected"}
    assert [event for event in after if event[0] == "model"] == [("model", Model("x"))]
    assert log.errors_changed[-1] == form.errors


@pytest.mark.conformance("FORM-039")
async def test_form_039_settlement_deny_after_racing_edit_replays_after_on_approved() -> None:
    hub: MessageHub[Any] = MessageHub()
    gate: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    entered = asyncio.Event()

    async def persister(_: Model) -> None:
        entered.set()
        await gate

    form = FormVM(Model("initial"), persister, hub=hub)
    form.set_model(Model("saved"))
    approval = asyncio.ensure_future(form.approve_async())
    await asyncio.wait_for(entered.wait(), HANG_GUARD)
    form.set_model(Model("newer"))

    log = Log(form, hub)
    seen: list[tuple[Model, bool]] = []
    form.on_approved.subscribe(lambda _: seen.append((form.model, form.is_dirty)))
    _settlement_observer(form, form.deny_command.execute)

    gate.set_result(None)
    await asyncio.wait_for(approval, HANG_GUARD)

    assert seen == [(Model("newer"), True)]
    before, after = log.split()
    assert ("reverted", None) not in before
    assert ("reverted", None) in after
    assert form.model == Model("saved")
    assert not form.is_dirty


@pytest.mark.conformance("FORM-039")
async def test_form_039_reset_set_model_then_deny_replay_in_call_order() -> None:
    hub: MessageHub[Any] = MessageHub()
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        form.set_model(Model("a"))
        form.deny_command.execute()
        return Model("pristine")

    form = FormVM(Model("initial"), _noop, hub=hub, reset_on_approved=reset)
    form.set_model(Model("edited"))
    log = Log(form, hub)

    await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    before, after = log.split()
    assert [event for event in before if event[0] in ("model", "reverted")] == []
    assert [event for event in after if event[0] in ("model", "reverted")] == [
        ("model", Model("a")),
        ("reverted", None),
        ("model", Model("pristine")),
    ]
    assert form.model == Model("pristine")
    assert not form.is_dirty


# ---------------------------------------------------------------------------
# FORM-040 — a queued update prepares at call time and replays in isolation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-040")
@pytest.mark.parametrize("path", ["async", "command"])
async def test_form_040_call_time_failure_is_not_queued(path: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    validated: list[int] = []

    def validator(model: Num) -> str | None:
        validated.append(model.n)
        if model.n == 13:
            raise BoomError("boom13")
        return None

    form = FormVM(Num(1), _noop, hub=hub, validators={"n": validator})
    form.set_model(Num(2))
    log = Log(form, hub)
    call_time: list[BaseException] = []

    def observer() -> None:
        try:
            form.set_model(Num(13))
        except BoomError as error:
            call_time.append(error)
        form.set_model(Num(42))

    _settlement_observer(form, observer)

    failure = await _approve(form, path)

    assert [str(error) for error in call_time] == ["boom13"]
    assert validated.count(13) == 1
    assert failure is None
    assert log.approved == [Num(2)]
    assert log.approve_errors == []
    assert form.model == Num(42)
    assert form.snapshot == Num(2)


@pytest.mark.conformance("FORM-040")
async def test_form_040_equal_candidate_is_still_queued() -> None:
    hub: MessageHub[Any] = MessageHub()
    form = FormVM(Num(1), _noop, hub=hub)
    form.set_model(Num(2))
    log = Log(form, hub)

    def observer() -> None:
        form.set_model(Num(5))
        form.set_model(Num(2))

    _settlement_observer(form, observer)

    await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    _, after = log.split()
    assert [event for event in after if event[0] == "model"] == [
        ("model", Num(5)),
        ("model", Num(2)),
    ]
    assert form.model == Num(2)


def _replay_failure_form(
    hub: MessageHub[Any],
) -> tuple[FormVM[Num], list[bool]]:
    """A form at ``2`` whose validator fails for 7 and 9 once ``armed``.

    A settlement observer queues 7, 8 and 9; all three pass their call-time
    preparation, and an ``on_approved`` subscriber arms the failure, so 7 and
    9 fail when they replay.
    """
    armed = [False]

    def validator(model: Num) -> str | None:
        if armed[0] and model.n in (7, 9):
            raise BoomError(f"boom{model.n}")
        return None

    form = FormVM(Num(1), _noop, hub=hub, validators={"n": validator})
    form.set_model(Num(2))

    def observer() -> None:
        form.set_model(Num(7))
        form.set_model(Num(8))
        form.set_model(Num(9))

    _settlement_observer(form, observer)
    return form, armed


@pytest.mark.conformance("FORM-040")
@pytest.mark.parametrize("path", ["async", "command"])
async def test_form_040_replay_failure_is_isolated_and_routed_once(path: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    form, armed = _replay_failure_form(hub)
    log = Log(form, hub)
    form.on_approved.subscribe(lambda _: armed.__setitem__(0, True))
    at_failure: list[Num] = []
    form.approve_errors.subscribe(lambda _: at_failure.append(form.model))

    failure = await _approve(form, path)

    if path == "async":
        assert str(failure) == "boom7"
        assert log.approve_errors == []
    else:
        assert failure is None
        assert [str(error) for error in log.approve_errors] == ["boom7"]
        # The failure is routed after the last replay.
        assert at_failure == [Num(8)]
    # The later update still committed; the approval stayed settled.
    assert form.model == Num(8)
    assert form.snapshot == Num(2)
    assert log.approved == [Num(2)]


@pytest.mark.conformance("FORM-040")
@pytest.mark.parametrize("path", ["async", "command"])
async def test_form_040_on_approved_subscriber_failure_wins(path: str) -> None:
    hub: MessageHub[Any] = MessageHub()
    form, armed = _replay_failure_form(hub)
    log = Log(form, hub)

    def failing_subscriber(_: Num) -> None:
        armed[0] = True
        raise BoomError("approved")

    form.on_approved.subscribe(failing_subscriber)

    failure = await _approve(form, path)

    if path == "async":
        assert str(failure) == "approved"
    else:
        assert [str(error) for error in log.approve_errors] == ["approved"]
    assert form.model == Num(8)
    assert form.snapshot == Num(2)
    assert log.approved == [Num(2)]

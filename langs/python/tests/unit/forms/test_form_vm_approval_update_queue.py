"""FormVM updates during approval publication (spec/20 §5.3, ADR-0174).

Covers the rules the FORM-039..040 conformance tests leave out: a failed
post-persist commit, call-time staleness, disposal in the window, a replayed
update whose observer fails, and another thread's update during the commit.
"""

from __future__ import annotations

import asyncio
import dataclasses
from threading import Event, Thread
from typing import Any

import pytest

from tests.liveness import HANG_GUARD
from vmx.forms import FormVM
from vmx.messages import PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class Model:
    value: str


class BoomError(Exception):
    """A consumer callback failure."""


async def _noop(_: object) -> None:
    return None


def _model_messages(hub: MessageHub[Any], form: FormVM[Model]) -> list[Model]:
    seen: list[Model] = []
    hub.messages.subscribe(
        lambda message: (
            seen.append(form.model) if isinstance(message, PropertyChangedMessage) else None
        )
    )
    return seen


async def test_failed_reset_replays_its_queue_before_the_failure_reaches_the_awaiter() -> None:
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        form.set_model(Model("queued"))
        raise BoomError("reset")

    form = FormVM(Model("initial"), _noop, reset_on_approved=reset)
    form.set_model(Model("edited"))
    approved: list[Model] = []
    form.on_approved.subscribe(approved.append)

    with pytest.raises(BoomError, match="reset") as raised:
        await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    assert raised.value.args == ("reset",)
    assert approved == []
    # The queued call returned normally, so it takes effect; the commit did not.
    assert form.model == Model("queued")
    assert form.snapshot == Model("initial")


async def test_failed_reset_replays_before_approve_errors_and_its_failure_wins() -> None:
    form: FormVM[Model]
    armed = [False]

    def validator(model: Model) -> str | None:
        if armed[0] and model.value == "fails-on-replay":
            raise BoomError("replay")
        return None

    def reset(_: Model) -> Model:
        form.set_model(Model("fails-on-replay"))
        form.set_model(Model("queued"))
        armed[0] = True
        raise BoomError("reset")

    form = FormVM(Model("initial"), _noop, validators={"value": validator}, reset_on_approved=reset)
    form.set_model(Model("edited"))
    routed: list[tuple[str, Model]] = []
    form.approve_errors.subscribe(lambda error: routed.append((str(error), form.model)))

    form.approve_command.execute()
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), HANG_GUARD)

    # Both queued calls replayed before the failure was routed; the commit
    # failure wins over the replay failure and is routed once.
    assert routed == [("reset", Model("queued"))]


async def test_failure_settlement_observer_update_is_not_queued() -> None:
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        raise BoomError("reset")

    form = FormVM(Model("initial"), _noop, reset_on_approved=reset)
    form.set_model(Model("edited"))
    seen_after_call: list[Model] = []

    def on_can_execute(_: None) -> None:
        if form.approve_command.can_execute() and not seen_after_call:
            form.set_model(Model("from-failure-settlement"))
            seen_after_call.append(form.model)

    form.approve_command.can_execute_changed.subscribe(on_can_execute)

    with pytest.raises(BoomError):
        await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    assert seen_after_call == [Model("from-failure-settlement")]


async def test_nested_update_from_call_time_preparation_makes_the_outer_call_stale() -> None:
    hub: MessageHub[Any] = MessageHub()
    form: FormVM[Model]

    def validator(model: Model) -> str | None:
        if model.value == "outer":
            form.set_model(Model("nested"))
        return None

    def reset(_: Model) -> Model:
        form.set_model(Model("outer"))
        return Model("pristine")

    form = FormVM(
        Model("initial"),
        _noop,
        hub=hub,
        validators={"value": validator},
        reset_on_approved=reset,
    )
    form.set_model(Model("edited"))
    messages = _model_messages(hub, form)

    await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    assert messages == [Model("nested")]
    assert form.model == Model("nested")


async def test_disposal_in_the_window_drops_the_replay() -> None:
    hub: MessageHub[Any] = MessageHub()
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        form.set_model(Model("queued"))
        form.dispose()
        return Model("pristine")

    form = FormVM(Model("initial"), _noop, hub=hub, reset_on_approved=reset)
    form.set_model(Model("edited"))
    messages = _model_messages(hub, form)

    await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    assert messages == []
    assert form.model == Model("edited")


async def test_replayed_update_observer_failure_does_not_stop_later_replays() -> None:
    form = FormVM(
        Model("initial"),
        _noop,
        validators={"value": lambda m: "bad" if m.value == "invalid" else None},
    )
    form.set_model(Model("saved"))
    approved: list[Model] = []
    form.on_approved.subscribe(approved.append)

    def on_errors(_: dict[str, str]) -> None:
        if form.model == Model("invalid"):
            raise BoomError("observer")

    form.errors_changed.subscribe(on_errors)
    armed = [True]

    def on_can_execute(_: None) -> None:
        if armed[0] and form.approve_command.can_execute():
            armed[0] = False
            form.set_model(Model("invalid"))
            form.set_model(Model("later"))

    form.approve_command.can_execute_changed.subscribe(on_can_execute)

    with pytest.raises(BoomError, match="observer"):
        await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    assert approved == [Model("saved")]
    assert form.snapshot == Model("saved")
    assert form.model == Model("later")


def test_another_threads_update_waits_for_the_post_persist_commit() -> None:
    in_reset = Event()
    release_reset = Event()
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        in_reset.set()
        assert release_reset.wait(HANG_GUARD)
        return Model("pristine")

    form = FormVM(Model("initial"), _noop, reset_on_approved=reset)
    form.set_model(Model("edited"))
    seen: list[Model] = []
    form.on_approved.subscribe(lambda _: seen.append(form.model))

    approver = Thread(target=lambda: asyncio.run(form.approve_async()), daemon=True)
    approver.start()
    assert in_reset.wait(HANG_GUARD)

    setter_done = Event()

    def set_foreign() -> None:
        form.set_model(Model("foreign"))
        setter_done.set()

    setter = Thread(target=set_foreign, daemon=True)
    setter.start()
    assert not setter_done.wait(0.05)

    release_reset.set()
    approver.join(timeout=HANG_GUARD * 2)
    setter.join(timeout=HANG_GUARD * 2)

    assert not approver.is_alive()
    assert not setter.is_alive()
    assert seen == [Model("pristine")]
    assert form.model == Model("foreign")
    assert form.snapshot == Model("pristine")

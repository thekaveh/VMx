"""FormVM updates during approval publication (spec/20 §5.3, ADR-0174).

Covers the rules the FORM-039..040 conformance tests leave out: a failed
post-persist commit, call-time staleness, disposal in the window, a replayed
update whose observer fails, a nested same-thread publication, and another
thread's update, approve, or dispose during the commit.
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


def _event_log(hub: MessageHub[Any], form: FormVM[Model]) -> list[str]:
    """Record model messages and ``can_execute_changed`` edges in one order."""
    log: list[str] = []
    hub.messages.subscribe(
        lambda message: (
            log.append(f"model:{form.model.value}")
            if isinstance(message, PropertyChangedMessage)
            else None
        )
    )
    form.approve_command.can_execute_changed.subscribe(lambda _: log.append("can_execute"))
    return log


def _model_messages(hub: MessageHub[Any], form: FormVM[Model]) -> list[Model]:
    seen: list[Model] = []
    hub.messages.subscribe(
        lambda message: (
            seen.append(form.model) if isinstance(message, PropertyChangedMessage) else None
        )
    )
    return seen


async def test_failed_reset_replays_its_queue_before_the_failure_reaches_the_awaiter() -> None:
    hub: MessageHub[Any] = MessageHub()
    form: FormVM[Model]

    def reset(_: Model) -> Model:
        form.set_model(Model("queued"))
        raise BoomError("reset")

    form = FormVM(Model("initial"), _noop, hub=hub, reset_on_approved=reset)
    form.set_model(Model("edited"))
    approved: list[Model] = []
    form.on_approved.subscribe(approved.append)
    log = _event_log(hub, form)

    with pytest.raises(BoomError, match="reset") as raised:
        await asyncio.wait_for(form.approve_async(), HANG_GUARD)
    log.append("raised")

    assert raised.value.args == ("reset",)
    assert approved == []
    # The admission edge, then the failure settlement edge. The queued call
    # published nothing during the commit; it replays after the failure
    # settlement's can_execute_changed and before the failure is routed.
    assert log == ["can_execute", "can_execute", "model:queued", "raised"]
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

    hub: MessageHub[Any] = MessageHub()
    form = FormVM(
        Model("initial"),
        _noop,
        hub=hub,
        validators={"value": validator},
        reset_on_approved=reset,
    )
    form.set_model(Model("edited"))
    log = _event_log(hub, form)
    routed: list[tuple[str, Model]] = []

    def on_error(error: BaseException) -> None:
        routed.append((str(error), form.model))
        log.append(f"error:{error}")

    form.approve_errors.subscribe(on_error)

    form.approve_command.execute()
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), HANG_GUARD)

    # Both queued calls replayed before the failure was routed; the commit
    # failure wins over the replay failure and is routed once.
    assert routed == [("reset", Model("queued"))]
    # Nothing was published during the commit. The first replay fails in its
    # validator and publishes nothing; the second publishes after the failure
    # settlement edge and before the failure reaches approve_errors.
    assert log == ["can_execute", "can_execute", "model:queued", "error:reset"]


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


async def test_nested_publication_on_the_same_thread_replays_when_the_outer_scope_ends() -> None:
    form: FormVM[Model]
    approvals = [0]

    def reset(_: Model) -> Model:
        approvals[0] += 1
        if approvals[0] == 2:
            form.set_model(Model("from-inner-reset"))
        return Model("pristine")

    form = FormVM(Model("initial"), _noop, reset_on_approved=reset)
    form.set_model(Model("edited"))
    inside_outer: list[Model] = []

    def on_approved(_: Model) -> None:
        if approvals[0] != 1:
            return
        # An on_approved subscriber is outside the window: this commits.
        form.set_model(Model("edited-again"))
        # Drive a second approval to completion on this thread, inside the
        # outer approval's publication scope. Its persister never suspends.
        inner = form.approve_async()
        with pytest.raises(StopIteration):
            inner.send(None)
        inside_outer.append(form.model)

    form.on_approved.subscribe(on_approved)

    await asyncio.wait_for(form.approve_async(), HANG_GUARD)

    # The inner reset's call joined the queue; the inner scope did not replay
    # it, so the inner reset state stood while the outer scope was open.
    assert inside_outer == [Model("pristine")]
    assert approvals[0] == 2
    assert form.model == Model("from-inner-reset")


def _start_blocked_reset_approval(
    persisted: list[Model] | None = None,
) -> tuple[FormVM[Model], Event, Thread, list[Model], list[BaseException]]:
    """Start an approval on its own thread whose reset blocks until released."""
    in_reset = Event()
    release_reset = Event()
    form: FormVM[Model]

    async def persister(model: Model) -> None:
        if persisted is not None:
            persisted.append(model)

    def reset(_: Model) -> Model:
        in_reset.set()
        assert release_reset.wait(HANG_GUARD)
        return Model("pristine")

    form = FormVM(Model("initial"), persister, reset_on_approved=reset)
    form.set_model(Model("edited"))
    seen: list[Model] = []
    form.on_approved.subscribe(lambda _: seen.append(form.model))
    failures: list[BaseException] = []

    def approve() -> None:
        try:
            asyncio.run(form.approve_async())
        except BaseException as error:
            failures.append(error)

    approver = Thread(target=approve, daemon=True)
    approver.start()
    assert in_reset.wait(HANG_GUARD)
    return form, release_reset, approver, seen, failures


def _run_foreign(action: Any) -> None:
    """Run *action* on another thread and require it to finish in time."""
    done = Event()

    def target() -> None:
        action()
        done.set()

    worker = Thread(target=target, daemon=True)
    worker.start()
    # The approving thread is still blocked in the reset: the commit holds
    # no other thread (spec/20 §5.3 rule 7).
    assert done.wait(HANG_GUARD)
    worker.join(timeout=HANG_GUARD)
    assert not worker.is_alive()


def test_another_threads_update_during_the_commit_is_not_held_and_the_reset_wins() -> None:
    form, release_reset, approver, seen, failures = _start_blocked_reset_approval()

    try:
        _run_foreign(lambda: form.set_model(Model("foreign")))
        # The foreign call committed at once, not queued.
        assert form.model == Model("foreign")
    finally:
        release_reset.set()
    approver.join(timeout=HANG_GUARD * 2)

    assert not approver.is_alive()
    assert failures == []
    # The configured reset stays authoritative (spec/20 §5.3).
    assert seen == [Model("pristine")]
    assert form.model == Model("pristine")
    assert form.snapshot == Model("pristine")


def test_another_threads_approve_during_the_commit_is_refused() -> None:
    persisted: list[Model] = []
    form, release_reset, approver, seen, failures = _start_blocked_reset_approval(persisted)

    try:
        _run_foreign(lambda: asyncio.run(form.approve_async()))
    finally:
        release_reset.set()
    approver.join(timeout=HANG_GUARD * 2)

    assert not approver.is_alive()
    assert failures == []
    # The approval was still in flight, so the foreign call was refused and
    # the persister ran once (FORM-031).
    assert persisted == [Model("edited")]
    assert seen == [Model("pristine")]


def test_another_threads_dispose_during_the_commit_suppresses_settlement() -> None:
    form, release_reset, approver, seen, failures = _start_blocked_reset_approval()

    try:
        _run_foreign(form.dispose)
    finally:
        release_reset.set()
    approver.join(timeout=HANG_GUARD * 2)

    assert not approver.is_alive()
    assert failures == []
    # Disposal suppresses the whole settlement (spec/20 §5.3, §10).
    assert seen == []
    assert form.model == Model("edited")

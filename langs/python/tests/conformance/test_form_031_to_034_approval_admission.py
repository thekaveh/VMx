"""FORM-031..034 — FormVM single-flight approval admission.

Per spec/20-form-vm.md §5.3 and ADR-0143. Every persister used here blocks on a
gate the test settles explicitly, so no case depends on timing; each wait is
bounded so a regression fails instead of hanging.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable, Coroutine
from threading import Event, Thread
from typing import Any

import pytest

from vmx.forms import FormVM

_TIMEOUT = 2.0


@dataclasses.dataclass(frozen=True)
class Model:
    value: str


def _required(model: Model) -> str | None:
    return "required" if not model.value else None


class GatedPersister:
    """Persister whose every call blocks until the test releases its gate."""

    def __init__(self) -> None:
        self.calls: list[Model] = []
        self.on_enter: Callable[[Model], Awaitable[None]] | None = None
        self._gates: list[asyncio.Future[None]] = []
        self._entered = asyncio.Event()

    async def __call__(self, model: Model) -> None:
        self.calls.append(model)
        gate: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._gates.append(gate)
        self._entered.set()
        hook, self.on_enter = self.on_enter, None
        if hook is not None:
            await hook(model)
        await gate

    async def wait_entered(self, count: int) -> None:
        async def entered() -> None:
            while len(self._gates) < count:
                self._entered.clear()
                await self._entered.wait()

        await asyncio.wait_for(entered(), _TIMEOUT)

    def release(self, index: int, error: BaseException | None = None) -> None:
        if error is None:
            self._gates[index].set_result(None)
        else:
            self._gates[index].set_exception(error)


class Signals:
    """Records every observable FormVM signal."""

    def __init__(self, form: FormVM[Model]) -> None:
        self.approved: list[Model] = []
        self.approve_errors: list[BaseException] = []
        self.errors_changed: list[dict[str, str]] = []
        self.can_execute_changed = 0
        form.on_approved.subscribe(self.approved.append)
        form.approve_errors.subscribe(self.approve_errors.append)
        form.errors_changed.subscribe(self.errors_changed.append)
        form.approve_command.can_execute_changed.subscribe(self._count)

    def _count(self, _: None) -> None:
        self.can_execute_changed += 1

    def counts(self) -> tuple[int, int, int, int]:
        return (
            len(self.approved),
            len(self.approve_errors),
            len(self.errors_changed),
            self.can_execute_changed,
        )


def _state(form: FormVM[Model]) -> tuple[Model, Model, dict[str, str], bool, bool]:
    return form.model, form.snapshot, form.errors, form.is_dirty, form.is_valid


def _run_refused(approval: Coroutine[Any, Any, None]) -> None:
    """Drive a refused ``approve_async`` from synchronous code.

    A refused call completes without suspending; an admitted one would reach
    the persister's gate and suspend.
    """
    try:
        approval.send(None)
    except StopIteration:
        return
    approval.close()
    raise AssertionError("approve_async suspended: the call was admitted")


async def _command_approvals() -> list[BaseException | None]:
    """Await every approval the fire-and-forget command scheduled on this loop."""
    pending = asyncio.all_tasks() - {asyncio.current_task()}
    results = await asyncio.wait_for(
        asyncio.gather(*pending, return_exceptions=True),
        _TIMEOUT,
    )
    return [result if isinstance(result, BaseException) else None for result in results]


# ---------------------------------------------------------------------------
# FORM-031 — a second approval during an in-flight approval is refused
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-031")
async def test_form_031_second_approval_from_every_source_is_refused() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("first"))
    signals = Signals(form)

    handler_refusals: list[str] = []

    def reenter_from_can_execute_changed(_: None) -> None:
        # Armed for the admission notification only; settlement re-enables approval.
        if handler_refusals:
            return
        _run_refused(form.approve_async())
        form.approve_command.execute()
        handler_refusals.append("refused")

    form.approve_command.can_execute_changed.subscribe(reenter_from_can_execute_changed)

    persister_refusals: list[str] = []

    async def reenter_from_persister(_: Model) -> None:
        await form.approve_async()
        persister_refusals.append("refused")

    persister.on_enter = reenter_from_persister

    first = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    assert handler_refusals == ["refused"]
    assert persister_refusals == ["refused"]

    state = _state(form)
    await asyncio.wait_for(form.approve_async(), _TIMEOUT)
    form.approve_command.execute()

    assert persister.calls == [Model("first")]
    assert _state(form) == state
    assert signals.approved == []
    assert signals.approve_errors == []
    assert signals.errors_changed == []
    assert signals.can_execute_changed == 1, "only the admission notification"

    persister.release(0)
    await asyncio.wait_for(first, _TIMEOUT)

    assert persister.calls == [Model("first")], "no refused call persisted later"
    assert form.snapshot == Model("first")
    assert signals.approved == [Model("first")]

    form.set_model(Model("second"))
    second = asyncio.create_task(form.approve_async())
    await persister.wait_entered(2)
    assert persister.calls == [Model("first"), Model("second")]
    persister.release(1)
    await asyncio.wait_for(second, _TIMEOUT)

    assert form.snapshot == Model("second")
    assert not form.is_dirty
    assert signals.approved == [Model("first"), Model("second")]
    assert signals.approve_errors == []


@pytest.mark.conformance("FORM-031")
async def test_form_031_command_executed_twice_persists_once() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("edited"))
    signals = Signals(form)

    form.approve_command.execute()
    form.approve_command.execute()
    await persister.wait_entered(1)
    await asyncio.wait_for(form.approve_async(), _TIMEOUT)

    assert persister.calls == [Model("edited")]
    persister.release(0)
    assert await _command_approvals() == [None]

    assert persister.calls == [Model("edited")]
    assert form.snapshot == Model("edited")
    assert signals.approved == [Model("edited")]
    assert signals.approve_errors == []


@pytest.mark.conformance("FORM-031")
def test_form_031_cross_thread_approval_is_refused_while_in_flight() -> None:
    entered = Event()
    release = Event()
    calls: list[Model] = []

    async def persist(model: Model) -> None:
        calls.append(model)
        entered.set()
        released = await asyncio.get_running_loop().run_in_executor(None, release.wait, _TIMEOUT)
        assert released

    form = FormVM(Model("initial"), persist)
    form.set_model(Model("first"))
    signals = Signals(form)
    failures: list[BaseException] = []

    def approve_on_own_loop() -> None:
        try:
            asyncio.run(form.approve_async())
        except BaseException as error:
            failures.append(error)

    approver = Thread(target=approve_on_own_loop, daemon=True)
    approver.start()
    try:
        assert entered.wait(_TIMEOUT)
        state = _state(form)
        refused: list[str] = []

        def approve_again() -> None:
            try:
                asyncio.run(asyncio.wait_for(form.approve_async(), _TIMEOUT))
                form.approve_command.execute()
                refused.append("returned")
            except BaseException as error:
                failures.append(error)

        contender = Thread(target=approve_again, daemon=True)
        contender.start()
        contender.join(_TIMEOUT)

        assert not contender.is_alive()
        assert refused == ["returned"]
        assert calls == [Model("first")]
        assert _state(form) == state
        assert not form.approve_command.can_execute()
        assert signals.approved == []
    finally:
        release.set()
        approver.join(_TIMEOUT)

    assert not approver.is_alive()
    assert failures == []
    assert calls == [Model("first")]
    assert form.snapshot == Model("first")
    assert signals.approved == [Model("first")]
    assert signals.approve_errors == []


# ---------------------------------------------------------------------------
# FORM-032 — the approve command is disabled while an approval is in flight
# ---------------------------------------------------------------------------


def _counting_persister(
    persister: GatedPersister, signals: Signals, seen_at_entry: list[int]
) -> None:
    async def record(_: Model) -> None:
        seen_at_entry.append(signals.can_execute_changed)

    persister.on_enter = record


@pytest.mark.conformance("FORM-032")
@pytest.mark.parametrize("strict", [False, True], ids=["default", "strict"])
@pytest.mark.parametrize("entry", ["awaitable", "command"])
async def test_form_032_command_disabled_in_flight_and_success_settles_once(
    strict: bool, entry: str
) -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister, strict=strict)
    form.set_model(Model("edited"))
    assert form.approve_command.can_execute()
    signals = Signals(form)
    seen_at_entry: list[int] = []
    _counting_persister(persister, signals, seen_at_entry)

    if entry == "awaitable":
        approval: asyncio.Task[None] | None = asyncio.create_task(form.approve_async())
    else:
        form.approve_command.execute()
        approval = None
        # Admission is synchronous on the command path: the persister is not
        # running yet, but the command is already disabled and notified.
        assert persister.calls == []
        assert signals.can_execute_changed == 1
        assert not form.approve_command.can_execute()
    await persister.wait_entered(1)

    assert seen_at_entry == [1], "one admission notification before the persister runs"
    assert not form.approve_command.can_execute()

    persister.release(0)
    if approval is not None:
        await asyncio.wait_for(approval, _TIMEOUT)
    else:
        assert await _command_approvals() == [None]

    assert signals.can_execute_changed == 2, "exactly one settlement notification"
    assert form.snapshot == Model("edited")
    # Only the validity and strict gates remain: the pristine form is
    # approvable again unless strict mode requires a change.
    assert form.approve_command.can_execute() is (not strict)


@pytest.mark.conformance("FORM-032")
@pytest.mark.parametrize("strict", [False, True], ids=["default", "strict"])
async def test_form_032_persister_failure_settles_once(strict: bool) -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister, strict=strict)
    form.set_model(Model("edited"))
    signals = Signals(form)
    seen_at_entry: list[int] = []
    _counting_persister(persister, signals, seen_at_entry)
    boom = RuntimeError("persist failed")

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    assert seen_at_entry == [1]
    assert not form.approve_command.can_execute()

    persister.release(0, boom)
    with pytest.raises(RuntimeError) as raised:
        await asyncio.wait_for(approval, _TIMEOUT)

    assert raised.value is boom
    assert signals.can_execute_changed == 2
    assert form.approve_command.can_execute(), "still valid and dirty"
    assert _state(form) == (Model("edited"), Model("initial"), {}, True, True)


@pytest.mark.conformance("FORM-032")
@pytest.mark.parametrize("strict", [False, True], ids=["default", "strict"])
async def test_form_032_reset_failure_after_persist_settles_once(strict: bool) -> None:
    boom = RuntimeError("reset failed")

    def fail(_: Model) -> Model:
        raise boom

    persister = GatedPersister()
    form = FormVM(Model("initial"), persister, strict=strict, reset_on_approved=fail)
    form.set_model(Model("edited"))
    signals = Signals(form)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    assert signals.can_execute_changed == 1
    assert not form.approve_command.can_execute()

    persister.release(0)
    with pytest.raises(RuntimeError) as raised:
        await asyncio.wait_for(approval, _TIMEOUT)

    assert raised.value is boom
    assert persister.calls == [Model("edited")]
    assert signals.can_execute_changed == 2
    assert form.approve_command.can_execute()
    assert _state(form) == (Model("edited"), Model("initial"), {}, True, True)
    assert signals.approved == []


@pytest.mark.conformance("FORM-032")
async def test_form_032_cancelled_approval_settles_once_and_readmits() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("edited"))
    signals = Signals(form)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    approval.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(approval, _TIMEOUT)

    assert signals.can_execute_changed == 2
    assert form.approve_command.can_execute()
    assert form.snapshot == Model("initial")

    retry = asyncio.create_task(form.approve_async())
    await persister.wait_entered(2)
    persister.release(1)
    await asyncio.wait_for(retry, _TIMEOUT)
    assert form.snapshot == Model("edited")


@pytest.mark.conformance("FORM-032")
async def test_form_032_settlement_notifies_once_in_order_when_errors_change() -> None:
    persister = GatedPersister()
    form = FormVM(
        Model("initial"),
        persister,
        validators={"value": _required},
        reset_on_approved=lambda _: Model(""),
    )
    form.set_model(Model("edited"))
    trace: list[str] = []
    form.errors_changed.subscribe(lambda errors: trace.append(f"errors:{sorted(errors)}"))
    form.approve_command.can_execute_changed.subscribe(
        lambda _: trace.append(f"can_execute:{form.approve_command.can_execute()}")
    )
    form.on_approved.subscribe(lambda model: trace.append(f"approved:{model.value}"))

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    persister.release(0)
    await asyncio.wait_for(approval, _TIMEOUT)

    # The validity change shares the one settlement notification.
    assert trace == [
        "can_execute:False",
        "errors:['value']",
        "can_execute:False",
        "approved:edited",
    ]


# ---------------------------------------------------------------------------
# FORM-033 — settlement clears admission before publishing the outcome
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-033")
async def test_form_033_on_approved_subscriber_approval_is_admitted() -> None:
    persister = GatedPersister()
    form = FormVM(
        Model("initial"),
        persister,
        reset_on_approved=lambda model: Model(f"reset:{model.value}"),
    )
    form.set_model(Model("edited"))
    observed: list[tuple[bool, Model, Model]] = []
    follow_ups: list[asyncio.Task[None]] = []

    def approve_again(_: Model) -> None:
        if follow_ups:
            return
        observed.append((form.approve_command.can_execute(), form.model, form.snapshot))
        follow_ups.append(asyncio.get_running_loop().create_task(form.approve_async()))

    form.on_approved.subscribe(approve_again)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    persister.release(0)
    await asyncio.wait_for(approval, _TIMEOUT)

    assert observed == [(True, Model("reset:edited"), Model("reset:edited"))]
    await persister.wait_entered(2)
    assert persister.calls == [Model("edited"), Model("reset:edited")]
    persister.release(1)
    await asyncio.wait_for(follow_ups[0], _TIMEOUT)
    assert form.snapshot == Model("reset:reset:edited")


@pytest.mark.conformance("FORM-033")
async def test_form_033_on_approved_subscriber_is_admitted_synchronously() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("edited"))
    observed: list[tuple[bool, bool]] = []

    def execute_again(_: Model) -> None:
        if observed:
            return
        before = form.approve_command.can_execute()
        form.approve_command.execute()
        # Admitted inside the notification: the new approval is now in flight.
        observed.append((before, form.approve_command.can_execute()))

    form.on_approved.subscribe(execute_again)

    form.approve_command.execute()
    await persister.wait_entered(1)
    persister.release(0)
    await persister.wait_entered(2)

    assert observed == [(True, False)]
    assert persister.calls == [Model("edited"), Model("edited")]
    persister.release(1)
    assert await _command_approvals() == [None]
    assert form.approve_command.can_execute()


@pytest.mark.conformance("FORM-033")
async def test_form_033_approve_errors_subscriber_approval_is_admitted() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister, validators={"value": _required})
    form.set_model(Model("edited"))
    signals = Signals(form)
    boom = RuntimeError("persist failed")
    observed: list[tuple[bool, tuple[Model, Model, dict[str, str], bool, bool]]] = []
    follow_ups: list[asyncio.Task[None]] = []
    failure_seen = asyncio.Event()

    def approve_again(_: BaseException) -> None:
        observed.append((form.approve_command.can_execute(), _state(form)))
        follow_ups.append(asyncio.get_running_loop().create_task(form.approve_async()))
        failure_seen.set()

    form.approve_errors.subscribe(approve_again)

    form.approve_command.execute()
    await persister.wait_entered(1)
    persister.release(0, boom)
    await asyncio.wait_for(failure_seen.wait(), _TIMEOUT)

    assert signals.approve_errors == [boom]
    assert observed == [(True, (Model("edited"), Model("initial"), {}, True, True))]
    assert signals.errors_changed == []
    await persister.wait_entered(2)
    persister.release(1)
    await asyncio.wait_for(follow_ups[0], _TIMEOUT)

    assert persister.calls == [Model("edited"), Model("edited")]
    assert signals.approve_errors == [boom], "emitted exactly once"
    assert signals.approved == [Model("edited")]
    assert form.snapshot == Model("edited")


@pytest.mark.conformance("FORM-033")
async def test_form_033_awaiter_retry_after_failure_is_admitted() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("edited"))
    signals = Signals(form)
    boom = RuntimeError("persist failed")

    async def approve_with_retry() -> BaseException:
        try:
            await form.approve_async()
        except RuntimeError as error:
            await form.approve_async()
            return error
        raise AssertionError("the first approval should have failed")

    caller = asyncio.create_task(approve_with_retry())
    await persister.wait_entered(1)
    persister.release(0, boom)
    await persister.wait_entered(2)
    persister.release(1)

    assert await asyncio.wait_for(caller, _TIMEOUT) is boom
    assert persister.calls == [Model("edited"), Model("edited")]
    assert signals.approve_errors == [], "the awaitable path never emits there"
    assert signals.approved == [Model("edited")]
    assert form.snapshot == Model("edited")


# ---------------------------------------------------------------------------
# FORM-034 — edits, deny, and disposal during an in-flight approval
# ---------------------------------------------------------------------------


@pytest.mark.conformance("FORM-034")
async def test_form_034_set_model_during_flight_keeps_captured_commit() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("captured"))
    signals = Signals(form)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    form.set_model(Model("newer"))
    assert form.model == Model("newer"), "set_model is not blocked"
    persister.release(0)
    await asyncio.wait_for(approval, _TIMEOUT)

    assert form.snapshot == Model("captured")
    assert form.model == Model("newer")
    assert form.is_dirty
    assert signals.approved == [Model("captured")]


@pytest.mark.conformance("FORM-034")
async def test_form_034_deny_during_flight_keeps_captured_commit() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.set_model(Model("captured"))
    signals = Signals(form)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    form.deny_command.execute()
    assert form.model == Model("initial"), "deny reverts to the current snapshot"
    persister.release(0)
    await asyncio.wait_for(approval, _TIMEOUT)

    assert form.snapshot == Model("captured")
    assert form.model == Model("initial")
    assert form.is_dirty
    assert signals.approved == [Model("captured")]


@pytest.mark.conformance("FORM-034")
@pytest.mark.parametrize("edit", ["set_model", "deny"])
async def test_form_034_reset_replaces_edit_made_during_flight(edit: str) -> None:
    persister = GatedPersister()
    form = FormVM(
        Model("initial"),
        persister,
        reset_on_approved=lambda model: Model(f"reset:{model.value}"),
    )
    form.set_model(Model("captured"))
    signals = Signals(form)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    if edit == "set_model":
        form.set_model(Model("newer"))
    else:
        form.deny_command.execute()
        assert form.model == Model("initial")
    persister.release(0)
    await asyncio.wait_for(approval, _TIMEOUT)

    assert form.model == Model("reset:captured")
    assert form.snapshot == Model("reset:captured")
    assert not form.is_dirty
    assert signals.approved == [Model("captured")]


@pytest.mark.conformance("FORM-034")
def test_form_034_cross_thread_edits_are_not_blocked() -> None:
    entered = Event()
    release = Event()

    async def persist(_: Model) -> None:
        entered.set()
        released = await asyncio.get_running_loop().run_in_executor(None, release.wait, _TIMEOUT)
        assert released

    form = FormVM(Model("initial"), persist)
    form.set_model(Model("captured"))
    approver = Thread(target=lambda: asyncio.run(form.approve_async()), daemon=True)
    approver.start()
    try:
        assert entered.wait(_TIMEOUT)
        editor = Thread(target=lambda: form.set_model(Model("newer")), daemon=True)
        editor.start()
        editor.join(_TIMEOUT)
        assert not editor.is_alive()
        assert form.model == Model("newer")

        denier = Thread(target=form.deny_command.execute, daemon=True)
        denier.start()
        denier.join(_TIMEOUT)
        assert not denier.is_alive()
        assert form.model == Model("initial")
    finally:
        release.set()
        approver.join(_TIMEOUT)

    assert not approver.is_alive()
    assert form.snapshot == Model("captured")
    assert form.model == Model("initial")
    assert form.is_dirty


@pytest.mark.conformance("FORM-034")
@pytest.mark.parametrize("outcome", ["success", "failure"])
@pytest.mark.parametrize("entry", ["awaitable", "command"])
async def test_form_034_disposal_during_flight_suppresses_settlement(
    entry: str, outcome: str
) -> None:
    persister = GatedPersister()
    resets: list[Model] = []
    form = FormVM(
        Model("initial"),
        persister,
        validators={"value": _required},
        # Would change the error map, so a leaked settlement would emit.
        reset_on_approved=lambda model: (resets.append(model), Model(""))[1],
    )
    form.set_model(Model("edited"))
    signals = Signals(form)
    loop = asyncio.get_running_loop()
    callback_errors: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: callback_errors.append(context))
    boom = RuntimeError("late persister failure")
    try:
        if entry == "awaitable":
            approval: asyncio.Task[None] | None = asyncio.create_task(form.approve_async())
        else:
            approval = None
            form.approve_command.execute()
        await persister.wait_entered(1)

        form.dispose()
        after_dispose = signals.counts()
        persister.release(0, boom if outcome == "failure" else None)

        if approval is not None:
            if outcome == "failure":
                # The awaiter of the admitted call still observes its failure.
                with pytest.raises(RuntimeError):
                    await asyncio.wait_for(approval, _TIMEOUT)
            else:
                await asyncio.wait_for(approval, _TIMEOUT)
        else:
            results = await _command_approvals()
            assert len(results) == 1
    finally:
        loop.set_exception_handler(None)

    assert signals.counts() == after_dispose, "nothing emitted after disposal"
    assert signals.approved == []
    assert signals.approve_errors == []
    assert resets == []
    assert form.model == Model("edited")
    assert form.snapshot == Model("initial")
    assert callback_errors == []

    await asyncio.wait_for(form.approve_async(), _TIMEOUT)
    form.approve_command.execute()
    assert persister.calls == [Model("edited")]


async def test_dispose_from_admission_notification_skips_persister() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    form.approve_command.can_execute_changed.subscribe(lambda _: form.dispose())

    await asyncio.wait_for(form.approve_async(), _TIMEOUT)

    assert persister.calls == []
    assert form.snapshot == Model("initial")


async def test_failing_admission_observer_does_not_wedge_the_form() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    boom = RuntimeError("observer failed")
    failures = [boom]

    def fail_once(_: None) -> None:
        if failures:
            raise failures.pop()

    form.approve_command.can_execute_changed.subscribe(fail_once)

    with pytest.raises(RuntimeError) as raised:
        await asyncio.wait_for(form.approve_async(), _TIMEOUT)
    assert raised.value is boom
    assert persister.calls == []
    assert form.approve_command.can_execute()

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    persister.release(0)
    await asyncio.wait_for(approval, _TIMEOUT)
    assert persister.calls == [Model("initial")]


async def test_failure_settlement_observer_error_does_not_replace_persister_failure() -> None:
    persister = GatedPersister()
    form = FormVM(Model("initial"), persister)
    boom = RuntimeError("persist failed")
    notifications: list[None] = []

    def fail_on_settlement(value: None) -> None:
        notifications.append(value)
        if len(notifications) == 2:
            raise KeyError("observer failed")

    form.approve_command.can_execute_changed.subscribe(fail_on_settlement)

    approval = asyncio.create_task(form.approve_async())
    await persister.wait_entered(1)
    persister.release(0, boom)
    with pytest.raises(RuntimeError) as raised:
        await asyncio.wait_for(approval, _TIMEOUT)

    assert raised.value is boom
    assert len(notifications) == 2
    assert form.approve_command.can_execute()

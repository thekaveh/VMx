"""FormVM callbacks run with no form lock held (spec/20 §5.4, §5.5, ADR-0215).

- #1427: a preparation callback that waits for another thread, which then
  reads or calls the same form, no longer deadlocks. The other thread's call
  commits at once, and the overtaken update runs again as a new call. A
  ``dispose()`` from the other thread marks the form disposed and returns; the
  teardown runs when the preparing call returns.
- #1452: another thread's ``set_model`` or deny while the post-persist commit
  runs its callbacks commits at once. A configured reset then overwrites it.
- #1426: a call in its own pre-publication window does not wait for another
  thread's scope, and a refused ``dispose()`` wakes the scope waiters at once.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable
from threading import Event, Thread
from typing import Any

from tests.liveness import HANG_GUARD
from tests.unit.forms.test_form_vm_publication_wait_graph import Model as WaitModel
from tests.unit.forms.test_form_vm_publication_wait_graph import _Scenario
from tests.wait_graph_seams import wait_until_waiting
from vmx.forms import FormVM
from vmx.messages import PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class Model:
    value: str


async def _noop(_: object) -> None:
    return None


def _run_in_thread(action: Callable[[], object]) -> tuple[bool, list[BaseException]]:
    """Run *action* on a new thread; return whether it finished in time and its failures."""
    failures: list[BaseException] = []

    def body() -> None:
        try:
            action()
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=body, daemon=True)
    thread.start()
    thread.join(HANG_GUARD)
    return not thread.is_alive(), failures


def _model_values(hub: MessageHub[Any], form: FormVM[Model]) -> list[str]:
    values: list[str] = []

    def record(message: object) -> None:
        if isinstance(message, PropertyChangedMessage) and message.property_name == "model":
            values.append(form.model.value)

    hub.messages.subscribe(record)
    return values


# ── #1427: a callback that waits for another thread ─────────────────────────


def test_another_threads_set_model_during_a_validator_commits_and_the_update_runs_again() -> None:
    hub: MessageHub[Any] = MessageHub()
    form: FormVM[Model] | None = None
    finished: list[bool] = []
    validated: list[str] = []

    def validate(model: Model) -> str | None:
        validated.append(model.value)
        if model.value == "1" and not finished:
            assert form is not None
            target = form
            finished.append(_run_in_thread(lambda: target.set_model(Model("2")))[0])
        return None

    form = FormVM(Model("0"), _noop, hub=hub, validators={"value": validate})
    published = _model_values(hub, form)

    form.set_model(Model("1"))

    assert finished == [True]
    # The other thread committed "2"; the overtaken update then ran again.
    assert published == ["2", "1"]
    assert validated == ["0", "1", "2", "1"]
    assert form.model == Model("1")


def test_another_threads_deny_during_a_validator_commits_and_the_update_runs_again() -> None:
    form: FormVM[Model] | None = None
    finished: list[bool] = []
    denied: list[Model] = []

    def validate(model: Model) -> str | None:
        if model.value == "1" and not finished:
            assert form is not None
            target = form

            def deny() -> None:
                target.deny_command.execute()
                denied.append(target.model)

            finished.append(_run_in_thread(deny)[0])
        return None

    form = FormVM(Model("0"), _noop, validators={"value": validate})
    form.set_model(Model("x"))

    form.set_model(Model("1"))

    assert finished == [True]
    assert denied == [Model("0")]
    assert form.model == Model("1")
    assert form.snapshot == Model("0")


def test_another_threads_reads_during_a_validator_return_the_committed_state() -> None:
    form: FormVM[Model] | None = None
    reads: list[object] = []
    finished: list[bool] = []

    def validate(model: Model) -> str | None:
        if model.value == "1" and not finished:
            assert form is not None
            target = form

            def read() -> None:
                reads.extend(
                    [
                        target.model,
                        target.snapshot,
                        target.errors,
                        target.is_valid,
                        target.field_error("value"),
                        target.is_dirty,
                        target.approve_command.can_execute(),
                    ]
                )

            finished.append(_run_in_thread(read)[0])
        return None

    form = FormVM(Model("0"), _noop, strict=True, validators={"value": validate})

    form.set_model(Model("1"))

    assert finished == [True]
    assert reads == [Model("0"), Model("0"), {}, True, None, False, False]
    assert form.model == Model("1")


def test_another_threads_dispose_during_a_validator_returns_and_the_update_commits_nothing() -> (
    None
):
    form: FormVM[Model] | None = None
    finished: list[bool] = []
    completed: list[str] = []
    completed_in_validator: list[bool] = []

    def validate(model: Model) -> str | None:
        if model.value == "1" and not finished:
            assert form is not None
            finished.append(_run_in_thread(form.dispose)[0])
            # The teardown waits for this update to return.
            completed_in_validator.append(bool(completed))
        return None

    form = FormVM(Model("0"), _noop, validators={"value": validate})
    form.errors_changed.subscribe(on_completed=lambda: completed.append("errors"))

    form.set_model(Model("1"))

    assert finished == [True]
    assert completed_in_validator == [False]
    assert completed == ["errors"]
    assert form.model == Model("0")


# ── #1452: another thread's edit during the post-persist commit ─────────────


def _approve_on_thread(form: FormVM[Model]) -> tuple[Thread, list[BaseException]]:
    failures: list[BaseException] = []

    def body() -> None:
        try:
            asyncio.run(form.approve_async())
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=body, daemon=True)
    thread.start()
    return thread, failures


def _edit_during_the_reset(edit: Callable[[FormVM[Model]], None]) -> FormVM[Model]:
    in_reset = Event()
    release = Event()

    def reset(_: Model) -> Model:
        in_reset.set()
        assert release.wait(HANG_GUARD)
        return Model("reset")

    form = FormVM(Model("initial"), _noop, reset_on_approved=reset)
    form.set_model(Model("edited"))
    approver, failures = _approve_on_thread(form)
    try:
        assert in_reset.wait(HANG_GUARD)
        finished, edit_failures = _run_in_thread(lambda: edit(form))
        assert finished
        assert edit_failures == []
    finally:
        release.set()
    approver.join(HANG_GUARD * 2)
    assert not approver.is_alive()
    assert failures == []
    return form


def test_another_threads_set_model_during_the_reset_commits_and_the_reset_overwrites_it() -> None:
    seen: list[Model] = []

    def edit(form: FormVM[Model]) -> None:
        form.set_model(Model("other"))
        seen.append(form.model)

    form = _edit_during_the_reset(edit)

    assert seen == [Model("other")]
    assert form.model == Model("reset")
    assert not form.is_dirty


def test_another_threads_deny_during_the_reset_commits_and_the_reset_overwrites_it() -> None:
    seen: list[Model] = []

    def edit(form: FormVM[Model]) -> None:
        form.deny_command.execute()
        seen.append(form.model)

    form = _edit_during_the_reset(edit)

    assert seen == [Model("initial")]
    assert form.model == Model("reset")
    assert not form.is_dirty


def test_another_threads_set_model_during_the_snapshot_advance_stands() -> None:
    in_snapshotter = Event()
    release = Event()
    armed = [False]

    def snapshotter(model: Model) -> Model:
        if armed[0]:
            armed[0] = False
            in_snapshotter.set()
            assert release.wait(HANG_GUARD)
        return dataclasses.replace(model)

    form = FormVM(Model("initial"), _noop, snapshotter=snapshotter)
    form.set_model(Model("edited"))
    armed[0] = True
    approver, failures = _approve_on_thread(form)
    try:
        assert in_snapshotter.wait(HANG_GUARD)
        finished, edit_failures = _run_in_thread(lambda: form.set_model(Model("other")))
        assert finished
        assert edit_failures == []
        assert form.model == Model("other")
    finally:
        release.set()
    approver.join(HANG_GUARD * 2)

    assert not approver.is_alive()
    assert failures == []
    assert form.model == Model("other")
    assert form.snapshot == Model("edited")


# ── #1426 case 1: a call in its own pre-publication window does not wait ────


def _validator(model: Model) -> str | None:
    return "bad value" if model.value == "bad" else None


def _update_in_own_window_while_another_thread_publishes(
    update: Callable[[FormVM[Model]], None],
) -> tuple[FormVM[Model], list[Model]]:
    a_persisting = Event()
    b_in_sink = Event()
    release_b = Event()
    a_returned = Event()
    approved: list[Model] = []
    form: FormVM[Model] | None = None

    async def persist(_: Model) -> None:
        # Hold the approval until thread B holds its update scope.
        a_persisting.set()
        assert b_in_sink.wait(HANG_GUARD)

    def reset(_: Model) -> Model:
        assert form is not None
        update(form)
        a_returned.set()
        return Model("reset")

    form = FormVM(
        Model("initial"),
        persist,
        validators={"value": _validator},
        reset_on_approved=reset,
    )
    form.set_model(Model("edited"))
    form.on_approved.subscribe(lambda _: approved.append(form.model))

    def sink(errors: dict[str, str]) -> None:
        if errors and not b_in_sink.is_set():
            b_in_sink.set()
            assert release_b.wait(HANG_GUARD * 2)

    form.errors_changed.subscribe(sink)
    approver, failures = _approve_on_thread(form)
    assert a_persisting.wait(HANG_GUARD)
    target = form
    b = Thread(target=lambda: target.set_model(Model("bad")), daemon=True)
    b.start()
    try:
        # A's call returns while B still holds its update scope.
        assert a_returned.wait(HANG_GUARD)
    finally:
        release_b.set()
    approver.join(HANG_GUARD * 3)
    b.join(HANG_GUARD * 3)
    assert not approver.is_alive()
    assert not b.is_alive()
    assert failures == []
    return form, approved


def test_set_model_in_its_own_pre_publication_window_does_not_wait_for_another_threads_scope() -> (
    None
):
    form, approved = _update_in_own_window_while_another_thread_publishes(
        lambda form: form.set_model(Model("v"))
    )

    # on_approved saw the reset state; the queued call replayed after it.
    assert approved == [Model("reset")]
    assert form.model == Model("v")


def test_deny_in_its_own_pre_publication_window_does_not_wait_for_another_threads_scope() -> None:
    form, approved = _update_in_own_window_while_another_thread_publishes(
        lambda form: form.deny_command.execute()
    )

    assert approved == [Model("reset")]
    assert form.model == form.snapshot == Model("reset")


# ── #1426 case 2: a refused dispose wakes the scope waiters at once ─────────


def test_a_refused_dispose_wakes_a_waiting_call_before_the_publishers_scope_closes() -> None:
    scenario = _Scenario("errors_changed", "dispose", "x_send_first")
    form = scenario.form
    waiter_finished: list[bool] = []
    waiter_failures: list[BaseException] = []

    def y_call() -> None:
        def wait_in_set_model() -> None:
            try:
                form.set_model(WaitModel("w"))
            except BaseException as error:
                waiter_failures.append(error)

        waiter = Thread(target=wait_in_set_model, daemon=True)
        waiter.start()
        assert waiter.ident is not None
        wait_until_waiting(waiter.ident)
        # Y's wait closes a cycle through X's hub send, so it is refused.
        form.dispose()
        # X's scope stays open until Y returns from its drain.
        waiter.join(HANG_GUARD)
        waiter_finished.append(not waiter.is_alive())

    scenario._y_call = y_call  # type: ignore[method-assign]

    scenario.run()

    assert scenario.x_failures == []
    assert scenario.y_failures == []
    assert waiter_finished == [True]
    assert waiter_failures == []
    assert form.model == WaitModel("bad")
    assert sorted(scenario.completed) == ["approved", "errors"]

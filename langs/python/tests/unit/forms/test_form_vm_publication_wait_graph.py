"""FormVM publication-scope waits join the wait-for graph (#1170, ADR-0176).

Thread X publishes a form notification, and X's sink sends on hub ``H``.
Thread Y drains ``H``, and Y's subscriber calls the form. Y's form wait and
X's hub send close a cycle. Each wait records an edge in
``vmx._wait_for_graph.WAITS``, so the wait that closes the cycle is refused
(spec/20 §5.5). Both arrival orders are covered:

- **X's send first.** Y's form wait is refused. A ``set_model`` or deny joins
  X's queue and replays when X's scope ends. A ``dispose`` marks the form
  disposed, and X runs the teardown when its scope ends.
- **Y's wait first.** X's send is refused and enqueues for Y's drain
  (ADR-0119). Y's call proceeds when X's scope ends, and Y's drain delivers
  X's message once.
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
from threading import Event, Thread
from typing import Any

import pytest

from tests.liveness import HANG_GUARD, join_thread, wait_event
from tests.wait_graph_seams import WaitRequests, wait_until_waiting
from vmx.forms import FormVM
from vmx.messages import PropertyChangedMessage
from vmx.services.message_hub import MessageHub


@dataclasses.dataclass(frozen=True)
class Model:
    value: str


async def _noop(_: object) -> None:
    return None


def _validator(model: Model) -> str | None:
    return "bad value" if model.value == "bad" else None


def _hub_message(property_name: str) -> PropertyChangedMessage:
    return PropertyChangedMessage.create(
        sender=None, sender_name="Probe", property_name=property_name
    )


# Each row names X's sink and Y's call, as in the #1170 table. Y's "read" is
# the control: it never waits for a publication scope.
ROWS = [
    ("errors_changed", "read"),
    ("errors_changed", "set_model"),
    ("errors_changed", "deny"),
    ("errors_changed", "dispose"),
    ("on_approved", "read"),
    ("on_approved", "set_model"),
    ("on_approved", "deny"),
    ("on_approved", "dispose"),
    ("on_approved", "approve"),
    ("on_approved_set_model", "read"),
    ("on_approved_set_model", "set_model"),
    ("reset_errors_changed", "read"),
    ("reset_errors_changed", "set_model"),
    ("settlement_can_execute", "read"),
    ("settlement_can_execute", "set_model"),
]

CASES = [
    pytest.param(sink, call, order, id=f"{sink}-{call}-{order}")
    for sink, call in ROWS
    for order in ("x_send_first", "y_wait_first")
    # The control call never waits, so it cannot record its wait first.
    if not (call == "read" and order == "y_wait_first")
]


class _Scenario:
    """Thread X publishes on the form while thread Y holds ``H``'s drain."""

    def __init__(self, sink: str, call: str, order: str) -> None:
        self.sink = sink
        self.call = call
        self.order = order
        self.hub: MessageHub[Any] = MessageHub()
        self.persisted: list[Model] = []

        async def persister(model: Model) -> None:
            self.persisted.append(model)

        self.form = FormVM(
            Model("initial"),
            persister,
            hub=self.hub if sink == "on_approved_set_model" else None,
            validators={"value": _validator},
            reset_on_approved=(
                (lambda _: Model("bad")) if sink == "reset_errors_changed" else None
            ),
        )
        if sink != "errors_changed":
            self.form.set_model(Model("edited"))

        self.x_failures: list[BaseException] = []
        self.y_failures: list[BaseException] = []
        self.x_in_sink = Event()
        self.y_draining = Event()
        self.y_release = Event()
        self.y_done = Event()
        self.x_ident = 0
        self.y_ident = 0
        self.model_after_y_call: Model | None = None
        self.completed_after_y_call: bool | None = None
        self.completed: list[str] = []
        self.approved: list[Model] = []
        self.pings = 0
        self.model_messages = 0

        self.form.errors_changed.subscribe(on_completed=lambda: self.completed.append("errors"))
        self.form.on_approved.subscribe(
            self.approved.append, on_completed=lambda: self.completed.append("approved")
        )
        self.hub.messages.subscribe(self._count)
        self.hub.messages.subscribe(self._y_subscriber)
        self._attach_x_sink()

    # ── X ────────────────────────────────────────────────────────────────

    def _attach_x_sink(self) -> None:
        armed = [True]

        def sink(*_: object) -> None:
            if not armed[0]:
                return
            armed[0] = False
            self.x_in_sink.set()
            if self.order == "y_wait_first":
                # Y records its form wait before X sends.
                wait_until_waiting(self.y_ident)
            if self.sink == "on_approved_set_model":
                # The nested update sends its model message on H while the
                # approval scope is still open.
                self.form.set_model(Model("from-x"))
            else:
                self.hub.send(_hub_message("ping"))

        if self.sink == "errors_changed" or self.sink == "reset_errors_changed":
            self.form.errors_changed.subscribe(sink)
        elif self.sink == "settlement_can_execute":
            notifications = [0]

            def on_can_execute(_: None) -> None:
                notifications[0] += 1
                if notifications[0] == 2:  # the settlement notification
                    sink()

            self.form.approve_command.can_execute_changed.subscribe(on_can_execute)
        else:
            self.form.on_approved.subscribe(sink)

    def _run_x(self) -> None:
        try:
            if self.sink == "errors_changed":
                self.form.set_model(Model("bad"))
            else:
                asyncio.run(self.form.approve_async())
        except BaseException as error:
            self.x_failures.append(error)

    # ── Y ────────────────────────────────────────────────────────────────

    def _count(self, message: object) -> None:
        if isinstance(message, PropertyChangedMessage):
            if message.property_name == "ping":
                self.pings += 1
            elif message.property_name == "model":
                self.model_messages += 1

    def _y_subscriber(self, message: object) -> None:
        if not isinstance(message, PropertyChangedMessage) or message.property_name != "trigger":
            return
        try:
            self.y_draining.set()
            assert wait_event(self.y_release)
            self._y_call()
        except BaseException as error:
            self.y_failures.append(error)
        finally:
            self.y_done.set()

    def _y_call(self) -> None:
        form = self.form
        if self.call == "read":
            _ = form.is_dirty
        elif self.call == "set_model":
            form.set_model(Model("y"))
        elif self.call == "deny":
            form.deny_command.execute()
        elif self.call == "dispose":
            form.dispose()
        else:
            asyncio.run(form.approve_async())
        self.model_after_y_call = form.model
        self.completed_after_y_call = bool(self.completed)

    def _run_y(self) -> None:
        try:
            self.hub.send(_hub_message("trigger"))
        except BaseException as error:
            self.y_failures.append(error)

    # ── Driver ───────────────────────────────────────────────────────────

    def run(self) -> None:
        y = Thread(target=self._run_y, daemon=True)
        y.start()
        assert y.ident is not None
        self.y_ident = y.ident
        assert wait_event(self.y_draining)

        x = Thread(target=self._run_x, daemon=True)
        x.start()
        assert x.ident is not None
        self.x_ident = x.ident
        try:
            assert wait_event(self.x_in_sink)
            if self.order == "x_send_first":
                # X's hub send waits for Y's drain before Y calls the form.
                wait_until_waiting(self.x_ident)
        finally:
            self.y_release.set()

        join_thread(x, 2 * HANG_GUARD)
        join_thread(y, 2 * HANG_GUARD)
        assert not x.is_alive(), "thread X stalled"
        assert not y.is_alive(), "thread Y stalled"
        assert self.y_done.is_set()


@pytest.mark.parametrize(("sink", "call", "order"), CASES)
def test_form_wait_and_hub_send_do_not_deadlock(sink: str, call: str, order: str) -> None:
    scenario = _Scenario(sink, call, order)

    scenario.run()

    assert scenario.x_failures == []
    assert scenario.y_failures == []
    form = scenario.form
    # Each of X's hub sends reaches every H subscriber exactly once.
    if sink == "on_approved_set_model":
        assert scenario.model_messages == (2 if call == "set_model" else 1)
    else:
        assert scenario.pings == 1

    refused = order == "x_send_first"
    if call == "set_model":
        # A refused call is queued, so it returns before it takes effect.
        assert (scenario.model_after_y_call == Model("y")) is not refused
        assert form.model == Model("y")
    elif call == "deny":
        if sink == "errors_changed":
            # Only this row's model differs from the snapshot before the deny.
            assert (scenario.model_after_y_call == form.snapshot) is not refused
        assert form.model == form.snapshot
    elif call == "dispose":
        # A refused dispose leaves the teardown to X's scope exit.
        assert scenario.completed_after_y_call is (not refused)
        assert sorted(scenario.completed) == ["approved", "errors"]
    elif call == "approve":
        # Y's admission and settlement waits are refused: the approval runs.
        assert scenario.persisted == [Model("edited"), Model("edited")]
        assert scenario.approved == [Model("edited"), Model("edited")]


class ReplayError(Exception):
    """A validator failure when a refused update replays."""


def test_a_refused_updates_replay_failure_propagates_from_the_publishers_update() -> None:
    """The publisher replays a refused update after its last notification.

    The first replay failure then propagates from the publisher's update
    (spec/20 §5.5). Y's call already returned, so the failure goes to X.
    """
    scenario = _Scenario("errors_changed", "set_model", "x_send_first")
    form = scenario.form
    y_call = scenario._y_call

    def failing_validator(model: Model) -> str | None:
        if model.value == "y":
            raise ReplayError("replay")
        return _validator(model)

    def y_call_then_arm() -> None:
        y_call()
        # Y's call is queued; its replay on X runs the new validator.
        form._validators["value"] = failing_validator

    scenario._y_call = y_call_then_arm  # type: ignore[method-assign]

    scenario.run()

    assert scenario.y_failures == []
    assert [type(error) for error in scenario.x_failures] == [ReplayError]
    assert scenario.model_after_y_call == Model("bad")
    assert form.model == Model("bad")
    assert scenario.pings == 1


def test_another_threads_update_waits_for_the_update_scope_and_records_its_wait() -> None:
    """A wait that closes no cycle blocks until the scope ends (spec/20 §5.5)."""
    in_sink = Event()
    release_sink = Event()
    form = FormVM(Model("initial"), _noop, validators={"value": _validator})
    order: list[str] = []

    def sink(errors: dict[str, str]) -> None:
        if errors and not in_sink.is_set():
            in_sink.set()
            assert wait_event(release_sink)
            order.append("x-errors")

    form.errors_changed.subscribe(sink)
    form.errors_changed.subscribe(lambda errors: order.append(f"errors:{sorted(errors)}"))

    def x() -> None:
        form.set_model(Model("bad"))

    def y() -> None:
        assert wait_event(in_sink)
        form.set_model(Model("y"))

    x_thread = Thread(target=x, daemon=True)
    y_thread = Thread(target=y, daemon=True)
    x_thread.start()
    y_thread.start()
    try:
        assert y_thread.ident is not None
        wait_until_waiting(y_thread.ident)
        assert form.model == Model("bad")
    finally:
        release_sink.set()
    join_thread(x_thread, 2 * HANG_GUARD)
    join_thread(y_thread, 2 * HANG_GUARD)

    assert not x_thread.is_alive()
    assert not y_thread.is_alive()
    # Error maps reach observers in commit order.
    assert order == ["x-errors", "errors:['value']", "errors:[]"]
    assert form.model == Model("y")


def test_no_notification_is_delivered_under_the_state_lock() -> None:
    """Another thread reads the form while an update's observers run (§5.5)."""
    form = FormVM(Model("initial"), _noop, validators={"value": _validator}, strict=True)
    reads: list[bool] = []

    def read_from_another_thread(*_: object) -> None:
        reader = Thread(target=lambda: (form.model, form.errors), daemon=True)
        reader.start()
        join_thread(reader)
        reads.append(not reader.is_alive())

    form.errors_changed.subscribe(read_from_another_thread)
    form.approve_command.can_execute_changed.subscribe(read_from_another_thread)

    form.set_model(Model("bad"))
    form.deny_command.execute()

    assert reads and all(reads)


class _NestedScenario:
    """A nested call meets another thread's open scope (spec/20 §5.4, #1472).

    Thread Y holds the drain of hub ``H``. Thread X's update sends on ``H``
    from its ``errors_changed`` sink, inside X's scope, so the send waits for
    Y. Y's subscriber then calls ``set_model``. Its wait for X's scope closes
    a cycle and is refused, so the call prepares at once (§5.5). Y's
    validator then makes a nested call, which never waits for X's scope.
    """

    OUTER = Model("outer")
    NESTED = Model("nested")

    def __init__(self, monkeypatch: pytest.MonkeyPatch, nested: str) -> None:
        self.nested = nested
        self.requests = WaitRequests(monkeypatch)
        self.hub: MessageHub[Any] = MessageHub()
        self.form = FormVM(Model("initial"), _noop, validators={"value": self._validate})
        self.failures: list[BaseException] = []
        self.y_draining = Event()
        self.y_release = Event()
        self.x_sink_returned = Event()
        self.x_ident = 0
        self.y_ident = 0
        self.nested_calls = 0
        self.requests_during_nested_call: list[bool] | None = None
        self.model_after_nested_call: Model | None = None
        self.x_scope_open_after_nested_call: bool | None = None
        self.approved_completions: list[bool] = []
        self.form.on_approved.subscribe(
            on_completed=lambda: self.approved_completions.append(self.x_sink_returned.is_set())
        )
        armed = [True]

        def x_sink(_: object) -> None:
            if threading.get_ident() != self.x_ident or not armed[0]:
                return
            armed[0] = False
            self.y_release.set()
            # Y drains H, so this send waits for Y.
            self.hub.send(_hub_message("x"))
            self.x_sink_returned.set()

        self.form.errors_changed.subscribe(x_sink)
        self.hub.messages.subscribe(self._y_subscriber)

    def _validate(self, model: Model) -> str | None:
        if model == self.OUTER and threading.get_ident() == self.y_ident:
            self._nested_call()
        return _validator(model)

    def _nested_call(self) -> None:
        self.nested_calls += 1
        before = len(self.requests.of(self.y_ident))
        if self.nested == "set_model":
            self.form.set_model(self.NESTED)
            self.model_after_nested_call = self.form.model
        else:
            self.form.dispose()
        self.x_scope_open_after_nested_call = not self.x_sink_returned.is_set()
        self.requests_during_nested_call = self.requests.of(self.y_ident)[before:]

    def _y_subscriber(self, message: object) -> None:
        if not isinstance(message, PropertyChangedMessage) or message.property_name != "go":
            return
        try:
            self.y_draining.set()
            assert wait_event(self.y_release)
            # X's hub send waits for Y before Y calls the form.
            wait_until_waiting(self.x_ident)
            self.form.set_model(self.OUTER)
        except BaseException as error:
            self.failures.append(error)

    def _run_y(self) -> None:
        self.y_ident = threading.get_ident()
        try:
            self.hub.send(_hub_message("go"))
        except BaseException as error:
            self.failures.append(error)

    def _run_x(self) -> None:
        self.x_ident = threading.get_ident()
        try:
            self.form.set_model(Model("bad"))
        except BaseException as error:
            self.failures.append(error)

    def run(self) -> None:
        y = Thread(target=self._run_y, daemon=True)
        y.start()
        assert wait_event(self.y_draining)
        x = Thread(target=self._run_x, daemon=True)
        x.start()
        try:
            join_thread(x, 2 * HANG_GUARD)
            join_thread(y, 2 * HANG_GUARD)
        finally:
            self.y_release.set()
        assert not x.is_alive(), "thread X did not return: deadlock"
        assert not y.is_alive(), "thread Y did not return: deadlock"
        assert self.failures == []
        # Y's outer wait for X's scope was refused, and the nested call ran.
        assert False in self.requests.of(self.y_ident)
        assert self.nested_calls == 1
        assert self.x_scope_open_after_nested_call is True
        # The nested call made no wait request, accepted or refused.
        assert self.requests_during_nested_call == []


def test_a_nested_set_model_never_waits_for_another_threads_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nested call joins X's queue and replays after X's scope ends (§5.4)."""
    scenario = _NestedScenario(monkeypatch, "set_model")

    scenario.run()

    assert scenario.model_after_nested_call is not None
    assert scenario.model_after_nested_call != _NestedScenario.NESTED
    assert scenario.form.model == _NestedScenario.NESTED
    assert scenario.form.is_valid


def test_a_nested_dispose_never_waits_for_another_threads_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nested dispose returns at once; the channels complete when X's scope ends."""
    scenario = _NestedScenario(monkeypatch, "dispose")

    scenario.run()

    # on_approved completed once, after X's sink returned inside X's scope.
    assert scenario.approved_completions == [True]

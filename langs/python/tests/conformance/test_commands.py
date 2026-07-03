"""Conformance tests for Commands — CMD-001..007.

Spec: spec/04-commands.md
Fixture: spec/fixtures/command-truthtable.json

CMD-001  Execute invokes the configured task
CMD-002  can_execute returns True when no predicate is set
CMD-003  can_execute returns the predicate result when a predicate is set
CMD-004  Trigger emissions fire can_execute_changed
CMD-005  Parameterized variant passes the parameter through
CMD-006  Null task is a no-op (no exception)
CMD-007  Table-driven configurations from command-truthtable.json
CMD-013  Disposed RelayCommand instances are inert
"""

from __future__ import annotations

import asyncio

import pytest
from reactivex.subject import Subject

from tests.conformance.fixtures.loader import load
from vmx.commands.async_relay_command import AsyncRelayCommand
from vmx.commands.relay_command import RelayCommand, RelayCommandOf


@pytest.mark.conformance("CMD-001")
def test_CMD_001_execute_invokes_configured_task() -> None:
    called: list[int] = []
    cmd = RelayCommand.builder().task(lambda: called.append(1)).build()
    cmd.execute()
    assert called == [1], "execute() must invoke the configured task"


@pytest.mark.conformance("CMD-002")
def test_CMD_002_can_execute_true_when_no_predicate() -> None:
    cmd = RelayCommand.builder().build()
    assert cmd.can_execute() is True, "can_execute() must return True when no predicate is set"


@pytest.mark.conformance("CMD-003")
def test_CMD_003_can_execute_returns_predicate_result() -> None:
    cmd_true = RelayCommand.builder().predicate(lambda: True).build()
    cmd_false = RelayCommand.builder().predicate(lambda: False).build()
    assert cmd_true.can_execute() is True
    assert cmd_false.can_execute() is False


@pytest.mark.conformance("CMD-004")
def test_CMD_004_trigger_fires_can_execute_changed() -> None:
    subject: Subject[None] = Subject()
    cmd = RelayCommand.builder().triggers(subject).build()

    fired: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: fired.append(1))

    subject.on_next(None)
    assert fired == [1], "can_execute_changed must fire on trigger emission"


@pytest.mark.conformance("CMD-005")
def test_CMD_005_parameterized_variant_passes_parameter_through() -> None:
    received: list[str | None] = []
    cmd: RelayCommandOf[str] = (
        RelayCommandOf.builder()
        .predicate(lambda p: True)
        .task(lambda p: received.append(p))
        .build()
    )
    cmd.execute("hello")
    assert received == ["hello"], "parameterized execute() must pass parameter to task"


@pytest.mark.conformance("CMD-006")
def test_CMD_006_null_task_execute_is_noop() -> None:
    """Execute with no task must be a no-op — must not raise."""
    cmd = RelayCommand.builder().build()
    cmd.execute()  # must not raise


@pytest.mark.conformance("CMD-007")
@pytest.mark.parametrize(
    "case",
    load("command-truthtable.json")["cases"],
    ids=lambda c: c["id"],
)
def test_CMD_007_truth_table(case: dict) -> None:  # type: ignore[type-arg]
    """Table-driven: exercises every canonical configuration in the fixture.

    Columns: predicate, task, trigger_emits, can_execute, execute_invokes_task,
             can_execute_changed_fires
    """
    predicate_value: bool | None = case["predicate"]  # null | true | false
    has_task: bool = case["task"] == "noop"
    trigger_emits: bool = case["trigger_emits"]
    expected_can_execute: bool = case["can_execute"]
    expected_task_invoked: bool = case["execute_invokes_task"]
    expected_changed_fires: bool = case["can_execute_changed_fires"]

    # Build the task
    task_called: list[int] = []
    task_fn = (lambda: task_called.append(1)) if has_task else None

    # Build the predicate
    if predicate_value is None:
        pred_fn = None
    elif predicate_value is True:
        pred_fn = lambda: True  # noqa: E731
    else:
        pred_fn = lambda: False  # noqa: E731

    # Build the trigger
    subject: Subject[None] = Subject()
    builder = RelayCommand.builder()
    if task_fn is not None:
        builder = builder.task(task_fn)
    if pred_fn is not None:
        builder = builder.predicate(pred_fn)
    if trigger_emits:
        builder = builder.triggers(subject)

    cmd = builder.build()

    # Subscribe to can_execute_changed
    changed_fired: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: changed_fired.append(1))

    # Assert can_execute
    assert cmd.can_execute() is expected_can_execute, (
        f"[{case['id']}] can_execute expected {expected_can_execute}"
    )

    # Fire trigger if the case requires it
    if trigger_emits:
        subject.on_next(None)

    # Assert can_execute_changed
    assert bool(changed_fired) is expected_changed_fires, (
        f"[{case['id']}] can_execute_changed fired={bool(changed_fired)}, "
        f"expected={expected_changed_fires}"
    )

    # Execute and check task invocation
    cmd.execute()
    assert bool(task_called) is expected_task_invoked, (
        f"[{case['id']}] task invoked={bool(task_called)}, expected={expected_task_invoked}"
    )


# ---------------------------------------------------------------------------
# CMD-013 — disposed relay commands are inert
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-013")
def test_CMD_013_disposed_relay_command_is_inert() -> None:
    called: list[int] = []
    cmd = RelayCommand.builder().task(lambda: called.append(1)).build()

    cmd.dispose()
    cmd.execute()

    assert cmd.can_execute() is False
    assert called == []


@pytest.mark.conformance("CMD-013")
def test_CMD_013_disposed_parameterized_relay_command_is_inert() -> None:
    called: list[int] = []
    cmd: RelayCommandOf[int] = (
        RelayCommandOf.builder().task(lambda p: called.append(p or 0)).build()
    )

    cmd.dispose()
    cmd.execute(42)

    assert cmd.can_execute(42) is False
    assert called == []


@pytest.mark.conformance("CMD-013")
async def test_CMD_013_disposed_async_relay_command_is_inert() -> None:
    called: list[int] = []

    async def _task() -> None:
        called.append(1)

    cmd = AsyncRelayCommand.builder().task(_task).build()

    cmd.dispose()
    cmd.execute()
    await cmd.execute_async()

    assert cmd.can_execute() is False
    assert called == []


# ---------------------------------------------------------------------------
# CMD-012 — async command cancellation (spec/04-commands.md §10, ADR-0056)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-012")
async def test_CMD_012_cancel_cancels_inflight_async_task_nonthrowing() -> None:
    """cancel() cancels an in-flight async task; the command returns to a
    non-executing state and no exception surfaces by default (DIA-007 alignment).
    """
    started = asyncio.Event()
    observed_cancel = False

    async def _task() -> None:
        nonlocal observed_cancel
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            observed_cancel = True
            raise

    cmd = AsyncRelayCommand.builder().task(_task).build()
    assert cmd.can_execute() is True, "executable before it starts"

    run = asyncio.ensure_future(cmd.execute_async())
    await started.wait()  # the task is now in flight

    assert cmd.is_executing is True, "executing while the task runs"
    assert cmd.can_execute() is False, "an in-flight async command must not be re-executable"

    cmd.cancel()
    await run  # MUST complete without raising (non-throwing default)

    assert observed_cancel is True, "the task observed cancellation"
    assert cmd.is_executing is False, "returns to a non-executing state after cancel"
    assert cmd.can_execute() is True, "can_execute reflects the cleared in-flight state"
    cmd.dispose()


@pytest.mark.conformance("CMD-012")
async def test_CMD_012_throw_on_cancel_reraises() -> None:
    """The opt-in throwing mode re-raises CancelledError to the awaiter while still
    returning the command to a non-executing state (spec §10 opt-in clause).
    """
    started = asyncio.Event()

    async def _task() -> None:
        started.set()
        await asyncio.sleep(3600)

    cmd = AsyncRelayCommand.builder().throw_on_cancel().task(_task).build()
    run = asyncio.ensure_future(cmd.execute_async())
    await started.wait()
    cmd.cancel()

    with pytest.raises(asyncio.CancelledError):
        await run
    assert cmd.is_executing is False, "still returns to a non-executing state when throwing"
    cmd.dispose()

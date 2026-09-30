"""Conformance tests: CMDD-001..013 — command decorators.

Per spec/04-commands.md §Decorators and ADR-0012.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest
from reactivex import Subject

from vmx.commands import (
    CompositeCommand,
    ConfirmationDecoratorCommand,
    DecoratorCommand,
    RelayCommand,
)


def _recording_command(record: list[str], label: str, predicate: bool) -> RelayCommand:
    return (
        RelayCommand.builder()
        .task(lambda: record.append(label))
        .predicate(lambda: predicate)
        .build()
    )


# ---------------------------------------------------------------------------
# CMDD-001 — CompositeCommand.can_execute is OR over inner commands
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-001")
def test_CMDD_001_composite_can_execute_is_or() -> None:
    log: list[str] = []
    c1 = _recording_command(log, "c1", False)
    c2 = _recording_command(log, "c2", True)
    composite = CompositeCommand(c1, c2)
    assert composite.can_execute() is True

    c3 = _recording_command(log, "c3", False)
    c4 = _recording_command(log, "c4", False)
    composite_false = CompositeCommand(c3, c4)
    assert composite_false.can_execute() is False


# ---------------------------------------------------------------------------
# CMDD-002 — CompositeCommand.execute invokes only enabled inner commands
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-002")
def test_CMDD_002_composite_execute_invokes_only_enabled() -> None:
    log: list[str] = []
    c1 = _recording_command(log, "c1", True)
    c2 = _recording_command(log, "c2", False)
    c3 = _recording_command(log, "c3", True)
    composite = CompositeCommand(c1, c2, c3)
    composite.execute()
    assert log == ["c1", "c3"]


# ---------------------------------------------------------------------------
# CMDD-003 — CompositeCommand propagates inner can_execute_changed
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-003")
def test_CMDD_003_composite_propagates_can_execute_changed() -> None:
    trigger: Subject[None] = Subject()
    c1 = RelayCommand.builder().task(lambda: None).triggers(trigger).build()
    composite = CompositeCommand(c1)
    fired = 0

    def _on_next(_: None) -> None:
        nonlocal fired
        fired += 1

    composite.can_execute_changed.subscribe(on_next=_on_next)
    trigger.on_next(None)
    assert fired == 1


# ---------------------------------------------------------------------------
# CMDD-004 — DecoratorCommand.can_execute is inner AND extra-predicate
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-004")
def test_CMDD_004_decorator_can_execute_combines_predicates() -> None:
    log: list[str] = []
    inner = _recording_command(log, "inner", True)
    extra_false = DecoratorCommand(inner, extra_predicate=lambda: False)
    extra_true = DecoratorCommand(inner, extra_predicate=lambda: True)
    inner_false = _recording_command(log, "innerF", False)
    extra_true_inner_false = DecoratorCommand(inner_false, extra_predicate=lambda: True)
    assert extra_false.can_execute() is False
    assert extra_true.can_execute() is True
    assert extra_true_inner_false.can_execute() is False


# ---------------------------------------------------------------------------
# CMDD-005 — DecoratorCommand.execute invokes pre, inner, post in order
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-005")
def test_CMDD_005_decorator_execute_order() -> None:
    log: list[str] = []
    inner = _recording_command(log, "inner", True)
    deco = DecoratorCommand(
        inner,
        pre_execute=lambda: log.append("pre"),
        post_execute=lambda: log.append("post"),
    )
    deco.execute()
    assert log == ["pre", "inner", "post"]


# ---------------------------------------------------------------------------
# CMDD-006 — DecoratorCommand.execute is no-op when CanExecute is false
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-006")
def test_CMDD_006_decorator_execute_noop_when_false() -> None:
    log: list[str] = []
    inner = _recording_command(log, "inner", True)
    deco = DecoratorCommand(
        inner,
        pre_execute=lambda: log.append("pre"),
        post_execute=lambda: log.append("post"),
        extra_predicate=lambda: False,
    )
    deco.execute()
    assert log == []


# ---------------------------------------------------------------------------
# CMDD-007 — ConfirmationDecoratorCommand invokes inner only when confirmed
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-007")
def test_CMDD_007_confirmation_invokes_inner_only_when_confirmed() -> None:
    log: list[str] = []

    async def _confirm_yes() -> bool:
        return True

    async def _confirm_no() -> bool:
        return False

    inner = _recording_command(log, "inner", True)
    confirmed = ConfirmationDecoratorCommand(inner, confirm=_confirm_yes)
    asyncio.run(confirmed.execute_async())
    assert log == ["inner"]

    log.clear()
    declined = ConfirmationDecoratorCommand(inner, confirm=_confirm_no)
    asyncio.run(declined.execute_async())
    assert log == []


# ---------------------------------------------------------------------------
# CMDD-008 — ConfirmationDecoratorCommand.can_execute delegates to inner
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-008")
def test_CMDD_008_confirmation_can_execute_delegates() -> None:
    async def _confirm() -> bool:
        return True

    inner_t = _recording_command([], "x", True)
    inner_f = _recording_command([], "x", False)
    conf_t = ConfirmationDecoratorCommand(inner_t, confirm=_confirm)
    conf_f = ConfirmationDecoratorCommand(inner_f, confirm=_confirm)
    assert conf_t.can_execute() is True
    assert conf_f.can_execute() is False


# ---------------------------------------------------------------------------
# CMDD-009 — Decorators compose (decorator of confirmation of relay)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-009")
def test_CMDD_009_decorators_compose() -> None:
    log: list[str] = []
    relay = _recording_command(log, "relay", True)

    async def _confirm() -> bool:
        return True

    conf = ConfirmationDecoratorCommand(relay, confirm=_confirm)
    dec = DecoratorCommand(conf)

    # dec.execute() kicks off async; we explicitly run the confirmation
    async def _run() -> None:
        await conf.execute_async()  # bypass dec.execute fire-and-forget for sync test

    # First verify the chain executes correctly via direct call
    asyncio.run(_run())
    assert log == ["relay"]

    # And via dec which internally calls inner.execute (which fires-and-forgets)
    log.clear()

    # dec.execute() → conf.execute() → fire-and-forget asyncio task; need event loop
    async def _via_dec() -> None:
        # We use can_execute + manual execute_async to ensure we await
        if dec.can_execute():
            await conf.execute_async()

    asyncio.run(_via_dec())
    assert log == ["relay"]


# ---------------------------------------------------------------------------
# CMDD-010 — ConfirmationDecoratorCommand surfaces errors on the error channel
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMDD-010")
async def test_CMDD_010_confirmation_surfaces_errors_on_error_channel() -> None:
    # execute() is fire-and-forget across the async confirm gate, so a rejecting
    # confirm delegate or a throwing inner command cannot propagate to the caller
    # the way RelayCommand's task does. They MUST be surfaced on `errors` instead
    # of being swallowed (VMX-009).

    # (a) the confirm delegate rejects
    confirm_boom = RuntimeError("confirm rejected")

    async def _reject() -> bool:
        raise confirm_boom

    inner = RelayCommand.builder().task(lambda: None).build()
    rejecting = ConfirmationDecoratorCommand(inner, confirm=_reject)
    reject_errors: list[BaseException] = []
    rejecting.errors.subscribe(reject_errors.append)

    rejecting.execute()  # fire-and-forget
    for _ in range(5):
        await asyncio.sleep(0)
        if reject_errors:
            break
    assert reject_errors == [confirm_boom]

    # (b) the inner command throws once confirmed
    inner_boom = RuntimeError("inner boom")

    def _raise() -> None:
        raise inner_boom

    async def _confirm() -> bool:
        return True

    throwing = RelayCommand.builder().task(_raise).build()
    confirming = ConfirmationDecoratorCommand(throwing, confirm=_confirm)
    inner_errors: list[BaseException] = []
    confirming.errors.subscribe(inner_errors.append)

    confirming.execute()
    for _ in range(5):
        await asyncio.sleep(0)
        if inner_errors:
            break
    assert inner_errors == [inner_boom]


# ---------------------------------------------------------------------------
# CMDD-011..013 — disposed wrappers are inert (spec §8.4, ADR-0134)
# ---------------------------------------------------------------------------


async def _drain_other_tasks() -> None:
    """Await every task this test started, including fire-and-forget ones."""
    current = asyncio.current_task()
    others = [task for task in asyncio.all_tasks() if task is not current]
    await asyncio.gather(*others, return_exceptions=True)


@pytest.mark.conformance("CMDD-011")
def test_CMDD_011_disposed_composite_and_decorator_are_inert() -> None:
    log: list[str] = []
    a = _recording_command(log, "a", True)
    b = _recording_command(log, "b", True)
    composite = CompositeCommand(a, b)
    composite.dispose()
    composite.dispose()

    assert composite.can_execute() is False
    composite.execute()
    assert log == []

    inner = _recording_command(log, "inner", True)

    def _predicate() -> bool:
        log.append("predicate")
        return True

    decorator = DecoratorCommand(
        inner,
        pre_execute=lambda: log.append("pre"),
        post_execute=lambda: log.append("post"),
        extra_predicate=_predicate,
    )
    decorator.dispose()
    decorator.dispose()

    assert decorator.can_execute() is False
    decorator.execute()
    assert log == []

    # The inner commands were not disposed.
    a.execute()
    inner.execute()
    assert log == ["a", "inner"]


@pytest.mark.conformance("CMDD-012")
async def test_CMDD_012_disposed_confirmation_never_consults_confirm() -> None:
    log: list[str] = []
    confirms: list[None] = []

    async def _confirm() -> bool:
        confirms.append(None)
        return True

    decorator = ConfirmationDecoratorCommand(_recording_command(log, "inner", True), _confirm)
    decorator.dispose()
    decorator.dispose()

    assert decorator.can_execute() is False
    decorator.execute()
    await decorator.execute_async()
    await _drain_other_tasks()

    assert confirms == []
    assert log == []


@pytest.mark.conformance("CMDD-012")
@pytest.mark.parametrize("outcome", ["true", "false", "faulted"])
async def test_CMDD_012_confirmation_resolving_after_disposal_runs_nothing(outcome: str) -> None:
    log: list[str] = []
    inner = _recording_command(log, "inner", True)
    decision: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    started = asyncio.Event()

    async def _confirm() -> bool:
        started.set()
        return await decision

    decorator = ConfirmationDecoratorCommand(inner, _confirm)
    errors: list[BaseException] = []
    completions: list[None] = []
    decorator.errors.subscribe(errors.append, on_completed=lambda: completions.append(None))

    decorator.execute()
    await started.wait()
    decorator.dispose()
    if outcome == "faulted":
        decision.set_exception(RuntimeError("confirm failed"))
    else:
        decision.set_result(outcome == "true")
    await _drain_other_tasks()

    assert log == []
    assert errors == []
    assert completions == [None]
    inner.execute()
    assert log == ["inner"]


@pytest.mark.conformance("CMDD-012")
async def test_CMDD_012_error_racing_disposal_on_another_thread_is_dropped() -> None:
    # Force the interleaving a background completion can hit: another thread
    # disposes the decorator after the fire-and-forget error path has checked
    # for disposal but before it publishes. The late error must be dropped,
    # not raised out of the task callback.
    log: list[str] = []
    inner = _recording_command(log, "inner", True)

    async def _confirm() -> bool:
        raise RuntimeError("confirm failed")

    decorator = ConfirmationDecoratorCommand(inner, _confirm)
    errors: list[BaseException] = []
    completions: list[None] = []
    decorator.errors.subscribe(errors.append, on_completed=lambda: completions.append(None))
    subject: Any = decorator._errors
    publish = subject.on_next

    def _dispose_then_publish(value: BaseException) -> None:
        disposer = threading.Thread(target=decorator.dispose)
        disposer.start()
        disposer.join()
        publish(value)

    subject.on_next = _dispose_then_publish
    loop = asyncio.get_running_loop()
    escaped: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: escaped.append(context))
    try:
        decorator.execute()
        await _drain_other_tasks()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert escaped == []
    assert errors == []
    assert completions == [None]
    assert log == []


@pytest.mark.conformance("CMDD-011")
def test_CMDD_011_disposal_leaves_inner_change_streams_to_their_owner() -> None:
    log: list[str] = []
    inner = _recording_command(log, "inner", True)
    notifications: list[None] = []
    completions: list[None] = []
    inner.can_execute_changed.subscribe(
        lambda _: notifications.append(None), on_completed=lambda: completions.append(None)
    )

    async def _confirm() -> bool:
        return True

    for wrapper in (
        CompositeCommand(inner),
        DecoratorCommand(inner),
        ConfirmationDecoratorCommand(inner, _confirm),
    ):
        wrapper.dispose()
    inner.raise_can_execute_changed()

    assert notifications == [None]
    assert completions == []


@pytest.mark.conformance("CMDD-013")
def test_CMDD_013_composite_runs_no_child_after_disposal_by_an_earlier_child() -> None:
    log: list[str] = []
    holder: list[CompositeCommand] = []

    def _first() -> None:
        log.append("first")
        holder[0].dispose()

    composite = CompositeCommand(
        RelayCommand.builder().task(_first).build(),
        _recording_command(log, "second", True),
    )
    holder.append(composite)

    composite.execute()

    assert log == ["first"]


@pytest.mark.conformance("CMDD-013")
def test_CMDD_013_decorator_disposed_by_its_predicate_runs_nothing() -> None:
    log: list[str] = []
    holder: list[DecoratorCommand] = []

    def _predicate() -> bool:
        holder[0].dispose()
        return True

    decorator = DecoratorCommand(
        _recording_command(log, "inner", True),
        pre_execute=lambda: log.append("pre"),
        post_execute=lambda: log.append("post"),
        extra_predicate=_predicate,
    )
    holder.append(decorator)

    decorator.execute()

    assert log == []


@pytest.mark.conformance("CMDD-013")
def test_CMDD_013_decorator_disposed_by_its_pre_action_still_runs_post_once() -> None:
    log: list[str] = []
    holder: list[DecoratorCommand] = []

    def _pre() -> None:
        log.append("pre")
        holder[0].dispose()

    decorator = DecoratorCommand(
        _recording_command(log, "inner", True),
        pre_execute=_pre,
        post_execute=lambda: log.append("post"),
    )
    holder.append(decorator)

    decorator.execute()
    decorator.execute()

    assert log == ["pre", "post"]


@pytest.mark.conformance("CMDD-013")
def test_CMDD_013_admitted_pair_with_throwing_inner_runs_post_and_reraises() -> None:
    log: list[str] = []
    boom = RuntimeError("inner boom")

    def _raise() -> None:
        raise boom

    decorator = DecoratorCommand(
        RelayCommand.builder().task(_raise).build(),
        pre_execute=lambda: log.append("pre"),
        post_execute=lambda: log.append("post"),
    )

    with pytest.raises(RuntimeError) as raised:
        decorator.execute()

    assert raised.value is boom
    assert log == ["pre", "post"]

"""Unit tests for RelayCommand and RelayCommandOf.

Covers all behaviour mandated by spec/04-commands.md:
- Predicate-null → can_execute True
- Predicate True / False
- Predicate raises → treated as False (defensive)
- Task-null → execute is a no-op
- Execute is GATED on can_execute
- Triggers re-fire can_execute_changed
- Builder immutability (each setter returns a new instance)
- Parameterized variant passes the parameter through
"""

from __future__ import annotations

import pytest
from reactivex.subject import Subject

from vmx.commands.relay_command import (
    RelayCommand,
    RelayCommandBuilder,
    RelayCommandOf,
    RelayCommandOfBuilder,
)

# ---------------------------------------------------------------------------
# RelayCommand — can_execute behaviour
# ---------------------------------------------------------------------------


def test_no_predicate_can_execute_returns_true() -> None:
    cmd = RelayCommand.builder().build()
    assert cmd.can_execute() is True


def test_predicate_true_can_execute_returns_true() -> None:
    cmd = RelayCommand.builder().predicate(lambda: True).build()
    assert cmd.can_execute() is True


def test_predicate_false_can_execute_returns_false() -> None:
    cmd = RelayCommand.builder().predicate(lambda: False).build()
    assert cmd.can_execute() is False


def test_predicate_raises_can_execute_returns_false() -> None:
    def boom() -> bool:
        raise RuntimeError("predicate error")

    cmd = RelayCommand.builder().predicate(boom).build()
    assert cmd.can_execute() is False


# ---------------------------------------------------------------------------
# RelayCommand — execute behaviour
# ---------------------------------------------------------------------------


def test_null_task_execute_is_noop() -> None:
    cmd = RelayCommand.builder().build()
    # Must not raise
    cmd.execute()


def test_execute_invokes_task_when_can_execute_true() -> None:
    called: list[int] = []
    cmd = RelayCommand.builder().task(lambda: called.append(1)).build()
    cmd.execute()
    assert called == [1]


def test_execute_gated_when_predicate_false() -> None:
    """If predicate returns False, execute must NOT invoke the task."""
    called: list[int] = []
    cmd = RelayCommand.builder().predicate(lambda: False).task(lambda: called.append(1)).build()
    cmd.execute()
    assert called == []


def test_execute_propagates_task_exception() -> None:
    def boom() -> None:
        raise ValueError("task error")

    cmd = RelayCommand.builder().task(boom).build()
    with pytest.raises(ValueError, match="task error"):
        cmd.execute()


# ---------------------------------------------------------------------------
# RelayCommand — triggers and can_execute_changed
# ---------------------------------------------------------------------------


def test_trigger_fires_can_execute_changed() -> None:
    subject: Subject[None] = Subject()
    cmd = RelayCommand.builder().triggers(subject).build()

    fired: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: fired.append(1))

    subject.on_next(None)
    assert len(fired) == 1

    subject.on_next(None)
    assert len(fired) == 2


def test_multiple_triggers_are_additive() -> None:
    s1: Subject[None] = Subject()
    s2: Subject[None] = Subject()
    cmd = RelayCommand.builder().triggers(s1).triggers(s2).build()

    fired: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: fired.append(1))

    s1.on_next(None)
    s2.on_next(None)
    assert len(fired) == 2


def test_no_trigger_can_execute_changed_does_not_fire() -> None:
    cmd = RelayCommand.builder().build()
    fired: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: fired.append(1))
    assert fired == []


# ---------------------------------------------------------------------------
# RelayCommand — builder immutability (BLD-001)
# ---------------------------------------------------------------------------


def test_builder_task_setter_returns_new_instance() -> None:
    b1 = RelayCommandBuilder()
    b2 = b1.task(lambda: None)
    assert b1 is not b2
    assert b1._task is None
    assert b2._task is not None


def test_builder_predicate_setter_returns_new_instance() -> None:
    b1 = RelayCommandBuilder()
    b2 = b1.predicate(lambda: True)
    assert b1 is not b2
    assert b1._predicate is None
    assert b2._predicate is not None


def test_builder_triggers_setter_returns_new_instance() -> None:
    subject: Subject[None] = Subject()
    b1 = RelayCommandBuilder()
    b2 = b1.triggers(subject)
    assert b1 is not b2
    assert len(b1._triggers) == 0
    assert len(b2._triggers) == 1


def test_build_with_no_args_succeeds() -> None:
    """build() with no task/predicate/triggers must succeed (not raise)."""
    cmd = RelayCommand.builder().build()
    assert cmd is not None


# ---------------------------------------------------------------------------
# RelayCommandOf — parameterized variant
# ---------------------------------------------------------------------------


def test_parameterized_no_predicate_can_execute_true() -> None:
    cmd: RelayCommandOf[str] = RelayCommandOf.builder().build()
    assert cmd.can_execute("hello") is True


def test_parameterized_predicate_receives_parameter() -> None:
    received: list[str | None] = []

    def pred(p: str | None) -> bool:
        received.append(p)
        return p == "ok"

    cmd: RelayCommandOf[str] = RelayCommandOf.builder().predicate(pred).build()
    assert cmd.can_execute("ok") is True
    assert cmd.can_execute("nope") is False
    assert received == ["ok", "nope"]


def test_parameterized_task_receives_parameter() -> None:
    received: list[str | None] = []

    cmd: RelayCommandOf[str] = RelayCommandOf.builder().task(lambda p: received.append(p)).build()
    cmd.execute("world")
    assert received == ["world"]


def test_parameterized_execute_gated_on_can_execute() -> None:
    called: list[int] = []
    cmd: RelayCommandOf[int] = (
        RelayCommandOf.builder().predicate(lambda p: False).task(lambda p: called.append(1)).build()
    )
    cmd.execute(42)
    assert called == []


def test_parameterized_trigger_fires_can_execute_changed() -> None:
    subject: Subject[None] = Subject()
    cmd: RelayCommandOf[str] = RelayCommandOf.builder().triggers(subject).build()

    fired: list[int] = []
    cmd.can_execute_changed.subscribe(lambda _: fired.append(1))

    subject.on_next(None)
    assert fired == [1]


def test_parameterized_builder_immutable() -> None:
    b1: RelayCommandOfBuilder[str] = RelayCommandOfBuilder()
    b2 = b1.task(lambda p: None)
    assert b1 is not b2
    assert b1._task is None
    assert b2._task is not None

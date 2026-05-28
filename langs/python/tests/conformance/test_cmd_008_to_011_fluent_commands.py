"""Conformance tests: CMD-008..CMD-011 — fluent command extension methods.

Per spec/04-commands.md §9 and ADR-0027.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import reactivex as rx

from vmx.commands import (
    CompositeCommand,
    ConfirmationDecoratorCommand,
    DecoratorCommand,
)
from vmx.commands.fluent import confirm, precede_with, succeed_with, wrap_with

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Recording:
    """Minimal Command that records calls and obeys a fixed predicate."""

    def __init__(self, log: list[str], label: str, *, enabled: bool = True) -> None:
        self._log = log
        self._label = label
        self._enabled = enabled
        self.can_execute_changed = rx.never()

    def can_execute(self, parameter: Any = None) -> bool:
        return self._enabled

    def execute(self, parameter: Any = None) -> None:
        self._log.append(self._label)


# ---------------------------------------------------------------------------
# CMD-008 — confirm(command, delegate) equivalent to ConfirmationDecoratorCommand
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-008")
def test_cmd_008_confirm_equivalent_to_explicit_constructor() -> None:
    """confirm() returns a ConfirmationDecoratorCommand with the supplied delegate."""
    log: list[str] = []
    inner = _Recording(log, "inner", enabled=True)

    async def confirm_yes() -> bool:
        return True

    async def confirm_no() -> bool:
        return False

    # fluent form — accepted
    result = confirm(inner, confirm_yes)
    assert isinstance(result, ConfirmationDecoratorCommand)
    assert result.can_execute() is True
    asyncio.run(result.execute_async())
    assert log == ["inner"]

    # fluent form — rejected
    log.clear()
    result_no = confirm(inner, confirm_no)
    asyncio.run(result_no.execute_async())
    assert log == []

    # equivalent CanExecute to explicit constructor
    explicit = ConfirmationDecoratorCommand(inner, confirm_yes)
    assert result.can_execute() == explicit.can_execute()


# ---------------------------------------------------------------------------
# CMD-009 — precede_with(receiver, other) equivalent to CompositeCommand(other, receiver)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-009")
def test_cmd_009_precede_with_equivalent_to_explicit_constructor() -> None:
    """precede_with() returns CompositeCommand(other, receiver): other runs first."""
    log: list[str] = []
    receiver = _Recording(log, "receiver", enabled=True)
    other = _Recording(log, "other", enabled=True)

    result = precede_with(receiver, other)
    assert isinstance(result, CompositeCommand)

    result.execute()
    assert log == ["other", "receiver"]


# ---------------------------------------------------------------------------
# CMD-010 — succeed_with(receiver, other) equivalent to CompositeCommand(receiver, other)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-010")
def test_cmd_010_succeed_with_equivalent_to_explicit_constructor() -> None:
    """succeed_with() returns CompositeCommand(receiver, other): receiver runs first."""
    log: list[str] = []
    receiver = _Recording(log, "receiver", enabled=True)
    other = _Recording(log, "other", enabled=True)

    result = succeed_with(receiver, other)
    assert isinstance(result, CompositeCommand)

    result.execute()
    assert log == ["receiver", "other"]


# ---------------------------------------------------------------------------
# CMD-011 — wrap_with(command, predicate?, pre?, post?) equivalent to DecoratorCommand
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-011")
def test_cmd_011_wrap_with_equivalent_to_explicit_constructor() -> None:
    """wrap_with() returns a DecoratorCommand with optional predicate/pre/post."""
    log: list[str] = []
    inner = _Recording(log, "inner", enabled=True)

    # all-None → transparent decorator
    all_none = wrap_with(inner)
    assert isinstance(all_none, DecoratorCommand)
    assert all_none.can_execute() is True
    all_none.execute()
    assert log == ["inner"]

    # with pre/post/predicate
    log.clear()
    decorated = wrap_with(
        inner,
        predicate=lambda: True,
        pre=lambda: log.append("pre"),
        post=lambda: log.append("post"),
    )
    assert isinstance(decorated, DecoratorCommand)
    decorated.execute()
    assert log == ["pre", "inner", "post"]

    # predicate returning False blocks execution
    log.clear()
    blocked = wrap_with(inner, predicate=lambda: False)
    assert blocked.can_execute() is False
    blocked.execute()
    assert log == []

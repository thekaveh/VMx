"""Conformance stubs: CMD-008..CMD-011 — fluent command extension methods.

Per spec/04-commands.md §9 and ADR-0027.
Implementation deferred to Substage 1D execution phase.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# CMD-008 — confirm(delegate) equivalent to explicit ConfirmationDecoratorCommand
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-008")
def test_cmd_008_confirm_equivalent_to_explicit_constructor() -> None:
    """CMD-008 stub — pending Substage 1D implementation."""
    pytest.skip("CMD-008: fluent command extensions not yet implemented.")


# ---------------------------------------------------------------------------
# CMD-009 — precede_with(other) equivalent to CompositeCommand(other, receiver)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-009")
def test_cmd_009_precede_with_equivalent_to_explicit_constructor() -> None:
    """CMD-009 stub — pending Substage 1D implementation."""
    pytest.skip("CMD-009: fluent command extensions not yet implemented.")


# ---------------------------------------------------------------------------
# CMD-010 — succeed_with(other) equivalent to CompositeCommand(receiver, other)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-010")
def test_cmd_010_succeed_with_equivalent_to_explicit_constructor() -> None:
    """CMD-010 stub — pending Substage 1D implementation."""
    pytest.skip("CMD-010: fluent command extensions not yet implemented.")


# ---------------------------------------------------------------------------
# CMD-011 — wrap_with(predicate?, pre?, post?) equivalent to explicit DecoratorCommand
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CMD-011")
def test_cmd_011_wrap_with_equivalent_to_explicit_constructor() -> None:
    """CMD-011 stub — pending Substage 1D implementation."""
    pytest.skip("CMD-011: fluent command extensions not yet implemented.")

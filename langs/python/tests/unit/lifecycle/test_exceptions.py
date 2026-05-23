"""Unit tests for StatusTransitionError."""

from __future__ import annotations

import pytest

from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus


def test_exception_carries_state_and_operation() -> None:
    err = StatusTransitionError(ConstructionStatus.DISPOSED, "construct")
    assert err.current_status is ConstructionStatus.DISPOSED
    assert err.attempted_operation == "construct"
    assert "Disposed" in str(err)
    assert "construct" in str(err)


def test_exception_is_runtime_error() -> None:
    err = StatusTransitionError(ConstructionStatus.CONSTRUCTING, "destruct")
    assert isinstance(err, RuntimeError)


def test_message_contains_state_name() -> None:
    err = StatusTransitionError(ConstructionStatus.CONSTRUCTING, "destruct")
    assert "Constructing" in str(err)
    assert "destruct" in str(err)


def test_exception_is_raised_correctly() -> None:
    with pytest.raises(StatusTransitionError) as exc_info:
        raise StatusTransitionError(ConstructionStatus.DISPOSED, "reconstruct")
    assert exc_info.value.current_status is ConstructionStatus.DISPOSED
    assert exc_info.value.attempted_operation == "reconstruct"

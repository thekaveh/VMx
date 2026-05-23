"""Unit tests for the lifecycle transition validator."""

from __future__ import annotations

import pytest

from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.transition_validator import final_state, is_legal, require


@pytest.mark.parametrize(
    "frm,op,expected",
    [
        (ConstructionStatus.DESTRUCTED, "construct", True),
        (ConstructionStatus.CONSTRUCTED, "destruct", True),
        (ConstructionStatus.CONSTRUCTED, "reconstruct", True),
        (ConstructionStatus.DISPOSED, "construct", False),
        (ConstructionStatus.DISPOSED, "destruct", False),
        (ConstructionStatus.CONSTRUCTING, "construct", False),
        (ConstructionStatus.DESTRUCTING, "destruct", False),
        # idempotent operations are legal
        (ConstructionStatus.CONSTRUCTED, "construct", True),
        (ConstructionStatus.DESTRUCTED, "destruct", True),
        # dispose is legal from every state
        (ConstructionStatus.CONSTRUCTED, "dispose", True),
        (ConstructionStatus.DESTRUCTED, "dispose", True),
        (ConstructionStatus.DISPOSED, "dispose", True),
        (ConstructionStatus.CONSTRUCTING, "dispose", True),
        (ConstructionStatus.DESTRUCTING, "dispose", True),
    ],
)
def test_is_legal_matches_fixture(frm: ConstructionStatus, op: str, expected: bool) -> None:
    assert is_legal(frm, op) == expected


def test_require_raises_with_state_and_op() -> None:
    with pytest.raises(StatusTransitionError) as exc_info:
        require(ConstructionStatus.DISPOSED, "construct")
    assert exc_info.value.current_status is ConstructionStatus.DISPOSED
    assert exc_info.value.attempted_operation == "construct"


def test_require_does_not_raise_for_legal_op() -> None:
    # Should not raise
    require(ConstructionStatus.DESTRUCTED, "construct")


def test_final_state_returns_expected() -> None:
    assert final_state(ConstructionStatus.DESTRUCTED, "construct") is ConstructionStatus.CONSTRUCTED


def test_final_state_destruct() -> None:
    assert final_state(ConstructionStatus.CONSTRUCTED, "destruct") is ConstructionStatus.DESTRUCTED


def test_final_state_reconstruct() -> None:
    result = final_state(ConstructionStatus.CONSTRUCTED, "reconstruct")
    assert result is ConstructionStatus.CONSTRUCTED


def test_final_state_dispose_from_constructed() -> None:
    assert final_state(ConstructionStatus.CONSTRUCTED, "dispose") is ConstructionStatus.DISPOSED


def test_final_state_raises_for_illegal_op() -> None:
    with pytest.raises(StatusTransitionError):
        final_state(ConstructionStatus.DISPOSED, "construct")

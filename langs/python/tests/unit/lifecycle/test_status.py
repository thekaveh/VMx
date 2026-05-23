"""Unit tests for ConstructionStatus."""

from __future__ import annotations

from vmx.lifecycle.status import ConstructionStatus


def test_construction_status_has_five_values() -> None:
    assert len(list(ConstructionStatus)) == 5


def test_disposed_is_zero() -> None:
    assert ConstructionStatus.DISPOSED.value == 0


def test_destructing_is_one() -> None:
    assert ConstructionStatus.DESTRUCTING.value == 1


def test_destructed_is_two() -> None:
    assert ConstructionStatus.DESTRUCTED.value == 2


def test_constructing_is_three() -> None:
    assert ConstructionStatus.CONSTRUCTING.value == 3


def test_constructed_is_four() -> None:
    assert ConstructionStatus.CONSTRUCTED.value == 4


def test_is_int_enum() -> None:
    import enum

    assert issubclass(ConstructionStatus, int)
    assert issubclass(ConstructionStatus, enum.Enum)


def test_comparison_by_value() -> None:
    assert ConstructionStatus.DISPOSED < ConstructionStatus.CONSTRUCTED

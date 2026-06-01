"""Conformance tests: DPROP-001..012 — derived properties.

Per spec/15-derived-properties.md and ADR-0011.
"""

from __future__ import annotations

import operator
from functools import reduce
from typing import Any

import pytest
from reactivex.subject import BehaviorSubject

from tests.conformance.fixtures.loader import load
from vmx.properties import (
    DerivedProperty,
    from_five,
    from_four,
    from_many,
    from_one,
    from_sources,
    from_three,
    from_two,
)

TRANSFORMS: dict[str, Any] = {
    "sum": lambda *xs: reduce(operator.add, xs, 0),
    "concat": lambda *xs: "".join(str(x) for x in xs),
}


# ---------------------------------------------------------------------------
# DPROP-001 — Single-source derived value computes on construction
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-001")
def test_DPROP_001_single_source_initial_value() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(10)
    dp = from_sources(s1, transform=lambda x: x * 2)
    assert dp.value == 20
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-002 — Source change triggers recompute
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-002")
def test_DPROP_002_source_change_triggers_recompute() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(10)
    dp: DerivedProperty[int] = from_sources(s1, transform=lambda x: x * 2)
    s1.on_next(5)
    assert dp.value == 10
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-003 — Two-source derived value
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-003")
def test_DPROP_003_two_source_derived() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(3)
    s2: BehaviorSubject[int] = BehaviorSubject(4)
    dp: DerivedProperty[int] = from_sources(s1, s2, transform=lambda a, b: a + b)
    assert dp.value == 7
    s2.on_next(6)
    assert dp.value == 9
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-004 — Five-source derived value (spec minimum)
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-004")
def test_DPROP_004_five_source_derived() -> None:
    subjects = [BehaviorSubject(i + 1) for i in range(5)]
    dp: DerivedProperty[int] = from_sources(
        *subjects, transform=lambda *xs: reduce(operator.add, xs, 0)
    )
    assert dp.value == 15
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-005 — Mutation of any source recomputes
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-005")
def test_DPROP_005_mutation_of_any_source_recomputes() -> None:
    subjects = [BehaviorSubject(i + 1) for i in range(5)]
    dp: DerivedProperty[int] = from_sources(
        *subjects, transform=lambda *xs: reduce(operator.add, xs, 0)
    )
    subjects[2].on_next(30)
    assert dp.value == 1 + 2 + 30 + 4 + 5
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-006 — Default-built derived property is read-only
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-006")
def test_DPROP_006_default_is_read_only() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(1)
    dp: DerivedProperty[int] = from_sources(s1, transform=lambda x: x)
    for v in (0, 1, 42, -7):
        assert dp.can_set(v) is False
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-007 — Validator + write-back enables SetValue
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-007")
def test_DPROP_007_validator_plus_write_back() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(0)
    recorder: list[int] = []
    dp: DerivedProperty[int] = from_sources(
        s1,
        transform=lambda x: x,
        can_set=lambda v: v > 0,
        set_action=recorder.append,
    )
    dp.set_value(5)
    assert recorder == [5]
    with pytest.raises(ValueError):
        dp.set_value(-1)
    assert recorder == [5]
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-008 — Write-back action receives the value
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-008")
def test_DPROP_008_write_back_action_receives_value() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(0)
    recorder: list[int] = []
    dp: DerivedProperty[int] = from_sources(
        s1,
        transform=lambda x: x,
        can_set=lambda _v: True,
        set_action=recorder.append,
    )
    dp.set_value(7)
    assert recorder == [7]
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-009 — ValueChanged emits on recompute
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-009")
def test_DPROP_009_value_changed_emits_on_recompute() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(1)
    dp: DerivedProperty[int] = from_sources(s1, transform=lambda x: x)
    observed: list[int] = []
    dp.value_changed.subscribe(on_next=observed.append)
    s1.on_next(2)
    s1.on_next(3)
    assert observed == [2, 3]
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-010 — ValueChanged does not emit if transform output unchanged
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-010")
def test_DPROP_010_distinct_until_changed() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(5)
    s2: BehaviorSubject[int] = BehaviorSubject(5)
    dp: DerivedProperty[int] = from_sources(s1, s2, transform=lambda a, b: a + b)
    observed: list[int] = []
    dp.value_changed.subscribe(on_next=observed.append)
    s1.on_next(3)  # 3+5 = 8 (different from 10) → emit
    s2.on_next(7)  # 3+7 = 10 (different from 8) → emit
    assert observed == [8, 10]
    s1.on_next(3)  # 3+7 still = 10 → no emit
    assert observed == [8, 10]
    dp.dispose()


# ---------------------------------------------------------------------------
# DPROP-011 — Dispose ends subscriptions; ValueChanged completes
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-011")
def test_DPROP_011_dispose_completes_value_changed() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(1)
    dp: DerivedProperty[int] = from_sources(s1, transform=lambda x: x)
    observed: list[int] = []
    completed = False

    def _on_completed() -> None:
        nonlocal completed
        completed = True

    dp.value_changed.subscribe(on_next=observed.append, on_completed=_on_completed)
    s1.on_next(2)
    assert observed == [2]
    dp.dispose()
    assert completed is True
    s1.on_next(3)
    assert dp.value == 2  # not updated after dispose


# ---------------------------------------------------------------------------
# DPROP-012 — Fixture-driven scenarios
# ---------------------------------------------------------------------------


@pytest.mark.conformance("DPROP-012")
def test_DPROP_012_fixture_scenarios() -> None:
    fixture = load("derived-properties.json")
    for scenario in fixture["scenarios"]:
        transform = TRANSFORMS[scenario["transform"]]
        initial = scenario["sources_initial"]
        subjects = [BehaviorSubject(v) for v in initial]
        dp: DerivedProperty[Any] = from_sources(*subjects, transform=transform)
        actuals: list[Any] = [dp.value]
        for src_idx, new_val in scenario["mutations"]:
            subjects[src_idx].on_next(new_val)
            actuals.append(dp.value)
        assert actuals == scenario["expected_values"], (
            f"scenario {scenario['name']!r}: got {actuals}, expected {scenario['expected_values']}"
        )
        dp.dispose()


# ---------------------------------------------------------------------------
# Typed-arity factories (parity with C# / TS) — ADR-0035 §2 DP2
# ---------------------------------------------------------------------------


def test_from_one_typed_arity() -> None:
    """``from_one`` accepts a single ``Observable[T1]`` and a ``(T1) -> TValue``
    transform. Type checker can verify the transform argument is exactly ``T1``.
    """
    s1: BehaviorSubject[int] = BehaviorSubject(3)
    dp: DerivedProperty[int] = from_one(s1, lambda x: x * 10)
    assert dp.value == 30
    s1.on_next(4)
    assert dp.value == 40
    dp.dispose()


def test_from_two_typed_arity() -> None:
    """``from_two`` types the transform as ``(T1, T2) -> TValue``."""
    s1: BehaviorSubject[int] = BehaviorSubject(2)
    s2: BehaviorSubject[str] = BehaviorSubject("x")
    dp: DerivedProperty[str] = from_two(s1, s2, lambda i, s: s * i)
    assert dp.value == "xx"
    s1.on_next(3)
    assert dp.value == "xxx"
    s2.on_next("y")
    assert dp.value == "yyy"
    dp.dispose()


def test_from_three_typed_arity() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(1)
    s2: BehaviorSubject[int] = BehaviorSubject(2)
    s3: BehaviorSubject[int] = BehaviorSubject(3)
    dp: DerivedProperty[int] = from_three(s1, s2, s3, lambda a, b, c: a + b + c)
    assert dp.value == 6
    s2.on_next(20)
    assert dp.value == 24
    dp.dispose()


def test_from_four_typed_arity() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(1)
    s2: BehaviorSubject[int] = BehaviorSubject(2)
    s3: BehaviorSubject[int] = BehaviorSubject(3)
    s4: BehaviorSubject[int] = BehaviorSubject(4)
    dp: DerivedProperty[int] = from_four(s1, s2, s3, s4, lambda a, b, c, d: a + b + c + d)
    assert dp.value == 10
    s4.on_next(40)
    assert dp.value == 46
    dp.dispose()


def test_from_five_typed_arity() -> None:
    s1: BehaviorSubject[int] = BehaviorSubject(1)
    s2: BehaviorSubject[int] = BehaviorSubject(2)
    s3: BehaviorSubject[int] = BehaviorSubject(3)
    s4: BehaviorSubject[int] = BehaviorSubject(4)
    s5: BehaviorSubject[int] = BehaviorSubject(5)
    dp: DerivedProperty[int] = from_five(
        s1, s2, s3, s4, s5, lambda a, b, c, d, e: a * b * c * d * e
    )
    assert dp.value == 120  # 1*2*3*4*5
    s1.on_next(2)
    assert dp.value == 240
    dp.dispose()


def test_from_many_alias_matches_from_sources() -> None:
    """``from_many`` is an alias for ``from_sources`` (parity with C# ``FromMany`` /
    TS ``fromMany``).
    """
    assert from_many is from_sources

    s1: BehaviorSubject[int] = BehaviorSubject(1)
    s2: BehaviorSubject[int] = BehaviorSubject(2)
    dp: DerivedProperty[int] = from_many(s1, s2, transform=lambda a, b: a + b)
    assert dp.value == 3
    dp.dispose()


def test_typed_arity_factories_support_can_set_and_set_action() -> None:
    """Typed-arity factories accept the same ``can_set`` / ``set_action`` kwargs
    as ``from_sources``."""
    s1: BehaviorSubject[int] = BehaviorSubject(5)
    written: list[int] = []
    dp: DerivedProperty[int] = from_one(
        s1,
        lambda x: x * 2,
        can_set=lambda v: v > 0,
        set_action=written.append,
    )
    assert dp.value == 10
    assert dp.can_set(42) is True
    dp.set_value(42)
    assert written == [42]
    dp.dispose()

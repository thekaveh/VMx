"""Unit tests: DerivedProperty dispose-path regression guards.

These tests verify idempotence and post-dispose source-mutation safety.
They are not normative conformance IDs — DPROP-011 covers the happy-path
dispose; these add edge-case regression coverage.
"""

from __future__ import annotations

from reactivex.subject import BehaviorSubject

from vmx.properties import DerivedProperty, from_sources


def test_derived_property_dispose_is_idempotent() -> None:
    s1 = BehaviorSubject(1)
    dp: DerivedProperty[int] = from_sources(s1, transform=lambda x: x * 2)
    dp.dispose()
    dp.dispose()  # second call must not raise


def test_derived_property_post_dispose_source_mutation_no_emit() -> None:
    s1 = BehaviorSubject(1)
    dp: DerivedProperty[int] = from_sources(s1, transform=lambda x: x * 2)
    emissions: list[int] = []
    dp.value_changed.subscribe(emissions.append)
    s1.on_next(2)
    assert emissions == [4]
    dp.dispose()
    s1.on_next(3)  # post-dispose: subscription torn down, no emit
    assert emissions == [4]

"""Unit tests: ExpandableState dispose-path regression guards.

These tests verify idempotence and observable-completion behavior on dispose.
They are not normative conformance IDs — EXP-005 and the main expansion tests
cover the happy-paths; these add regression coverage for dispose internals.
"""

from __future__ import annotations

from vmx.capabilities import ExpandableState


def test_expandable_state_dispose_is_idempotent() -> None:
    state = ExpandableState(initially_expanded=True)
    state.dispose()
    state.dispose()  # second call must not raise


def test_expandable_state_dispose_completes_change_observable() -> None:
    state = ExpandableState(initially_expanded=False)
    completed = False

    def on_completed() -> None:
        nonlocal completed
        completed = True

    state.is_expanded_changed.subscribe(on_completed=on_completed)
    state.dispose()
    assert completed is True

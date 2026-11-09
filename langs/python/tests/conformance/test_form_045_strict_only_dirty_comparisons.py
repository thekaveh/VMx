"""FORM-045 — an update runs the dirty comparisons only in strict mode.

Per spec/20-form-vm.md §5.2 (*Dirty comparisons*) and ADR-0216. A strict
``set_model`` runs three equality comparisons: the candidate with the live
model, the live model with the snapshot, and the candidate with the snapshot.
A strict deny runs the last two. A non-strict ``set_model`` runs only the
first, and a non-strict deny runs none. A non-strict update commits even when
the comparison of the candidate with the snapshot would fail.
"""

from __future__ import annotations

import pytest

from vmx.forms import FormVM


class _Counted:
    """A model whose ``__eq__`` counts its calls. ``!=`` falls back to ``__eq__``.

    When ``fail_against`` is set, a comparison with that object raises.
    """

    calls = 0
    fail_against: object | None = None

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        _Counted.calls += 1
        failing = _Counted.fail_against
        if failing is not None and (self is failing or other is failing):
            raise AssertionError("compared with the snapshot")
        return isinstance(other, _Counted) and other.value == self.value

    __hash__ = None  # type: ignore[assignment]


def _copy(model: _Counted) -> _Counted:
    """A snapshotter that returns a distinct object."""
    return _Counted(model.value)


async def _noop(_: object) -> None:
    return None


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    _Counted.calls = 0
    _Counted.fail_against = None


def _comparisons(action: object) -> int:
    assert callable(action)
    _Counted.calls = 0
    action()
    return _Counted.calls


@pytest.mark.conformance("FORM-045")
@pytest.mark.parametrize(("strict", "set_calls", "deny_calls"), [(True, 3, 2), (False, 1, 0)])
def test_form_045_update_comparison_counts(strict: bool, set_calls: int, deny_calls: int) -> None:
    form = FormVM(_Counted("initial"), _noop, strict=strict, snapshotter=_copy)

    assert _comparisons(lambda: form.set_model(_Counted("edited"))) == set_calls
    assert _comparisons(form.deny_command.execute) == deny_calls
    assert form.model.value == "initial"


@pytest.mark.conformance("FORM-045")
def test_form_045_non_strict_update_commits_when_the_snapshot_comparison_would_fail() -> None:
    form = FormVM(_Counted("initial"), _noop, snapshotter=_copy)
    _Counted.fail_against = form.snapshot

    form.set_model(_Counted("edited"))
    form.deny_command.execute()
    form.set_model(_Counted("again"))

    assert form.model.value == "again"

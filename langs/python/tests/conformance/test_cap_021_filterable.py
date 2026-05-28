"""Conformance stub: CAP-021 — IFilterable[TItem] capability contract.

IFilterable[TItem] does not exist yet; this stub satisfies the conformance
coverage requirement. Replace with a real test once IFilterable[TItem] lands
in vmx.capabilities (Task 1A.5-1A.7).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# CAP-021 — IFilterable[TItem] capability contract surface and opt-in behavior
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-021")
@pytest.mark.skip(reason="IFilterable[TItem] not yet implemented — see Task 1A.5")
def test_CAP_021_ifilterable_contract() -> None:
    """CAP-021: IFilterable[TItem] stub -- to be filled in during Task 1A.5-1A.7.

    Verifies:
    - F exposes a settable filter predicate and a can_filter() decision.
    - Setting filter to None clears the filter (no predicate applied).
    - A VM that does NOT opt in reports False for IFilterable[TItem].
    """
    raise NotImplementedError("CAP-021: IFilterable[TItem] not yet implemented")

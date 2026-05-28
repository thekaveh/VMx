"""Conformance tests: CAP-022 — IPageable capability contract.

Per spec/14-capabilities.md §2.10 and ADR-0023, IPageable exposes mutable
PageSize and CurrentPageIndex, derived PageCount and IsPagingEnabled, and
four navigation methods that are no-ops at their respective bounds.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# CAP-022 — IPageable capability contract surface and clamping/navigation
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-022")
def test_CAP_022_ipageable_contract() -> None:
    """CAP-022: IPageable capability contract surface and clamping/navigation behavior.

    Not yet implemented — stub only.
    """
    pytest.skip("CAP-022 not yet implemented")
    raise NotImplementedError("CAP-022 not yet implemented")

"""Conformance tests: CAP-021 — ``Filterable[TItem]`` capability contract.

Per spec/14-capabilities.md §Filterable and ADR-0022, ``Filterable[T]``
(spec-canonical name ``IFilterable<T>``; Python omits the I-prefix per
ADR-0009) exposes a settable filter predicate and a can_filter() decision
method.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vmx.capabilities import Filterable

# ---------------------------------------------------------------------------
# CAP-021 — Filterable[TItem] capability contract surface and opt-in behavior
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-021")
def test_CAP_021_filterable_contract() -> None:
    """CAP-021: ``Filterable[TItem]`` contract surface.

    Verifies:
    - F exposes a settable filter predicate and a can_filter() decision.
    - Setting filter to None clears the filter (no predicate applied).
    """

    class F(Filterable[int]):
        def __init__(self) -> None:
            self._filter: Callable[[int], bool] | None = None

        @property
        def filter(self) -> Callable[[int], bool] | None:
            return self._filter

        @filter.setter
        def filter(self, value: Callable[[int], bool] | None) -> None:
            self._filter = value

        def can_filter(self) -> bool:
            return True

    sut = F()
    assert sut.filter is None
    assert sut.can_filter() is True

    def p(x: int) -> bool:
        return x > 0

    sut.filter = p
    assert sut.filter is p

    sut.filter = None
    assert sut.filter is None

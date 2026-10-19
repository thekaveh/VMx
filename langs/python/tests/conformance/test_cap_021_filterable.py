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
from vmx.components.component_vm import ComponentVM
from vmx.composites.builders import CompositeVMBuilder
from vmx.composites.composite_vm import CompositeVM
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub

# ---------------------------------------------------------------------------
# CAP-021 — Filterable[TItem] capability contract surface and opt-in behavior
# ---------------------------------------------------------------------------


@pytest.mark.conformance("CAP-021")
def test_CAP_021_filterable_contract() -> None:
    """CAP-021: ``Filterable[TItem]`` contract surface.

    Verifies:
    - F exposes a settable filter predicate and a can_filter() decision.
    - Setting filter to None clears the filter (no predicate applied).
    - A minimal CompositeVM wrapper opts in by declaring the capability; a VM
      that does NOT opt in reports False for Filterable.
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

    # Filterable is ``(ABC, Generic[T])`` while CompositeVM's MRO places
    # Generic before ABC, so a direct mixin has no consistent MRO; the wrapper
    # therefore declares the capability through ABC virtual registration.
    class FilterableComposite(CompositeVM[ComponentVM]):
        _vm_filter: Callable[[ComponentVM], bool] | None = None

        @property
        def filter(self) -> Callable[[ComponentVM], bool] | None:
            return self._vm_filter

        @filter.setter
        def filter(self, value: Callable[[ComponentVM], bool] | None) -> None:
            self._vm_filter = value

        def can_filter(self) -> bool:
            return True

    Filterable.register(FilterableComposite)

    hub: MessageHub[object] = MessageHub()
    dispatcher = RxDispatcher.immediate()
    opted_in = FilterableComposite(name="opted-in", hint="", hub=hub, dispatcher=dispatcher)
    assert isinstance(opted_in, Filterable)
    assert opted_in.can_filter() is True
    opted_in.filter = lambda _vm: True
    assert opted_in.filter is not None
    opted_in.filter = None
    assert opted_in.filter is None

    plain: CompositeVM[ComponentVM] = (
        CompositeVMBuilder().name("plain").services(hub, dispatcher).children(lambda: ()).build()
    )
    assert isinstance(plain, Filterable) is False

"""ScoredFilteredCompositeVM — score-ranked visible projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from vmx.components.base import _ComponentVMBase
from vmx.composites.composite_vm import CompositeVM
from vmx.composites.filtered_composite_vm import FilteredCompositeVM, FilteredCursorPolicy

VM = TypeVar("VM", bound=_ComponentVMBase)


class ScoredFilteredCompositeVM(FilteredCompositeVM[VM]):
    """Filters out ``None`` scores and orders remaining items by descending score."""

    def __init__(
        self,
        source: CompositeVM[VM],
        *,
        scorer: Callable[[VM], float | int | None],
        cursor_policy: FilteredCursorPolicy = FilteredCursorPolicy.SNAP_TO_FIRST,
    ) -> None:
        self._scorer = scorer
        super().__init__(
            source,
            predicate=lambda vm: scorer(vm) is not None,
            cursor_policy=cursor_policy,
        )

    def _ordered_visible(self) -> list[VM]:
        scored: list[tuple[int, float | int, VM]] = []
        for index, item in enumerate(self._source):
            score = self._scorer(item)
            if score is not None:
                scored.append((index, score, item))
        scored.sort(key=lambda entry: (-entry[1], entry[0]))
        return [item for _, _, item in scored]

    def refresh_scores(self) -> None:
        self._recompute()

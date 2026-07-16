"""FilteredCompositeVM — visible projection over a CompositeVM source."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Generic, TypeVar

import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.components.base import _ComponentVMBase
from vmx.composites.composite_vm import CompositeVM

VM = TypeVar("VM", bound=_ComponentVMBase)


class FilteredCursorPolicy(str, Enum):
    SNAP_TO_FIRST = "snap_to_first"
    CLEAR = "clear"
    PRESERVE_IF_VISIBLE = "preserve_if_visible"


class FilteredCompositeVM(Generic[VM]):
    """Maintains a filtered visible projection over a source composite."""

    def __init__(
        self,
        source: CompositeVM[VM],
        *,
        predicate: Callable[[VM], bool] | None = None,
        cursor_policy: FilteredCursorPolicy = FilteredCursorPolicy.SNAP_TO_FIRST,
    ) -> None:
        self._source = source
        self._predicate = predicate or (lambda _: True)
        self._cursor_policy = cursor_policy
        self._visible: list[VM] = []
        self._current: VM | None = None
        self._changed: Subject[None] = Subject()
        self._disposed = False
        self._subscription = source.on_collection_changed.subscribe(lambda _: self._recompute())
        self._recompute()

    @property
    def visible(self) -> tuple[VM, ...]:
        return tuple(self._visible)

    @property
    def visible_count(self) -> int:
        return len(self._visible)

    @property
    def current(self) -> VM | None:
        return self._current

    @current.setter
    def current(self, value: VM | None) -> None:
        self.set_current(value)

    @property
    def on_changed(self) -> rx.Observable[None]:
        return self._changed.pipe(ops.as_observable())

    def set_predicate(self, predicate: Callable[[VM], bool]) -> None:
        self._predicate = predicate
        self._recompute()

    def set_current(self, item: VM | None) -> None:
        if self._disposed:
            return
        if item is not None and self._visible_index(item) < 0:
            raise ValueError("current must be None or a visible item")
        if self._current is item:
            return
        self._current = item
        self._changed.on_next(None)

    def move_to_next_visible(self) -> None:
        if not self._visible:
            self.set_current(None)
            return
        index = -1 if self._current is None else self._visible_index(self._current)
        if index < 0:
            self.set_current(self._visible[0])
            return
        self.set_current(self._visible[min(index + 1, len(self._visible) - 1)])

    def move_to_previous_visible(self) -> None:
        if not self._visible:
            self.set_current(None)
            return
        index = -1 if self._current is None else self._visible_index(self._current)
        if index < 0:
            self.set_current(self._visible[0])
            return
        self.set_current(self._visible[max(index - 1, 0)])

    def _ordered_visible(self) -> list[VM]:
        return [item for item in self._source if self._predicate(item)]

    def _recompute(self) -> None:
        if self._disposed:
            return
        self._visible = self._ordered_visible()
        if self._current is None or self._visible_index(self._current) < 0:
            if self._cursor_policy in (
                FilteredCursorPolicy.CLEAR,
                FilteredCursorPolicy.PRESERVE_IF_VISIBLE,
            ):
                self._current = None
            else:
                self._current = self._visible[0] if self._visible else None
        self._changed.on_next(None)

    def _visible_index(self, item: VM) -> int:
        return next(
            (index for index, candidate in enumerate(self._visible) if candidate is item),
            -1,
        )

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._subscription.dispose()
        self._changed.on_completed()
        self._changed.dispose()

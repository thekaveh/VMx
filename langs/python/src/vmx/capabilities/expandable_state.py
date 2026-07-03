"""ExpandableState — composition-friendly helper for expand/collapse.

See spec/05-component-vm.md §IExpandable integration and ADR-0015.
"""

from __future__ import annotations

from reactivex import Observable
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx.capabilities.expansion import (
    ICollapsible,
    IExpandable,
    IExpansionTogglable,
)


class ExpandableState(IExpandable, ICollapsible, IExpansionTogglable):
    """Bundle of IExpandable + ICollapsible + IExpansionTogglable with a
    change observable. Compose into VMs that want expand/collapse."""

    def __init__(self, initially_expanded: bool = False) -> None:
        self._is_expanded = initially_expanded
        self._changes: Subject[bool] = Subject()
        self._disposed = False

    @property
    def is_expanded(self) -> bool:
        return self._is_expanded

    @property
    def is_expanded_changed(self) -> Observable[bool]:
        return self._changes.pipe(ops.as_observable())

    def can_expand(self) -> bool:
        return not self._is_expanded

    def expand(self) -> None:
        if self._is_expanded:
            return
        self._is_expanded = True
        self._changes.on_next(True)

    def can_collapse(self) -> bool:
        return self._is_expanded

    def collapse(self) -> None:
        if not self._is_expanded:
            return
        self._is_expanded = False
        self._changes.on_next(False)

    def can_toggle_expansion(self) -> bool:
        return True

    def toggle_expansion(self) -> None:
        if self._is_expanded:
            self.collapse()
        else:
            self.expand()

    def dispose(self) -> None:
        """Complete and dispose the change observable. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        self._changes.on_completed()
        self._changes.dispose()

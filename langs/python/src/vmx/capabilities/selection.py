"""Selection capability contracts. See spec/14-capabilities.md §Selection."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ISelectable(ABC):
    @abstractmethod
    def can_select(self) -> bool: ...

    @abstractmethod
    def select(self) -> None: ...


class IDeselectable(ABC):
    @abstractmethod
    def can_deselect(self) -> bool: ...

    @abstractmethod
    def deselect(self) -> None: ...


class ISelectionTogglable(ABC):
    @abstractmethod
    def can_toggle_selection(self) -> bool: ...

    @abstractmethod
    def toggle_selection(self) -> None: ...

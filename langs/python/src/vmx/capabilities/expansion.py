"""Expansion capability contracts. See spec/14-capabilities.md §Expansion."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IExpandable(ABC):
    @property
    @abstractmethod
    def is_expanded(self) -> bool: ...

    @abstractmethod
    def can_expand(self) -> bool: ...

    @abstractmethod
    def expand(self) -> None: ...


class ICollapsible(ABC):
    @abstractmethod
    def can_collapse(self) -> bool: ...

    @abstractmethod
    def collapse(self) -> None: ...


class IExpansionTogglable(ABC):
    @abstractmethod
    def can_toggle_expansion(self) -> bool: ...

    @abstractmethod
    def toggle_expansion(self) -> None: ...

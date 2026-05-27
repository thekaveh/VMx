"""Search capability contract. See spec/14-capabilities.md §Search."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ISearchable(ABC):
    @property
    @abstractmethod
    def search_term(self) -> str: ...

    @search_term.setter
    @abstractmethod
    def search_term(self, value: str) -> None: ...

    @abstractmethod
    def can_search(self) -> bool: ...

    @abstractmethod
    def search(self) -> None: ...

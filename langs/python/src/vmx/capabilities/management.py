"""Management capability contract. See spec/14-capabilities.md §Management."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class IManagable(ABC, Generic[T]):
    @abstractmethod
    def can_manage(self, item: T) -> bool: ...

    @abstractmethod
    def manage(self, item: T) -> None: ...

"""Container-current capability contracts. See spec/14-capabilities.md §Container-current."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ICurrentDeletable(ABC):
    @abstractmethod
    def can_delete_current(self) -> bool: ...

    @abstractmethod
    def delete_current(self) -> None: ...


class ICurrentUpdatable(ABC):
    @abstractmethod
    def can_update_current(self) -> bool: ...

    @abstractmethod
    def update_current(self) -> None: ...

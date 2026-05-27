"""CRUD capability contracts. See spec/14-capabilities.md §CRUD."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class INewCreatable(ABC):
    @abstractmethod
    def can_create_new(self) -> bool: ...

    @abstractmethod
    def create_new(self) -> None: ...


class IDeletable(ABC, Generic[T]):
    @abstractmethod
    def can_delete(self, item: T) -> bool: ...

    @abstractmethod
    def delete(self, item: T) -> None: ...


class IUpdatable(ABC, Generic[T]):
    @abstractmethod
    def can_update(self, item: T) -> bool: ...

    @abstractmethod
    def update(self, item: T) -> None: ...


class ISavable(ABC, Generic[T]):
    @abstractmethod
    def can_save(self, item: T) -> bool: ...

    @abstractmethod
    def save(self, item: T) -> None: ...

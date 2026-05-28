"""Filter capability contract. See spec/14-capabilities.md §Filterable and ADR-0022."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Filterable(ABC, Generic[T]):
    """A collection/composition that supports filtering by an arbitrary predicate.

    ``filter`` is the predicate; ``None`` means no filter applied.
    ``can_filter()`` reports whether filtering is currently allowed.
    """

    @property
    @abstractmethod
    def filter(self) -> Callable[[T], bool] | None: ...

    @filter.setter
    @abstractmethod
    def filter(self, value: Callable[[T], bool] | None) -> None: ...

    @abstractmethod
    def can_filter(self) -> bool: ...

"""Lifecycle capability contracts. See spec/14-capabilities.md §Lifecycle.

These three are baseline: every core VM trivially satisfies them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IConstructable(ABC):
    @abstractmethod
    def can_construct(self) -> bool: ...

    @abstractmethod
    def construct(self) -> None: ...


class IDestructable(ABC):
    @abstractmethod
    def can_destruct(self) -> bool: ...

    @abstractmethod
    def destruct(self) -> None: ...


class IReconstructable(ABC):
    @abstractmethod
    def can_reconstruct(self) -> bool: ...

    @abstractmethod
    def reconstruct(self) -> None: ...

"""Dialog / form capability contracts. See spec/14-capabilities.md §Dialog / form."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IClosable(ABC):
    @abstractmethod
    def can_close(self) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...


class IApprovable(ABC):
    @abstractmethod
    def can_approve(self) -> bool: ...

    @abstractmethod
    def approve(self) -> None: ...


class ICancelable(ABC):
    @abstractmethod
    def can_cancel(self) -> bool: ...

    @abstractmethod
    def cancel(self) -> None: ...

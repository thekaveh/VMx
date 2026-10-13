"""Command and ParameterizedCommand Protocols for VMx.

Spec: spec/04-commands.md
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol, TypeVar, runtime_checkable

import reactivex as rx

T = TypeVar("T", contravariant=True)


@runtime_checkable
class Command(Protocol):
    """Non-parameterized command protocol.

    - ``can_execute()`` returns True when no predicate is set.
    - ``execute()`` is a no-op when no task is set or when ``can_execute()`` is False.
    - ``can_execute_changed`` fires on each trigger emission.
    """

    def can_execute(self, parameter: object = None) -> bool:
        """Return whether the command can currently execute."""
        ...

    def execute(self, parameter: object = None) -> None:
        """Execute the command (gated on ``can_execute``)."""
        ...

    @property
    def can_execute_changed(self) -> rx.Observable[None]:
        """Observable that emits whenever ``can_execute`` may have changed."""
        ...


@runtime_checkable
class ParameterizedCommand(Protocol[T]):
    """Parameterized command protocol (typed parameter).

    Same contract as ``Command`` but ``can_execute`` / ``execute`` receive a
    value of type ``T``.
    """

    def can_execute(self, parameter: T | None = None) -> bool:
        """Return whether the command can execute with the given parameter."""
        ...

    def execute(self, parameter: T | None = None) -> None:
        """Execute the command with the given parameter (gated on ``can_execute``)."""
        ...

    @property
    def can_execute_changed(self) -> rx.Observable[None]:
        """Observable that emits whenever ``can_execute`` may have changed."""
        ...


@runtime_checkable
class _AsyncCommand(Protocol):
    """Internal structural check for a command with an awaitable entry point.

    Python's form of the spec's async command capability (spec/04-commands.md
    §8.3.2, ADR-0145): a command is asynchronous when it offers an awaitable
    ``execute_async``. ``AsyncRelayCommand`` and ``ConfirmationDecoratorCommand``
    both satisfy it. Private: the ADR adds no public member outside Rust.
    """

    def execute_async(self, parameter: object = None) -> Awaitable[None]:
        """Run the command once and complete when that run completes."""
        ...

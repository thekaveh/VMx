"""Fluent command composition helpers for VMx.

Module-level functions that are ergonomic shortcuts over the explicit
decorator constructors. They add no new behaviour.

See spec/04-commands.md §10 and ADR-0027.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vmx.commands.composite_command import CompositeCommand
from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand
from vmx.commands.decorator_command import DecoratorCommand
from vmx.commands.protocols import Command


def confirm(
    command: Command,
    confirm_callback: Callable[[], Any],
) -> ConfirmationDecoratorCommand:
    """Return a :class:`ConfirmationDecoratorCommand` wrapping *command*.

    Equivalent to ``ConfirmationDecoratorCommand(command, confirm_callback)``.

    Args:
        command: The inner command to gate.
        confirm_callback: An async callable (``async def () -> bool``) that
            returns ``True`` when the user accepts.
    """
    return ConfirmationDecoratorCommand(command, confirm_callback)


def precede_with(command: Command, other: Command) -> CompositeCommand:
    """Return a :class:`CompositeCommand` where *other* executes before *command*.

    Equivalent to ``CompositeCommand(other, command)``.

    Args:
        command: The receiver (executes second).
        other: The command that executes first.
    """
    return CompositeCommand(other, command)


def succeed_with(command: Command, other: Command) -> CompositeCommand:
    """Return a :class:`CompositeCommand` where *other* executes after *command*.

    Equivalent to ``CompositeCommand(command, other)``.

    Args:
        command: The receiver (executes first).
        other: The command that executes second.
    """
    return CompositeCommand(command, other)


def wrap_with(
    command: Command,
    predicate: Callable[[], bool] | None = None,
    pre: Callable[[], None] | None = None,
    post: Callable[[], None] | None = None,
) -> DecoratorCommand:
    """Return a :class:`DecoratorCommand` wrapping *command*.

    Equivalent to
    ``DecoratorCommand(command, pre_execute=pre, post_execute=post,
    extra_predicate=predicate)``.

    All arguments are optional; passing none yields a semantically transparent
    decorator.

    Args:
        command: The inner command to wrap.
        predicate: Optional extra can-execute gate (no-arg, returns bool).
        pre: Optional action invoked before *command* executes.
        post: Optional action invoked after *command* executes (always, even
            on error).
    """
    return DecoratorCommand(
        command,
        pre_execute=pre,
        post_execute=post,
        extra_predicate=predicate,
    )

"""VMx Commands — RelayCommand, RelayCommandOf, and Protocol interfaces.

``RelayCommandOf`` is the canonical name from v1.2.0; ``RelayCommandOfT`` and
``RelayCommandOfTBuilder`` are kept as identity aliases for backward compatibility.
The originally planned v2.0.0 removal slipped and is deferred to vmx v3.0.0 per
ADR-0009.
"""

from vmx.commands.composite_command import CompositeCommand
from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand
from vmx.commands.decorator_command import DecoratorCommand
from vmx.commands.fluent import (
    confirm,
    confirm_with_dialog_service,
    precede_with,
    succeed_with,
    wrap_with,
)
from vmx.commands.modeled_crud_commands import ModeledCrudCommands
from vmx.commands.protocols import Command, ParameterizedCommand
from vmx.commands.relay_command import (
    RelayCommand,
    RelayCommandBuilder,
    RelayCommandOf,
    RelayCommandOfBuilder,
    RelayCommandOfT,
    RelayCommandOfTBuilder,
)

__all__ = [
    "Command",
    "CompositeCommand",
    "ConfirmationDecoratorCommand",
    "DecoratorCommand",
    "ModeledCrudCommands",
    "ParameterizedCommand",
    "RelayCommand",
    "RelayCommandBuilder",
    "RelayCommandOf",
    "RelayCommandOfBuilder",
    "RelayCommandOfT",
    "RelayCommandOfTBuilder",
    "confirm",
    "confirm_with_dialog_service",
    "precede_with",
    "succeed_with",
    "wrap_with",
]

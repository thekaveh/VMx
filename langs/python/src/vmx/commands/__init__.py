"""VMx Commands — RelayCommand, RelayCommandOf, and Protocol interfaces.

``RelayCommandOf`` / ``RelayCommandOfBuilder`` are the canonical names (parity
with the C# ``RelayCommand<T>`` and TypeScript ``RelayCommandOf`` surfaces). The
legacy v1.0.0 ``RelayCommandOfT`` / ``RelayCommandOfTBuilder`` aliases were
removed in vmx v3.0.0 (ADR-0052; deferral originally recorded in ADR-0009).
"""

from vmx.commands.async_relay_command import (
    AsyncRelayCommand,
    AsyncRelayCommandBuilder,
)
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
)

__all__ = [
    "AsyncRelayCommand",
    "AsyncRelayCommandBuilder",
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
    "confirm",
    "confirm_with_dialog_service",
    "precede_with",
    "succeed_with",
    "wrap_with",
]

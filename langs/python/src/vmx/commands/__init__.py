"""VMx Commands — RelayCommand, RelayCommandOf, and Protocol interfaces.

``RelayCommandOf`` is the canonical name from v1.2.0; ``RelayCommandOfT`` and
``RelayCommandOfTBuilder`` are kept as identity aliases for backward compatibility
and will be removed in vmx v2.0.0.
"""

from vmx.commands.composite_command import CompositeCommand
from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand
from vmx.commands.decorator_command import DecoratorCommand
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
    "ParameterizedCommand",
    "RelayCommand",
    "RelayCommandBuilder",
    "RelayCommandOf",
    "RelayCommandOfBuilder",
    "RelayCommandOfT",
    "RelayCommandOfTBuilder",
]

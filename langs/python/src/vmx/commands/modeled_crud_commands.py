"""ModeledCrudCommands — Create / UpdateCurrent / DeleteCurrent helper.

See spec/06-composite-vm.md §Modeled CRUD commands and ADR-0016.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand
from vmx.commands.protocols import Command
from vmx.commands.relay_command import RelayCommand

VM = TypeVar("VM")
M = TypeVar("M")


class ModeledCrudCommands(Generic[M, VM]):
    """Three CRUD commands wired against a current-VM provider."""

    create_new_command: Command
    update_current_command: Command
    delete_current_command: Command

    def __init__(
        self,
        current: Callable[[], VM | None],
        create_new: Callable[[], None],
        update_current: Callable[[VM], None],
        delete_current: Callable[[VM], None],
        confirm_update: Callable[[], Awaitable[bool]] | None = None,
        confirm_delete: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        def _do_update() -> None:
            c = current()
            if c is not None:
                update_current(c)

        def _do_delete() -> None:
            c = current()
            if c is not None:
                delete_current(c)

        create = RelayCommand.builder().task(create_new).build()
        update = (
            RelayCommand.builder().task(_do_update).predicate(lambda: current() is not None).build()
        )
        delete = (
            RelayCommand.builder().task(_do_delete).predicate(lambda: current() is not None).build()
        )

        # Inner RelayCommands hold trigger subscriptions; track them so dispose()
        # can tear them down (parity with C# ModeledCrudCommands.Dispose).
        self._inner_relays = (create, update, delete)

        self.create_new_command = create
        self.update_current_command = (
            ConfirmationDecoratorCommand(update, confirm=confirm_update)
            if confirm_update is not None
            else update
        )
        self.delete_current_command = (
            ConfirmationDecoratorCommand(delete, confirm=confirm_delete)
            if confirm_delete is not None
            else delete
        )

    def dispose(self) -> None:
        """Dispose the underlying RelayCommands and their trigger subscriptions.

        Note: ``ConfirmationDecoratorCommand`` wrappers (when ``confirm_update`` /
        ``confirm_delete`` are supplied) are NOT tracked separately because they
        hold no subscriptions of their own — ``can_execute_changed`` is a direct
        passthrough to ``inner.can_execute_changed``. This differs from C#, where
        the wrapper subscribes to ``CanExecuteChanged`` events and must dispose
        that subscription explicitly.
        """
        for cmd in self._inner_relays:
            cmd.dispose()

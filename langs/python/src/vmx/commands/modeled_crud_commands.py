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

        # Track the inner RelayCommands so dispose() can complete their
        # can_execute_changed subjects (parity with C# ModeledCrudCommands.
        # Dispose). No triggers are wired here, so there are no trigger
        # subscriptions to release.
        self._inner_relays = (create, update, delete)
        self._disposed = False

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

        Idempotent: subsequent calls are a no-op.

        Note: ``ConfirmationDecoratorCommand`` wrappers (when ``confirm_update`` /
        ``confirm_delete`` are supplied) are NOT tracked separately because they
        hold no subscriptions of their own — ``can_execute_changed`` is a direct
        passthrough to ``inner.can_execute_changed``. This differs from C#, where
        the wrapper subscribes to ``CanExecuteChanged`` events and must dispose
        that subscription explicitly.
        """
        if self._disposed:
            return
        self._disposed = True
        first_error: BaseException | None = None
        for cmd in self._inner_relays:
            try:
                cmd.dispose()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

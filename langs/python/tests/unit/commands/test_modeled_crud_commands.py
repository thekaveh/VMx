"""Unit tests for ModeledCrudCommands disposal and resource cleanup.

Conformance tests for create / update / delete behaviour live in
tests/conformance/test_modeled_crud.py under COMP-019..024.
"""

from __future__ import annotations

from vmx.commands import ConfirmationDecoratorCommand, ModeledCrudCommands


def test_dispose_releases_inner_relay_commands() -> None:
    vm1 = object()
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
    )

    # Sanity: commands work before dispose.
    assert crud.create_new_command.can_execute() is True
    assert crud.update_current_command.can_execute() is True
    assert crud.delete_current_command.can_execute() is True

    # Dispose must not raise; double dispose is safe (idempotent).
    crud.dispose()
    crud.dispose()


def test_dispose_when_confirm_wrappers_present() -> None:
    """Wrappers should still be the public commands; dispose tears down inner relays."""
    vm1 = object()

    async def _yes() -> bool:
        return True

    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
        confirm_update=_yes,
        confirm_delete=_yes,
    )

    assert isinstance(crud.update_current_command, ConfirmationDecoratorCommand)
    assert isinstance(crud.delete_current_command, ConfirmationDecoratorCommand)
    # create_new has no confirm hook by spec.
    assert not isinstance(crud.create_new_command, ConfirmationDecoratorCommand)

    # Double dispose must be idempotent even when wrappers are present
    # (parity with C# Update_And_Delete_Are_Wrapped_With_Confirmation_When_Configured).
    crud.dispose()
    crud.dispose()


def test_dispose_completes_inner_can_execute_changed() -> None:
    """After dispose, inner RelayCommand can_execute_changed streams complete."""
    vm1 = object()
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
    )

    completions = 0

    def _on_completed() -> None:
        nonlocal completions
        completions += 1

    sub_a = crud.create_new_command.can_execute_changed.subscribe(on_completed=_on_completed)
    sub_b = crud.update_current_command.can_execute_changed.subscribe(on_completed=_on_completed)
    sub_c = crud.delete_current_command.can_execute_changed.subscribe(on_completed=_on_completed)

    crud.dispose()

    sub_a.dispose()
    sub_b.dispose()
    sub_c.dispose()

    # Three inner RelayCommands → three completion callbacks.
    assert completions == 3

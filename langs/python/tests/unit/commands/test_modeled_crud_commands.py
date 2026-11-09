"""Unit tests for ModeledCrudCommands disposal and resource cleanup.

Conformance tests for create / update / delete behaviour live in
tests/conformance/test_modeled_crud.py under COMP-019..024.
"""

from __future__ import annotations

import pytest
from reactivex.subject import Subject

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


def test_dispose_attempts_every_command_and_preserves_first_failure() -> None:
    vm1 = object()
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
    )

    def fail_first(_: object) -> None:
        raise RuntimeError("first terminal failure")

    def fail_later(_: object) -> None:
        raise ValueError("later terminal failure")

    crud.create_new_command.can_execute_changed.subscribe(fail_first)
    crud.update_current_command.can_execute_changed.subscribe(fail_later)

    with pytest.raises(RuntimeError, match="first terminal failure"):
        crud.dispose()

    assert all(command._disposed for command in crud._inner_relays)  # type: ignore[attr-defined]
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


# ---------------------------------------------------------------------------
# current_changed trigger (issue #1346, spec/06 §7, ADR-0049)
# ---------------------------------------------------------------------------


def test_update_and_delete_raise_can_execute_changed_on_current_changed_trigger() -> None:
    current: object | None = None
    current_changed: Subject[object] = Subject()
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: current,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
        current_changed=current_changed,
    )
    update_raised: list[object] = []
    delete_raised: list[object] = []
    crud.update_current_command.can_execute_changed.subscribe(update_raised.append)
    crud.delete_current_command.can_execute_changed.subscribe(delete_raised.append)

    assert crud.update_current_command.can_execute() is False
    assert crud.delete_current_command.can_execute() is False

    current = object()
    current_changed.on_next(None)

    assert len(update_raised) == 1
    assert len(delete_raised) == 1
    assert crud.update_current_command.can_execute() is True
    assert crud.delete_current_command.can_execute() is True
    crud.dispose()


def test_current_changed_trigger_reaches_confirmation_wrapped_commands() -> None:
    current: object | None = None
    current_changed: Subject[object] = Subject()

    async def confirm() -> bool:
        return True

    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: current,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
        confirm_update=confirm,
        confirm_delete=confirm,
        current_changed=current_changed,
    )
    assert isinstance(crud.update_current_command, ConfirmationDecoratorCommand)
    assert isinstance(crud.delete_current_command, ConfirmationDecoratorCommand)
    update_raised: list[object] = []
    delete_raised: list[object] = []
    crud.update_current_command.can_execute_changed.subscribe(update_raised.append)
    crud.delete_current_command.can_execute_changed.subscribe(delete_raised.append)

    current = object()
    current_changed.on_next(None)

    assert len(update_raised) == 1
    assert len(delete_raised) == 1
    assert crud.update_current_command.can_execute() is True
    assert crud.delete_current_command.can_execute() is True
    crud.dispose()


@pytest.mark.parametrize("confirmed", [False, True], ids=["plain", "confirmation-wrapped"])
def test_dispose_releases_the_current_changed_subscription(confirmed: bool) -> None:
    current: object | None = None
    current_changed: Subject[object] = Subject()

    async def confirm() -> bool:
        return True

    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: current,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
        confirm_update=confirm if confirmed else None,
        confirm_delete=confirm if confirmed else None,
        current_changed=current_changed,
    )
    raised: list[object] = []
    for command in (
        crud.create_new_command,
        crud.update_current_command,
        crud.delete_current_command,
    ):
        command.can_execute_changed.subscribe(raised.append)
    assert current_changed.observers

    crud.dispose()
    after_dispose = len(raised)
    current = object()
    current_changed.on_next(None)

    assert current_changed.observers == []
    assert len(raised) == after_dispose

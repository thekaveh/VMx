"""Conformance tests: COMP-019..024 — modeled CRUD commands.

Per spec/06-composite-vm.md §Modeled CRUD commands and ADR-0016.
"""

from __future__ import annotations

import asyncio

import pytest

from vmx.commands import ConfirmationDecoratorCommand, ModeledCrudCommands

# ---------------------------------------------------------------------------
# COMP-019
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-019")
def test_COMP_019_create_new_invokes_action() -> None:
    log: list[str] = []
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: None,
        create_new=lambda: log.append("create"),
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
    )
    crud.create_new_command.execute()
    assert log == ["create"]


# ---------------------------------------------------------------------------
# COMP-020
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-020")
def test_COMP_020_update_current_invokes_with_current() -> None:
    log: list[object] = []
    vm1 = object()
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=log.append,
        delete_current=lambda _vm: None,
    )
    crud.update_current_command.execute()
    assert log == [vm1]


# ---------------------------------------------------------------------------
# COMP-021
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-021")
def test_COMP_021_update_can_execute_false_when_current_null() -> None:
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: None,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
    )
    assert crud.update_current_command.can_execute() is False


# ---------------------------------------------------------------------------
# COMP-022
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-022")
def test_COMP_022_delete_current_invokes_with_current() -> None:
    log: list[object] = []
    vm1 = object()
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=log.append,
    )
    crud.delete_current_command.execute()
    assert log == [vm1]


# ---------------------------------------------------------------------------
# COMP-023
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-023")
def test_COMP_023_delete_can_execute_false_when_current_null() -> None:
    crud: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: None,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=lambda _vm: None,
    )
    assert crud.delete_current_command.can_execute() is False


# ---------------------------------------------------------------------------
# COMP-024
# ---------------------------------------------------------------------------


@pytest.mark.conformance("COMP-024")
def test_COMP_024_delete_confirm_gate() -> None:
    log: list[object] = []
    vm1 = object()

    async def _no() -> bool:
        return False

    async def _yes() -> bool:
        return True

    # First: confirm returns False → no delete
    crud_no: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=log.append,
        confirm_delete=_no,
    )
    assert isinstance(crud_no.delete_current_command, ConfirmationDecoratorCommand)
    asyncio.run(crud_no.delete_current_command.execute_async())
    assert log == []

    # Then: confirm returns True → delete
    crud_yes: ModeledCrudCommands[object, object] = ModeledCrudCommands(
        current=lambda: vm1,
        create_new=lambda: None,
        update_current=lambda _vm: None,
        delete_current=log.append,
        confirm_delete=_yes,
    )
    asyncio.run(crud_yes.delete_current_command.execute_async())
    assert log == [vm1]

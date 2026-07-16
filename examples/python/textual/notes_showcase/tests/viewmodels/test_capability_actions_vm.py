"""Tests for CapabilityActionsVM."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import MessageHub, RxDispatcher
from vmx.messages.protocols import Message

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.notebook_model import NotebookModel
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.capability_actions_vm import CapabilityActionsVM
from notes_showcase.viewmodels.note_vm import NoteVM
from notes_showcase.viewmodels.notebook_vm import NotebookVM
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM


def _focus_state() -> dict[str, object | None]:
    return {"focused": None}


def _build_actions_vm(getter_state: dict[str, object | None]) -> CapabilityActionsVM:
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    return (
        CapabilityActionsVM.builder()
        .name("actions")
        .services(hub, dispatcher)
        .focused_getter(lambda: getter_state["focused"])
        .build()
    )


def _build_notebook_vm() -> NotebookVM:
    return (
        NotebookVM.builder()
        .name("nb")
        .model(NotebookModel(id="nb", name="Work", parent_id=None))
        .build()
    )


def _build_note_vm() -> NoteVM:
    return (
        NoteVM.builder()
        .name("note")
        .model(
            NoteModel(
                id="n",
                notebook_id="nb",
                title="T",
                tags=(),
                body="b",
                starred=False,
                created_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
            )
        )
        .build()
    )


def test_actions_is_empty_when_no_focus() -> None:
    state = _focus_state()
    vm = _build_actions_vm(state)
    assert vm.actions.value == []


def test_actions_for_notebook_vm_include_select_expand_collapse_toggle_reconstruct() -> (
    None
):
    state = _focus_state()
    vm = _build_actions_vm(state)
    notebook = _build_notebook_vm()
    notebook.construct()
    state["focused"] = notebook
    vm.recompute_actions()
    labels = {a.label for a in vm.actions.value}
    assert {"Select", "Expand", "Collapse", "Toggle Expansion", "Reconstruct"}.issubset(
        labels
    )
    # NotebookVM does NOT implement IClosable / INewCreatable.
    assert "Close" not in labels
    assert "New" not in labels


def test_actions_for_note_vm_include_close_save_delete_reconstruct() -> None:
    state = _focus_state()
    vm = _build_actions_vm(state)
    note = _build_note_vm()
    note.construct()
    state["focused"] = note
    vm.recompute_actions()
    labels = {a.label for a in vm.actions.value}
    assert {"Select", "Close", "Save", "Delete", "Reconstruct"}.issubset(labels)
    assert "Expand" not in labels  # NoteVM is not IExpandable


def test_actions_for_notebooks_root_vm_includes_new() -> None:
    repo = InMemoryNoteRepository(
        build_seed(), load_all_delay=0.0, add_notebook_delay=0.0
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    root = (
        NotebooksRootVM.builder()
        .name("notebooks")
        .services(hub, dispatcher)
        .repository(repo)
        .build()
    )
    root.construct()
    state = {"focused": root}
    vm = _build_actions_vm(state)
    vm.recompute_actions()
    labels = {a.label for a in vm.actions.value}
    assert "New" in labels


def test_recompute_actions_replaces_projection_on_focus_change() -> None:
    state = _focus_state()
    vm = _build_actions_vm(state)
    nb = _build_notebook_vm()
    nb.construct()
    state["focused"] = nb
    vm.recompute_actions()
    notebook_labels = {a.label for a in vm.actions.value}
    note = _build_note_vm()
    note.construct()
    state["focused"] = note
    vm.recompute_actions()
    note_labels = {a.label for a in vm.actions.value}
    assert "Expand" in notebook_labels and "Expand" not in note_labels
    assert "Close" in note_labels and "Close" not in notebook_labels


def test_builder_requires_name_and_focused_getter() -> None:
    with pytest.raises(ValueError, match="name"):
        CapabilityActionsVM.builder().build()
    with pytest.raises(ValueError, match="focused_getter"):
        CapabilityActionsVM.builder().name("x").build()


def test_dispose_releases_resources() -> None:
    vm = _build_actions_vm(_focus_state())
    vm.construct()
    vm.dispose()
    from vmx import ConstructionStatus

    assert vm.status == ConstructionStatus.DISPOSED


# ── shared delete-command behavior: capability-bar Delete reuses NoteVM.delete_command ──
# so the ConfirmationDecoratorCommand + "Note deleted" notification fire
# from the action-bar identically to the in-list delete button. Prior code
# built a fresh RelayCommand that called note.delete() directly, bypassing
# the gate. Parity with C# (CapabilityActionsVM.cs:121-131) and TS.


def _make_note_with_confirm(
    *,
    confirm_result: bool,
    notification_hub: object | None = None,
) -> tuple[NoteVM, list[bool]]:
    from vmx.notifications import INotificationHub

    deleted: list[bool] = []
    nh = notification_hub if isinstance(notification_hub, INotificationHub) else None

    async def _confirm(_vm: NoteVM) -> bool:
        return confirm_result

    builder = (
        NoteVM.builder()
        .name("note")
        .model(
            NoteModel(
                id="n",
                notebook_id="nb",
                title="T",
                tags=(),
                body="b",
                starred=False,
                created_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
            )
        )
        .on_delete(lambda _vm: deleted.append(True))
        .confirm_delete(_confirm)
    )
    if nh is not None:
        builder = builder.notification_hub(nh)
    note = builder.build()
    note.construct()
    return note, deleted


async def test_capability_bar_delete_reuses_note_delete_command_confirm_false() -> None:
    """Action-bar Delete must route through the ConfirmationDecoratorCommand
    so a "No" answer cancels the delete.
    """
    from vmx.commands import ConfirmationDecoratorCommand

    note, deleted = _make_note_with_confirm(confirm_result=False)
    assert isinstance(note.delete_command, ConfirmationDecoratorCommand)
    state: dict[str, object | None] = {"focused": note}
    vm = _build_actions_vm(state)
    vm.recompute_actions()
    delete_action = next(a for a in vm.actions.value if a.label == "Delete")
    # The action-bar's Delete command must BE the very same wrapped command
    # exposed by NoteVM (parity with C# / TS reuse pattern).
    assert delete_action.command is note.delete_command
    await delete_action.command.execute_async()  # type: ignore[union-attr]
    assert deleted == []


async def test_capability_bar_delete_reuses_note_delete_command_confirm_true() -> None:
    """When the confirm gate accepts, the action-bar Delete fires
    on_delete AND publishes the "Note deleted" notification.
    """
    from vmx.notifications import Notification, NotificationHub

    nh = NotificationHub()
    observed: list[Notification] = []
    nh.pending.subscribe(
        on_next=lambda snap: [observed.append(n) for n in snap if n not in observed]
    )
    note, deleted = _make_note_with_confirm(confirm_result=True, notification_hub=nh)
    state: dict[str, object | None] = {"focused": note}
    vm = _build_actions_vm(state)
    vm.recompute_actions()
    delete_action = next(a for a in vm.actions.value if a.label == "Delete")
    await delete_action.command.execute_async()  # type: ignore[union-attr]
    for _ in range(10):
        if deleted and observed:
            break
        await asyncio.sleep(0)
    assert deleted == [True]
    assert any("Note deleted" in n.message for n in observed)

"""Tests for WorkspaceVM."""

from __future__ import annotations

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import ConstructionStatus, MessageHub, RxDispatcher
from vmx.messages.protocols import Message
from vmx.notifications import NotificationHub

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM


def _build(*, with_notification_hub: bool = True) -> WorkspaceVM:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
        add_notebook_delay=0.0,
        export_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    builder = (
        WorkspaceVM.builder()
        .name("workspace")
        .repository(repo)
        .message_hub(hub)
        .dispatcher(dispatcher)
    )
    if with_notification_hub:
        builder = builder.notification_hub(NotificationHub())
    return builder.build()


async def test_construct_async_populates_notebooks_and_binds_first() -> None:
    ws = _build()
    await ws.construct_async()
    assert ws.is_constructed
    # 5 root notebooks were seeded; one is nested → 4 roots.
    assert len(ws.notebooks_root.roots) == 4
    assert ws.notebooks_root.current is not None
    first = ws.notebooks_root.current
    assert ws.notes_view.bound_notebook_id == first.model.id


async def test_construct_synchronous_does_not_populate() -> None:
    ws = _build()
    ws.construct()
    assert ws.is_constructed
    # populate() not called in sync construct → 0 notebooks.
    assert ws.notebooks_root.all.count == 0


def test_capability_components_are_exposed_after_construct() -> None:
    ws = _build()
    ws.construct()
    assert ws.notebooks_root is not None
    assert ws.notes_view is not None
    assert ws.note_form is not None
    assert ws.status_bar is not None
    assert ws.notifications is not None
    assert ws.capability_actions is not None


async def test_new_notebook_command_predicate_requires_constructed_status() -> None:
    ws = _build()
    assert ws.new_notebook_command.can_execute() is False
    ws.construct()
    assert ws.new_notebook_command.can_execute() is True


async def test_new_note_command_predicate_requires_current_notebook() -> None:
    ws = _build()
    await ws.construct_async()
    # current notebook is set after construct_async → command enabled.
    assert ws.new_note_command.can_execute() is True


def test_set_focus_updates_focused_vm_and_triggers_recompute() -> None:
    ws = _build()
    ws.construct()
    nb_label_set = {a.label for a in ws.capability_actions.actions.value}
    assert nb_label_set == set()  # no focus initially
    # Now focus on the notebooks_root itself (INewCreatable).
    ws.set_focus(ws.notebooks_root)
    labels = {a.label for a in ws.capability_actions.actions.value}
    assert "New" in labels


async def test_dispose_propagates_through_aggregate() -> None:
    ws = _build()
    await ws.construct_async()
    ws.dispose()
    assert ws.status == ConstructionStatus.DISPOSED


def test_builder_requires_repository() -> None:
    with pytest.raises(ValueError, match="repository"):
        WorkspaceVM.builder().build()

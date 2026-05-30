"""Tests for WorkspaceVM."""

from __future__ import annotations

import asyncio

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import ConstructionStatus, MessageHub, RxDispatcher
from vmx.messages.protocols import Message
from vmx.notifications import Notification, NotificationHub

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import IDialogService
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


# ── Audit pass #1, C1: toolbar-command body coverage ──────────────────────


class _StubDialogService(IDialogService):
    """Test stub that returns a pre-canned save path and dismisses confirms."""

    def __init__(self, save_path: str | None) -> None:
        self._save_path = save_path
        self.save_calls = 0
        self.confirm_calls = 0
        self.notify_calls = 0

    async def pick_file_to_open(self, filter=None, title=None) -> str | None:  # noqa: ARG002
        return None

    async def pick_file_to_save(self, filter=None, title=None, suggested_name=None) -> str | None:  # noqa: ARG002
        self.save_calls += 1
        return self._save_path

    async def confirm(self, message: str, title=None) -> bool:  # noqa: ARG002
        self.confirm_calls += 1
        return True

    async def notify(self, message, title=None, severity=None) -> None:  # noqa: ARG002
        self.notify_calls += 1


async def test_new_notebook_command_adds_notebook_and_fires_notification() -> None:
    """``new_notebook_command.execute()`` persists a new notebook and posts the
    "Notebook added" notification.
    """
    notification_hub = NotificationHub()
    observed: list[Notification] = []
    notification_hub.pending.subscribe(
        on_next=lambda snapshot: [observed.append(n) for n in snapshot if n not in observed]
    )
    ws = (
        WorkspaceVM.builder()
        .name("ws")
        .repository(InMemoryNoteRepository(
            build_seed(),
            load_all_delay=0.0,
            add_notebook_delay=0.0,
        ))
        .notification_hub(notification_hub)
        .build()
    )
    await ws.construct_async()
    before = ws.notebooks_root.all.count

    ws.new_notebook_command.execute()
    # Fire-and-forget; let the loop drain.
    await asyncio.sleep(0.05)

    assert ws.notebooks_root.all.count == before + 1
    assert any("Notebook added" in n.message for n in observed)


async def test_new_note_command_adds_note_to_current_notebook() -> None:
    """``new_note_command.execute()`` saves a new note into the current notebook
    via the repo and re-binds the notes view.
    """
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
    )
    ws = (
        WorkspaceVM.builder()
        .name("ws")
        .repository(repo)
        .notification_hub(NotificationHub())
        .build()
    )
    await ws.construct_async()
    nb_id = ws.notebooks_root.current.model.id  # type: ignore[union-attr]
    before = len(await repo.load_notes(nb_id))

    ws.new_note_command.execute()
    await asyncio.sleep(0.05)

    after = len(await repo.load_notes(nb_id))
    assert after == before + 1


class _CountingRepo(InMemoryNoteRepository):
    """Wraps InMemoryNoteRepository with export-call counters for assertions."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.export_count = 0
        self.last_export_path: str | None = None

    async def export(self, notebooks, notes, path):  # type: ignore[override]
        self.export_count += 1
        self.last_export_path = path
        await super().export(notebooks, notes, path)


async def test_export_command_uses_dialog_service_and_writes_via_repo(tmp_path) -> None:
    """``export_command.execute()`` calls ``dialog_service.pick_file_to_save``
    and then ``repo.export`` when the dialog returns a path.
    """
    out_path = str(tmp_path / "notes-export.json")
    repo = _CountingRepo(
        build_seed(),
        load_all_delay=0.0,
        export_delay=0.0,
    )
    dialog = _StubDialogService(save_path=out_path)
    ws = (
        WorkspaceVM.builder()
        .name("ws")
        .repository(repo)
        .dialog_service(dialog)
        .notification_hub(NotificationHub())
        .build()
    )
    await ws.construct_async()

    ws.export_command.execute()
    await asyncio.sleep(0.05)

    assert dialog.save_calls == 1
    assert repo.export_count == 1
    assert repo.last_export_path == out_path


async def test_export_command_cancelled_does_not_call_repo() -> None:
    """If the dialog returns ``None`` (user cancelled), the repo is not called."""
    repo = _CountingRepo(
        build_seed(),
        load_all_delay=0.0,
        export_delay=0.0,
    )
    dialog = _StubDialogService(save_path=None)
    ws = (
        WorkspaceVM.builder()
        .name("ws")
        .repository(repo)
        .dialog_service(dialog)
        .notification_hub(NotificationHub())
        .build()
    )
    await ws.construct_async()

    ws.export_command.execute()
    await asyncio.sleep(0.05)

    assert dialog.save_calls == 1
    assert repo.export_count == 0


def test_dialog_service_property_round_trips() -> None:
    """``WorkspaceVM.dialog_service`` is a late-bindable property — covers the
    getter/setter on the workspace.
    """
    ws = _build()
    initial = ws.dialog_service
    other = _StubDialogService(save_path=None)
    ws.dialog_service = other
    assert ws.dialog_service is other
    # Restoring the original is a no-op for tests.
    ws.dialog_service = initial
    assert ws.dialog_service is initial


async def test_new_note_command_no_op_when_no_current_notebook() -> None:
    """``new_note_command`` predicate fails when no notebook is current; calling
    execute is still safe (fire-and-forget guard inside the body).
    """
    ws = _build()
    ws.construct()
    # No populate → current notebook is None.
    assert ws.new_note_command.can_execute() is False
    # Direct internal coroutine should also no-op gracefully.
    await ws._add_new_note_to_current()  # type: ignore[attr-defined]


async def test_export_command_internal_returns_early_when_no_dialog_path() -> None:
    """Direct coroutine call exercising the early-return branch for cancelled
    dialogs (extra coverage on _export_internal).
    """
    repo = _CountingRepo(build_seed(), load_all_delay=0.0)
    ws = (
        WorkspaceVM.builder()
        .name("ws")
        .repository(repo)
        .dialog_service(_StubDialogService(save_path=None))
        .build()
    )
    ws.construct()
    await ws._export_internal()  # type: ignore[attr-defined]
    assert repo.export_count == 0


# ── Round-3 Critical-2: WorkspaceVM observes notes_view.current and rebinds
# the note form so the right-pane editor reflects the selection. Without
# this subscription, the editor stays empty in the running app.


async def test_setting_notes_view_current_rebinds_note_form() -> None:
    ws = _build()
    await ws.construct_async()
    assert ws.note_form.has_bound_note is False
    await ws.notes_view.bind_to_async("nb-personal")
    first = ws.notes_view.inner[0]
    ws.notes_view.current = first
    # Subscription fires synchronously on the immediate scheduler.
    assert ws.note_form.has_bound_note is True
    assert ws.note_form.title == first.title
    assert ws.note_form.body == first.body


# ── Round-4 Important-1: selecting + deleting clears the form ──────────────
#
# When notes_view.current transitions to None (e.g. the user deletes the
# selected note), the WorkspaceVM subscription must call note_form.unbind()
# so the right pane does not display ghost data from the just-removed note.


class _AcceptDialog(IDialogService):
    """Test-only dialog service whose confirm() always accepts."""

    async def pick_file_to_open(self, filter=None, title=None) -> str | None:  # noqa: ARG002
        return None

    async def pick_file_to_save(self, filter=None, title=None, suggested_name=None) -> str | None:  # noqa: ARG002
        return None

    async def confirm(self, message: str, title=None) -> bool:  # noqa: ARG002
        return True

    async def notify(self, message, title=None, severity=None) -> None:  # noqa: ARG002
        return None


async def test_selecting_a_note_then_deleting_it_clears_the_form() -> None:
    import asyncio

    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
        delete_note_delay=0.0,
    )
    ws = (
        WorkspaceVM.builder()
        .name("ws")
        .repository(repo)
        # AlwaysAcceptDialog ensures the ConfirmationDecorator on
        # NoteVM.delete_command proceeds with the actual delete.
        .dialog_service(_AcceptDialog())
        .notification_hub(NotificationHub())
        .build()
    )
    await ws.construct_async()
    # Pick a note from the auto-bound first notebook.
    note = ws.notes_view.inner[0]
    ws.notes_view.current = note
    assert ws.note_form.has_bound_note is True
    assert ws.note_form.title == note.title

    # Invoke the in-list delete pathway — confirm() returns True, the inner
    # task runs, and NotesViewVM._delete_note_async clears current.
    note.delete_command.execute()
    await asyncio.sleep(0.05)

    assert ws.notes_view.current is None
    # The form must have been unbound — no ghost data left over.
    assert ws.note_form.has_bound_note is False
    assert ws.note_form.title == ""
    assert ws.note_form.body == ""

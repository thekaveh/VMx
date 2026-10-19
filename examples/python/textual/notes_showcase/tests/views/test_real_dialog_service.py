"""The real Textual dialog service drives commands started outside a worker."""

from __future__ import annotations

from textual.widgets import Button

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import NullDialogService
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.adapter.dialog import TextualDialogService
from notes_showcase.views.app import NotesShowcaseApp


async def test_delete_confirmed_through_the_real_modal_deletes_the_note() -> None:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        delete_note_delay=0.0,
        export_delay=0.0,
    )
    workspace = WorkspaceVM.builder().repository(repo).dialog_service(NullDialogService()).build()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    workspace.dialog_service = TextualDialogService(app)
    errors: list[BaseException] = []

    async with app.run_test(size=(160, 50)) as pilot:
        for _ in range(4):
            await pilot.pause()
        workspace.notes_view.current = workspace.notes_view.inner[0]
        for _ in range(6):
            await pilot.pause()
        note = workspace.notes_view.current
        assert note is not None
        note.delete_command.errors.subscribe(on_next=errors.append)
        before = len(workspace.notes_view.inner)
        delete = next(b for b in app.query(Button) if str(b.label) == "Delete")
        delete.press()
        for _ in range(6):
            await pilot.pause()
        yes = next(b for b in app.screen.query(Button) if str(b.label) == "Yes")
        await pilot.click(yes)
        for _ in range(10):
            await pilot.pause(0.05)

        assert errors == []
        assert len(workspace.notes_view.inner) == before - 1

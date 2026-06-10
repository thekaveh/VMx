"""Composition root for the Notes Workspace Textual TUI.

Wires the in-memory repository, the workspace VM tree, and the Textual
:class:`App`. The :class:`TextualDialogService` requires a live ``App``
instance so it is late-bound after ``NotesShowcaseApp`` is constructed
(mirrors the Avalonia composition root in ``Program.cs``).
"""

from __future__ import annotations

import asyncio

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import NullDialogService
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.adapter.dialog import TextualDialogService
from notes_showcase.views.app import NotesShowcaseApp


async def main() -> None:
    repo = InMemoryNoteRepository(build_seed())
    workspace = (
        WorkspaceVM.builder()
        .repository(repo)
        .dialog_service(NullDialogService())
        .build()
    )
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    # Late-bind the dialog service now that the App exists.
    workspace.dialog_service = TextualDialogService(app)
    await app.run_async()
    # Mirror the Avalonia composition root, which disposes the workspace on
    # ShutdownRequested.
    workspace.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""NotesShowcaseApp — Textual :class:`App` subclass that hosts the workspace.

Per spec §6.1, the widget class exposes only ``compose()`` / ``on_mount()`` /
``action_*()``. Each ``action_*`` is a single statement so the Phase 6 CI grep
stays green; the actual work happens inside the bound :class:`WorkspaceVM`
commands.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.widgets import Input

from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.main_screen import MainScreen


class NotesShowcaseApp(App[None]):
    """Notes Workspace TUI rooted at a :class:`WorkspaceVM`."""

    CSS_PATH = "theme.tcss"
    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+n", "new_note", "New note"),
        Binding("ctrl+shift+n", "new_notebook", "New notebook"),
        Binding("ctrl+e", "export", "Export"),
        Binding("ctrl+f", "focus_search", "Search"),
    ]

    def __init__(self, workspace: WorkspaceVM) -> None:
        super().__init__()
        self.workspace = workspace

    def get_default_screen(self) -> MainScreen:
        # Screens are installed, never composed: yielding a Screen from
        # ``compose()`` mounts it as a zero-sized child widget and the whole
        # app renders blank (real-wiring audit, pass 5).
        return MainScreen(self.workspace)

    async def action_save(self) -> None:
        self.workspace.note_form.approve_command.execute()

    async def action_new_note(self) -> None:
        self.workspace.new_note_command.execute()

    async def action_new_notebook(self) -> None:
        self.workspace.new_notebook_command.execute()

    async def action_export(self) -> None:
        self.workspace.export_command.execute()

    async def action_focus_search(self) -> None:
        self.query_one("#search_input", Input).focus()

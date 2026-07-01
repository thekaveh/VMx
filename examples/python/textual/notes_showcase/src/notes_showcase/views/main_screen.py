"""MainScreen — three-pane layout for the Notes Workspace.

Layout (spec §5):

    ┌──────────────┬──────────────────────┬─────────────────────────┐
    │  Notebooks   │  Notes list (centre) │  Note form (right)      │
    └──────────────┴──────────────────────┴─────────────────────────┘
    │  StatusBar   ·   ·   ·                                         │
    │  CapabilityActions [ Save ] [ Reconstruct ] …                  │
    └────────────────────────────────────────────────────────────────┘

The screen owns three column panes inside a :class:`Horizontal`, plus the
status bar, capability strip, and notifications overlay below. Every child
view delegates its binding work to the adapter (Phase 4.b), so this class
contains only structural composition.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.capability_actions import CapabilityActionsView
from notes_showcase.views.global_search import GlobalSearchView
from notes_showcase.views.note_form import NoteFormView
from notes_showcase.views.notebooks_tree import NotebooksTreeView
from notes_showcase.views.notes_list import NotesListView
from notes_showcase.views.notifications import NotificationsView
from notes_showcase.views.status_bar import StatusBarView


class MainScreen(Screen[None]):
    """Top-level screen — three-pane workspace + footer strip."""

    def __init__(self, workspace: WorkspaceVM) -> None:
        super().__init__()
        self._workspace = workspace

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Horizontal(
            NotebooksTreeView(self._workspace.notebooks_root),
            NotesListView(self._workspace.notes_view),
            NoteFormView(self._workspace.note_form),
            id="main_layout",
        )
        yield GlobalSearchView(self._workspace.global_search)
        yield StatusBarView(self._workspace.status_bar)
        yield CapabilityActionsView(self._workspace.capability_actions)
        yield NotificationsView(self._workspace.notifications)
        yield Footer()

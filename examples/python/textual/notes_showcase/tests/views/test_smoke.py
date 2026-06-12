"""Headless smoke tests for the Phase 5.b Textual UI.

The tests exercise the composition root + ``app.run_test()`` plumbing only.
They are intentionally light on UI-event simulation — Textual's ``Pilot`` is
finicky around layout timing and we have richer unit coverage in the
viewmodels and adapter suites. The smokes assert that:

1. The app launches and the notebooks tree shows the four root notebooks.
2. The note form is actually editable end-to-end: writing the new title
   scalar through the binding makes ``is_dirty`` flip and
   ``approve_command.can_execute`` become ``True``.
"""

from __future__ import annotations

import pytest

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import NullDialogService
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.app import NotesShowcaseApp


def _build_workspace() -> WorkspaceVM:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
    )
    return (
        WorkspaceVM.builder()
        .repository(repo)
        .dialog_service(NullDialogService())
        .build()
    )


@pytest.mark.asyncio
async def test_app_launches_and_lists_four_root_notebooks() -> None:
    workspace = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Tree

        tree = app.query_one("#notebooks_tree", Tree)
        roots = list(tree.root.children)
        assert len(roots) == 4
        # Labels should match the four top-level notebooks from build_seed.
        labels = {str(node.label) for node in roots}
        assert labels == {"Work", "Reviews", "Personal", "Archive"}


@pytest.mark.asyncio
async def test_tree_renders_nested_specs_under_work() -> None:
    """Binding-gap #2: ``NotebookVM.children`` lets the tree show hierarchy."""
    workspace = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Tree

        tree = app.query_one("#notebooks_tree", Tree)
        work_node = next(n for n in tree.root.children if str(n.label) == "Work")
        children = [str(c.label) for c in work_node.children]
        assert "Specs" in children


@pytest.mark.asyncio
async def test_editing_a_note_title_flips_dirty_and_enables_save() -> None:
    """Binding-gap #1: the per-field scalar setter on NoteFormVM makes the
    form actually editable end-to-end.
    """
    workspace = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Pick the first note in the currently-bound notebook and bind it.
        first_note = workspace.notes_view.inner[0]
        workspace.note_form.bind_to(first_note.model)
        await pilot.pause()
        # Sanity: clean to start.
        assert workspace.note_form.is_dirty.value is False
        assert workspace.note_form.approve_command.can_execute() is False
        # Edit via the new scalar setter (what the two-way Input binding
        # would call when the user types).
        workspace.note_form.title = "Edited via two-way bind"
        await pilot.pause()
        assert workspace.note_form.is_dirty.value is True
        assert workspace.note_form.is_valid.value is True
        assert workspace.note_form.approve_command.can_execute() is True


@pytest.mark.asyncio
async def test_status_bar_text_updates_via_derived_property_bridge() -> None:
    """Binding-gap #3: DerivedProperty changes drive widget renderables."""
    workspace = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import Static

        # The status bar's note-count Static should display the current
        # filtered-items count via bind_derived_property.
        slot = app.query_one("#status_note_count", Static)
        rendered = str(slot.content)
        assert "note" in rendered.lower()

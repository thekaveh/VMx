"""The Notes page: notebooks, the note list, and the editor, bound to a shared workspace.

The page holds no state of its own. Every element reads from a view-model, and
every event forwards to one. Bindings are released when NiceGUI deletes the
page's client.
"""

from __future__ import annotations

from nicegui import ui
from notes_showcase.viewmodels.note_vm import NoteVM
from notes_showcase.viewmodels.notebook_vm import NotebookVM
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from reactivex.abc import DisposableBase

from nicegui_notes.adapter import (
    bind_command,
    bind_derived_property,
    bind_property_two_way,
    bind_refreshable,
    release_on_delete,
    text,
    vm_property_changes,
)
from nicegui_notes.host import NotesHost

# Every NotesViewVM signal that changes which notes are listed, or their labels.
ROW_SIGNALS = {"visible_items", "current_page_index", "page_count", "page_size"}


def _select_notebook(root: NotebooksRootVM, notebook: NotebookVM) -> None:
    root.current = notebook


def _select_note(notes: NotesViewVM, note: NoteVM) -> None:
    notes.current = note


def _dirty_text(is_dirty: object) -> str:
    return "Unsaved changes" if is_dirty else "Saved"


def _notebooks_pane(workspace: WorkspaceVM) -> DisposableBase:
    root = workspace.notebooks_root

    @ui.refreshable
    def notebooks() -> None:
        for notebook in root.walk():
            ui.button(notebook.model.name, on_click=lambda _, n=notebook: _select_notebook(root, n))

    with ui.column().classes("w-48"):
        ui.label("Notebooks").classes("text-subtitle1")
        notebooks()
    return bind_refreshable(notebooks, root.all.on_property_changed)


def _notes_pane(workspace: WorkspaceVM) -> list[DisposableBase]:
    notes_view = workspace.notes_view

    @ui.refreshable
    def notes() -> None:
        for note in notes_view.visible_items:
            ui.button(note.title, on_click=lambda _, n=note: _select_note(notes_view, n)).props(
                "flat no-caps"
            )

    with ui.column().classes("w-64"):
        ui.label("Notes").classes("text-subtitle1")
        search = ui.input("Search notes").mark("search")
        notes()
        new_note = ui.button("New note").mark("new-note")
    return [
        bind_property_two_way(search, notes_view, "search_term", text),
        bind_refreshable(notes, vm_property_changes(notes_view, ROW_SIGNALS)),
        bind_command(new_note, workspace.new_note_command),
    ]


# docs-snippet:start nicegui-editor
def _editor_pane(workspace: WorkspaceVM) -> list[DisposableBase]:
    form = workspace.note_form
    with ui.column().classes("grow"):
        title = ui.input("Title").classes("w-full").mark("note-title")
        body = ui.textarea("Body").classes("w-full").mark("note-body")
        with ui.row():
            save = ui.button("Save").mark("save")
            revert = ui.button("Revert").mark("revert")
            dirty = ui.label().mark("dirty")
    return [
        bind_property_two_way(title, form, "title", text),
        bind_property_two_way(body, form, "body", text),
        bind_command(save, form.approve_command),
        bind_command(revert, form.deny_command),
        bind_derived_property(dirty, "text", form.is_dirty, _dirty_text),
    ]
    # docs-snippet:end nicegui-editor


# docs-snippet:start nicegui-page
async def build_page(host: NotesHost) -> None:
    """Build one client's page over the host's workspace."""
    workspace = host.workspace if await host.ready() else None
    if workspace is None:
        ui.label("The notes workspace is not running.")
        return
    with ui.row().classes("items-baseline"):
        ui.label("VMx Notes").classes("text-h5")
        status = ui.label().mark("status")
    with ui.row().classes("w-full no-wrap"):
        bindings = [_notebooks_pane(workspace), *_notes_pane(workspace), *_editor_pane(workspace)]
    bindings.append(bind_derived_property(status, "text", workspace.status_bar.note_count_text))
    host.adopt(release_on_delete(*bindings))
    # docs-snippet:end nicegui-page

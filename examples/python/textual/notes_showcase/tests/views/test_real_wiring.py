"""Real-wiring pilot tests — the golden path through actual UI events.

The pass-5 real-wiring audit found the app substantially broken in ways the
existing suites masked by calling VM methods directly (``bind_to``,
``action_press``) or reading dead widget attributes (``renderable``). These
tests drive the same paths a user does — mouse clicks, widget value writes,
selection events — and assert on *rendered* widget state, so a regression in
the view/adapter wiring fails here even when every VM-level test stays green.
"""

from __future__ import annotations

import pytest
from textual.widgets import Input, ListItem, Static, Tree

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import NullDialogService
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.app import NotesShowcaseApp


def _build_workspace() -> tuple[WorkspaceVM, InMemoryNoteRepository]:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
    )
    workspace = (
        WorkspaceVM.builder()
        .repository(repo)
        .dialog_service(NullDialogService())
        .build()
    )
    return workspace, repo


class _ApprovingDialogService(NullDialogService):
    """Confirms everything — stands in for the Textual modal in tests."""

    def __init__(self) -> None:
        super().__init__()
        self.confirm_calls: list[str] = []

    async def confirm(self, message: str, *, title: str = "") -> bool:
        self.confirm_calls.append(message)
        return True


async def _settle(pilot: object, ticks: int = 4) -> None:
    """Let queued fire-and-forget VM tasks and re-renders drain."""
    for _ in range(ticks):
        await pilot.pause()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_clicking_a_note_row_populates_the_editor() -> None:
    """List selection → notes_view.current → form rebind → Input renders."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        assert workspace.note_form.has_bound_note is False

        rows = list(app.query(ListItem))
        assert rows, "notes list rendered no rows"
        await pilot.click(rows[0])
        await pilot.click(rows[0])  # ListView selects on the second click
        await _settle(pilot)

        current = workspace.notes_view.current
        assert current is not None, "row click never reached notes_view.current"
        assert workspace.note_form.has_bound_note is True
        assert app.query_one("#form_title", Input).value == current.title


@pytest.mark.asyncio
async def test_selecting_another_notebook_rebinds_the_notes_list() -> None:
    """notebooks.current change → notes_view.bind_to_async → rows swap."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        first_id = workspace.notes_view.bound_notebook_id
        assert first_id is not None

        other = next(
            nb for nb in workspace.notebooks_root.roots if nb.model.id != first_id
        )
        # The tree's on_tree_node_selected handler performs exactly this
        # assignment; everything downstream is the wiring under test.
        workspace.notebooks_root.current = other
        await _settle(pilot)

        assert workspace.notes_view.bound_notebook_id == other.model.id
        labels = [str(item.children[0].content) for item in app.query(ListItem)]
        expected_titles = {nv.title for nv in workspace.notes_view.visible_items}
        assert {label[2:] for label in labels} == expected_titles


@pytest.mark.asyncio
async def test_save_click_persists_and_refreshes_the_row_label() -> None:
    """Type into the title Input, click Save: repo persists, row re-labels."""
    workspace, repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        rows = list(app.query(ListItem))
        await pilot.click(rows[0])
        await pilot.click(rows[0])
        await _settle(pilot)
        current = workspace.notes_view.current
        assert current is not None

        # Write through the widget: Input.value → watch_value → vm.title.
        app.query_one("#form_title", Input).value = "Retitled by pilot"
        await _settle(pilot)
        assert workspace.note_form.is_dirty.value is True

        await pilot.click("#form_save")
        # The repo simulates I/O (save_note_delay = 0.2 s) — drain for real.
        await pilot.pause(0.5)
        await _settle(pilot)

        notebook_id = workspace.notes_view.bound_notebook_id
        assert notebook_id is not None
        saved = await repo.load_notes(notebook_id)
        assert any(n.title == "Retitled by pilot" for n in saved)
        labels = [str(item.children[0].content) for item in app.query(ListItem)]
        assert any("Retitled by pilot" in label for label in labels)


@pytest.mark.asyncio
async def test_revert_click_restores_the_snapshot_after_rebinds() -> None:
    """The deny binding must survive form rebinds (stable command)."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        rows = list(app.query(ListItem))
        await pilot.click(rows[0])
        await pilot.click(rows[0])
        await _settle(pilot)
        current = workspace.notes_view.current
        assert current is not None
        original_title = current.title

        app.query_one("#form_title", Input).value = "Discard me"
        await _settle(pilot)
        assert workspace.note_form.is_dirty.value is True

        await pilot.click("#form_revert")
        await _settle(pilot)

        assert workspace.note_form.is_dirty.value is False
        assert app.query_one("#form_title", Input).value == original_title


@pytest.mark.asyncio
async def test_starred_filter_click_narrows_visible_rows() -> None:
    """Checkbox click → watch_value chain → vm filter → row rebuild + glyph."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        before = len(list(app.query(ListItem)))
        assert before > 0

        await pilot.click("#starred_filter")
        await _settle(pilot)

        assert workspace.notes_view.show_starred_only is True
        rows = list(app.query(ListItem))
        assert len(rows) == len(workspace.notes_view.visible_items)
        assert len(rows) < before
        assert all(str(item.children[0].content).startswith("★ ") for item in rows)
        # The chained class watcher must still apply the visual toggle state.
        from textual.widgets import Checkbox

        assert app.query_one("#starred_filter", Checkbox).has_class("-on")


@pytest.mark.asyncio
async def test_page_label_and_status_bar_actually_render() -> None:
    """Rendered content (not a dead attribute) carries the bound text."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        page_label = str(app.query_one("#page_label", Static).content)
        assert page_label.startswith("Page 1 of ")


@pytest.mark.asyncio
async def test_new_notebook_appears_in_the_tree() -> None:
    """TreeStructureChangedMessage → adapter subscription → repopulate."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        tree = app.query_one("#notebooks_tree", Tree)
        before = len(list(tree.root.children))

        workspace.new_notebook_command.execute()
        # The in-memory repo simulates I/O (add_notebook_delay = 0.12 s).
        await pilot.pause(0.4)
        await _settle(pilot)

        after = list(tree.root.children)
        assert len(after) == before + 1
        assert any(str(n.label) == "New Notebook" for n in after)


@pytest.mark.asyncio
async def test_late_bound_dialog_service_reaches_delete_confirmation() -> None:
    """The composition root's late-bind must reach the per-note confirms."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    dialog = _ApprovingDialogService()
    workspace.dialog_service = dialog
    assert workspace.notes_view.dialog_service is dialog

    note_vm = workspace.notes_view.inner[0]
    before = workspace.notes_view.inner.count
    note_vm.delete_command.execute()
    # Drain the fire-and-forget confirm/delete chain (the repo simulates
    # I/O: delete_note_delay = 0.12 s plus a notes reload).
    import asyncio

    await asyncio.sleep(0.6)

    assert dialog.confirm_calls, "late-bound dialog service never consulted"
    assert workspace.notes_view.inner.count == before - 1


@pytest.mark.asyncio
async def test_rapid_notebook_switch_lands_on_the_last_selection() -> None:
    """A→B→A: the superseding selection must win even with a bind to B
    mid-await (pass-6 adversarial probe confirmed the original dedupe
    raced and left the notes pane on B while the tree said A)."""
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.05,
    )
    workspace = (
        WorkspaceVM.builder()
        .repository(repo)
        .dialog_service(NullDialogService())
        .build()
    )
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        nb_a = workspace.notebooks_root.current
        assert nb_a is not None
        nb_b = next(
            nb
            for nb in workspace.notebooks_root.roots
            if nb.model.id != nb_a.model.id
        )

        workspace.notebooks_root.current = nb_b
        workspace.notebooks_root.current = nb_a
        await pilot.pause(0.4)
        await _settle(pilot)

        assert workspace.notebooks_root.current is nb_a
        assert workspace.notes_view.bound_notebook_id == nb_a.model.id


@pytest.mark.asyncio
async def test_mouse_click_reaches_a_bound_command() -> None:
    """bind_command must intercept the click path, not just the Enter key."""
    workspace, _repo = _build_workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        workspace.notes_view.page_size = 1
        await _settle(pilot)
        page_label_before = str(app.query_one("#page_label", Static).content)
        assert page_label_before.startswith("Page 1 of ")

        await pilot.click("#page_next")
        await _settle(pilot)

        assert workspace.notes_view.current_page_index == 1
        assert str(app.query_one("#page_label", Static).content).startswith("Page 2")

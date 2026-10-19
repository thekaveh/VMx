"""Pilot regressions for bugs found by driving the real Textual UI.

Each test drives widgets the way a user does (clicks, key presses) and asserts
on rendered state or the persisted repository, so it fails when the view or
view-model wiring regresses even if VM-only suites stay green.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Input, ListItem, Static

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.dialog_service import NullDialogService
from notes_showcase.viewmodels.workspace_vm import WorkspaceVM
from notes_showcase.views.adapter.dialog import TextualDialogService
from notes_showcase.views.app import NotesShowcaseApp
from notes_showcase.views.modals import ConfirmModal, SaveFileModal


def _workspace(**delays: float) -> tuple[WorkspaceVM, InMemoryNoteRepository]:
    options = {"load_all_delay": 0.0, "load_notes_delay": 0.0, **delays}
    repo = InMemoryNoteRepository(build_seed(), **options)
    workspace = WorkspaceVM.builder().repository(repo).dialog_service(NullDialogService()).build()
    return workspace, repo


async def _settle(pilot: object, ticks: int = 4) -> None:
    for _ in range(ticks):
        await pilot.pause()  # type: ignore[attr-defined]


def _rendered(widget: object) -> str:
    return str(getattr(widget, "content", getattr(widget, "renderable", "")))


async def _select_row(pilot: object, app: NotesShowcaseApp, index: int) -> None:
    row = list(app.query(ListItem))[index]
    await pilot.click(row)  # type: ignore[attr-defined]
    await pilot.click(row)  # type: ignore[attr-defined]
    await _settle(pilot)


def _row_labels(app: NotesShowcaseApp) -> list[str]:
    return [_rendered(item.children[0]) for item in app.query(ListItem)]


# ── 1. Switching notes while a save is pending ─────────────────────────────


@pytest.mark.asyncio
async def test_switching_notes_mid_save_still_refreshes_the_row_and_toasts() -> None:
    workspace, repo = _workspace(save_note_delay=0.3)
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        await _select_row(pilot, app, 0)
        saved_id = workspace.notes_view.current.model.id  # type: ignore[union-attr]

        app.query_one("#form_title", Input).value = "Saved while switching"
        await _settle(pilot)
        app.query_one("#form_save", Button).press()
        await _settle(pilot, ticks=2)
        await _select_row(pilot, app, 1)  # rebind while the save is in flight
        other = workspace.notes_view.current
        assert other is not None and other.model.id != saved_id
        assert app.query_one("#form_title", Input).value == other.title

        await pilot.pause(0.6)
        await _settle(pilot)

        _notebooks, notes = await repo.load_all()
        assert any(n.id == saved_id and n.title == "Saved while switching" for n in notes)
        assert any("Saved while switching" in label for label in _row_labels(app))
        toast = _rendered(app.query_one("#notifications_render", Static))
        assert "Saved “Saved while switching”" in toast
        # The newly bound note is untouched and clean.
        assert workspace.note_form.title == other.title
        assert workspace.note_form.is_dirty.value is False
    workspace.dispose()


@pytest.mark.asyncio
async def test_switching_notebooks_mid_save_still_toasts_and_persists() -> None:
    workspace, repo = _workspace(save_note_delay=0.3)
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        await _select_row(pilot, app, 0)
        saved_id = workspace.notes_view.current.model.id  # type: ignore[union-attr]
        first_nb = workspace.notebooks_root.current
        assert first_nb is not None

        app.query_one("#form_title", Input).value = "Saved across notebooks"
        await _settle(pilot)
        app.query_one("#form_save", Button).press()
        await _settle(pilot, ticks=2)
        other = next(nb for nb in workspace.notebooks_root.roots if nb is not first_nb)
        workspace.notebooks_root.current = other
        await pilot.pause(0.6)
        await _settle(pilot)

        _notebooks, notes = await repo.load_all()
        assert any(n.id == saved_id and n.title == "Saved across notebooks" for n in notes)
        toast = _rendered(app.query_one("#notifications_render", Static))
        assert "Saved “Saved across notebooks”" in toast

        workspace.notebooks_root.current = first_nb
        await pilot.pause(0.2)
        await _settle(pilot)
        assert any("Saved across notebooks" in label for label in _row_labels(app))
    workspace.dispose()


# ── 2. Global search: the latest term wins ─────────────────────────────────


@pytest.mark.asyncio
async def test_fast_typing_in_global_search_shows_the_latest_term() -> None:
    # "q" starts a refresh; the backspace lands while it is in flight, so the
    # input ends empty and the results must describe "" rather than "q".
    workspace, repo = _workspace(load_notes_delay=0.3)
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        await pilot.click("#global_search_input")
        await pilot.press("q", "backspace")
        await pilot.pause(1.2)
        await _settle(pilot)

        term = app.query_one("#global_search_input", Input).value
        assert workspace.global_search.search_term == term
        expected, _token = await repo.search_notes(term, None, 5)
        assert [n.model.id for n in workspace.global_search.results] == [n.id for n in expected]
        rendered = _rendered(app.query_one("#global_search_results", Static))
        assert all(n.title in rendered for n in expected)
    workspace.dispose()


# ── 3. Every control is reachable at 80x24 ─────────────────────────────────

_CONTROLS = (
    "#form_add_tag",
    "#form_mode_edit",
    "#form_mode_preview",
    "#form_save",
    "#form_revert",
    "#global_search_input",
    "#global_search_refresh",
    "#global_search_more",
    "#search_input",
    "#page_first",
    "#page_prev",
    "#page_next",
    "#page_last",
    "#form_title",
    "#form_tag_draft",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (120, 40), (250, 70)])
async def test_every_control_is_on_screen_and_clickable(size: tuple[int, int]) -> None:
    workspace, _repo = _workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=size) as pilot:
        await _settle(pilot)
        await _select_row(pilot, app, 0)
        screen = app.screen.region
        # Capability buttons rebuild on focus changes, so hover (not click) them.
        actions = list(app.query("#capability_actions Button"))
        assert actions, "capability actions never rendered"
        for button in actions:
            assert screen.contains_region(button.region), f"{button.id} at {button.region}"
            assert await pilot.hover(button), f"{button.id} is covered or clipped"
        for selector in _CONTROLS:
            widget = app.query_one(selector)
            widget.scroll_visible(animate=False, immediate=True)
            await _settle(pilot, ticks=2)
            assert screen.contains_region(widget.region), f"{selector} at {widget.region}"
            assert await pilot.click(selector), f"{selector} is covered or clipped"
            await pilot.press("escape")
            await _settle(pilot, ticks=2)
    workspace.dispose()


# ── 4. Tag removal, Enter submits, Escape dismisses, export errors ─────────


@pytest.mark.asyncio
async def test_enter_adds_a_tag_and_the_remove_button_removes_it() -> None:
    workspace, _repo = _workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        await _select_row(pilot, app, 0)

        await pilot.click("#form_tag_draft")
        await pilot.press(*"urgent", "enter")
        await _settle(pilot)
        assert workspace.note_form.tags == ("urgent",)
        assert app.query_one("#form_tag_draft", Input).value == ""

        assert await pilot.click("#tag_remove_0")
        await _settle(pilot)
        assert workspace.note_form.tags == ()
        assert not list(app.query("#tag_remove_0"))
    workspace.dispose()


@pytest.mark.asyncio
async def test_escape_dismisses_the_delete_confirmation_as_no() -> None:
    workspace, _repo = _workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    results: list[bool | None] = []
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ConfirmModal("Delete?"), results.append)
        await _settle(pilot)
        await pilot.press("escape")
        await _settle(pilot)
        assert results == [False]
        assert not isinstance(app.screen, ConfirmModal)
    workspace.dispose()


@pytest.mark.asyncio
async def test_enter_submits_the_export_path(tmp_path: Path) -> None:
    workspace, _repo = _workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    results: list[str | None] = []
    target = str(tmp_path / "out.json")
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(SaveFileModal(suggested_name=""), results.append)
        await _settle(pilot)
        await pilot.click("#path")
        await pilot.press(*target, "enter")
        await _settle(pilot)
        assert results == [target]
    workspace.dispose()


@pytest.mark.asyncio
async def test_export_to_a_bad_path_shows_the_error(tmp_path: Path) -> None:
    repo = InMemoryNoteRepository(build_seed(), load_all_delay=0.0, load_notes_delay=0.0)
    workspace = WorkspaceVM.builder().repository(repo).build()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    bad = str(tmp_path / "missing-dir" / "out.json")
    async with app.run_test(size=(160, 50)) as pilot:
        workspace.dialog_service = TextualDialogService(app)
        await _settle(pilot)
        await pilot.press("ctrl+e")
        await _settle(pilot)
        assert isinstance(app.screen, SaveFileModal)
        app.screen.query_one("#path", Input).value = bad
        await pilot.click("#save")
        await pilot.pause(0.5)
        await _settle(pilot)
        toast = _rendered(app.query_one("#notifications_render", Static))
        assert "Export failed" in toast, toast
    await asyncio.sleep(0)
    workspace.dispose()


@pytest.mark.asyncio
async def test_title_error_and_dirty_marker_render_text_not_reprs() -> None:
    workspace, _repo = _workspace()
    await workspace.construct_async()
    app = NotesShowcaseApp(workspace)
    async with app.run_test(size=(160, 50)) as pilot:
        await _settle(pilot)
        await _select_row(pilot, app, 0)
        assert _rendered(app.query_one("#form_title_error", Static)) == ""
        assert _rendered(app.query_one("#form_status", Static)) == "Saved"

        app.query_one("#form_title", Input).value = ""
        await _settle(pilot)
        assert _rendered(app.query_one("#form_title_error", Static)) == "Title is required."
        assert _rendered(app.query_one("#form_status", Static)) == "Unsaved changes"
        assert app.query_one("#form_save", Button).disabled
    workspace.dispose()

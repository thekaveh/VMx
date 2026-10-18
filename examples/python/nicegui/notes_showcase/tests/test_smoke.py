"""Smoke test: the real app (``src/nicegui_notes/__main__.py``) in the user simulation."""

from __future__ import annotations

import asyncio

from nicegui import ui
from nicegui.testing import User


async def test_the_page_shows_the_seed_notes_and_saves_an_edit(user: User) -> None:
    await user.open("/")
    await user.should_see("Work")
    await user.should_see("Standup notes")

    user.find("Standup notes").click()
    title = user.find(marker="note-title")
    await user.should_see(marker="note-title", content="Standup notes")
    await user.should_see("Saved")

    title.clear().type("Standup notes, revised")
    await user.should_see("Unsaved changes")
    user.find(marker="save").click()

    await user.should_see("Saved")
    await user.should_see("Standup notes, revised", kind=None)


async def test_choosing_a_notebook_lists_its_notes(user: User) -> None:
    await user.open("/")
    user.find("Reviews").click()
    await user.should_see("Q1 design review")
    await user.should_not_see("Standup notes")


async def test_typing_in_search_filters_the_note_list(user: User) -> None:
    # Regression: the 150 ms search debounce ran on an ImmediateScheduler,
    # whose WouldBlockException silently ended the search pipeline.
    await user.open("/")
    await user.should_see("Standup notes")
    await user.should_see("Roadmap snapshot")
    await user.should_see(marker="status", content="2 notes")

    user.find(marker="search").type("roadmap")
    await asyncio.sleep(0.5)  # past the debounce

    await user.should_not_see("Standup notes")
    await user.should_see("Roadmap snapshot")
    await user.should_see(marker="status", content="1 note")


async def test_the_pager_moves_to_the_second_page(user: User) -> None:
    await user.open("/")
    user.find("Reviews").click()
    await user.should_see(marker="page-label", content="Page 1 of 2")
    await user.should_see("Q1 design review")

    user.find(marker="page-next").click()

    await user.should_see(marker="page-label", content="Page 2 of 2")
    await user.should_not_see("Q1 design review")
    await user.should_see("Cross-team review log")


async def test_new_note_is_disabled_on_the_readonly_archive(user: User) -> None:
    await user.open("/")
    await user.should_see("Archive")
    (new_note,) = user.find(marker="new-note").elements
    assert new_note.enabled

    user.find("Archive").click()
    for _ in range(20):
        if not new_note.enabled:
            break
        await asyncio.sleep(0.05)
    assert not new_note.enabled


async def test_an_empty_title_shows_the_required_error(user: User) -> None:
    await user.open("/")
    user.find("Standup notes").click()
    await user.should_see(marker="note-title", content="Standup notes")
    await user.should_not_see("Title is required.")

    user.find(marker="note-title").clear()

    await user.should_see(marker="title-error", content="Title is required.")
    (save,) = user.find(marker="save").elements
    assert not save.enabled


async def test_switching_notes_while_a_save_is_pending_still_relabels_the_row(
    user: User,
) -> None:
    # The seeded repository takes 200 ms to save; the second click lands first.
    await user.open("/")
    user.find("Standup notes").click()
    await user.should_see(marker="note-title", content="Standup notes")
    user.find(marker="note-title").clear().type("Standup, saved mid-switch")
    await user.should_see("Unsaved changes")

    user.find(marker="save").click()
    user.find("Roadmap snapshot").click()
    await user.should_see(marker="note-title", content="Roadmap snapshot")
    await asyncio.sleep(0.5)

    await user.should_see("Standup, saved mid-switch", kind=ui.button)
    await user.should_see(marker="dirty", content="Saved")

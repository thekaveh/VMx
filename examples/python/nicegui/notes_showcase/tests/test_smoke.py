"""Smoke test: the real app (``src/nicegui_notes/__main__.py``) in the user simulation."""

from __future__ import annotations

import asyncio

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

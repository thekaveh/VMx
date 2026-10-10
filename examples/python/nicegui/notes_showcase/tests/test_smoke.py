"""Smoke test: the real app (``src/nicegui_notes/__main__.py``) in the user simulation."""

from __future__ import annotations

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

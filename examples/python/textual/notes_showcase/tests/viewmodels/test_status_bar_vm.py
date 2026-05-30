"""Tests for StatusBarVM."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from reactivex.scheduler import ImmediateScheduler

from vmx import MessageHub, RxDispatcher
from vmx.messages.protocols import Message

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.seed import build_seed
from notes_showcase.viewmodels.note_form_vm import NoteFormVM
from notes_showcase.viewmodels.notebooks_root_vm import NotebooksRootVM
from notes_showcase.viewmodels.notes_view_vm import NotesViewVM
from notes_showcase.viewmodels.status_bar_vm import StatusBarVM


def _bootstrap() -> tuple[StatusBarVM, NotesViewVM, NotebooksRootVM, NoteFormVM]:
    repo = InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
        add_notebook_delay=0.0,
    )
    hub = MessageHub[Message]()
    dispatcher = RxDispatcher(
        foreground=ImmediateScheduler(), background=ImmediateScheduler()
    )
    notebooks = (
        NotebooksRootVM.builder()
        .name("notebooks")
        .services(hub, dispatcher)
        .repository(repo)
        .build()
    )
    notes_view = (
        NotesViewVM.builder()
        .name("notes")
        .services(hub, dispatcher)
        .repository(repo)
        .build()
    )
    note_form = (
        NoteFormVM.builder()
        .name("form")
        .services(hub, dispatcher)
        .repository(repo)
        .build()
    )
    status = (
        StatusBarVM.builder()
        .name("status")
        .services(hub, dispatcher)
        .notes_view(notes_view)
        .notebooks(notebooks)
        .note_form(note_form)
        .build()
    )
    notebooks.construct()
    notes_view.construct()
    note_form.construct()
    status.construct()
    return status, notes_view, notebooks, note_form


async def test_note_count_text_reflects_filtered_count() -> None:
    status, nv, *_ = _bootstrap()
    await nv.bind_to_async("nb-reviews")
    assert status.note_count_text.value == "7 notes"
    await nv.bind_to_async("nb-personal")
    assert status.note_count_text.value == "2 notes"


async def test_note_count_text_uses_singular_for_one_item() -> None:
    status, nv, *_ = _bootstrap()
    await nv.bind_to_async("nb-specs")
    assert status.note_count_text.value == "1 note"


async def test_starred_text_counts_only_starred_items() -> None:
    status, nv, *_ = _bootstrap()
    await nv.bind_to_async("nb-reviews")
    # nb-reviews has note-02 + note-07 starred → "2 starred".
    assert status.starred_text.value == "2 starred"


def test_editing_text_reports_no_selection_when_form_unbound() -> None:
    status, _, _, _ = _bootstrap()
    assert status.editing_text.value == "No selection"


def test_editing_text_marks_dirty_state_with_asterisk() -> None:
    status, _, _, note_form = _bootstrap()
    note = NoteModel(
        id="x", notebook_id="nb-1", title="Hello", tags=(), body="",
        starred=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    note_form.bind_to(note)
    assert status.editing_text.value == "Editing: Hello"
    note_form.draft = NoteModel(
        id="x", notebook_id="nb-1", title="Hello edited", tags=(), body="",
        starred=False,
        created_at=note.created_at, updated_at=note.updated_at,
    )
    assert status.editing_text.value == "Editing: Hello edited *"


def test_derived_properties_are_equality_guarded() -> None:
    status, *_ = _bootstrap()
    initial = status.note_count_text.value
    observed: list[str] = []
    status.note_count_text.value_changed.subscribe(on_next=observed.append)
    # No source emission happened, value_changed should not fire when same string.
    assert observed == []
    assert status.note_count_text.value == initial


def test_builder_requires_all_sources() -> None:
    with pytest.raises(ValueError, match="name"):
        StatusBarVM.builder().build()
    with pytest.raises(ValueError, match="notes_view"):
        StatusBarVM.builder().name("x").build()


def test_dispose_releases_subscriptions() -> None:
    status, *_ = _bootstrap()
    status.dispose()
    from vmx import ConstructionStatus

    assert status.status == ConstructionStatus.DISPOSED

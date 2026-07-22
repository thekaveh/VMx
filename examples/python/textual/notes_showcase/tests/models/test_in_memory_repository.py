"""Tests for InMemoryNoteRepository — delay, persistence, export."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.notebook_model import NotebookModel
from notes_showcase.models.seed import build_seed


def _fast_repo() -> InMemoryNoteRepository:
    """Return a repository with all delays zeroed out — useful in most tests."""
    return InMemoryNoteRepository(
        build_seed(),
        load_all_delay=0.0,
        load_notes_delay=0.0,
        save_note_delay=0.0,
        delete_note_delay=0.0,
        add_notebook_delay=0.0,
        export_delay=0.0,
    )


async def test_load_all_returns_seed_after_default_delay() -> None:
    repo = InMemoryNoteRepository(build_seed())
    start = time.perf_counter()
    notebooks, notes = await repo.load_all()
    elapsed = time.perf_counter() - start
    # Prove that the configured latency is honored without imposing an upper
    # wall-clock bound that becomes flaky on contended CI runners.
    assert elapsed >= 0.2
    assert len(notebooks) == 5
    assert len(notes) == 12


async def test_load_notes_filters_by_notebook_id() -> None:
    repo = _fast_repo()
    notes = await repo.load_notes("nb-personal")
    assert {n.id for n in notes} == {"note-11", "note-12"}


async def test_save_note_round_trip_via_load_notes() -> None:
    repo = _fast_repo()
    _, notes = await repo.load_all()
    first = notes[0]
    updated = NoteModel(
        id=first.id,
        notebook_id=first.notebook_id,
        title="Updated",
        tags=first.tags,
        body=first.body,
        starred=first.starred,
        created_at=first.created_at,
        updated_at=first.updated_at,
    )
    await repo.save_note(updated)
    reloaded = await repo.load_notes(first.notebook_id)
    same = next(n for n in reloaded if n.id == first.id)
    assert same.title == "Updated"
    # save_note stamps updated_at to "now" — must move forward.
    assert same.updated_at >= first.updated_at


async def test_save_note_inserts_when_id_is_new() -> None:
    repo = _fast_repo()
    notes_before = await repo.load_notes("nb-archive")
    assert notes_before == []
    fresh = NoteModel(
        id="note-99",
        notebook_id="nb-archive",
        title="Archived idea",
        tags=(),
        body="",
        starred=False,
        created_at=notes_before[0].created_at
        if notes_before
        else (await repo.load_all())[1][0].created_at,
        updated_at=notes_before[0].updated_at
        if notes_before
        else (await repo.load_all())[1][0].updated_at,
    )
    await repo.save_note(fresh)
    after = await repo.load_notes("nb-archive")
    assert [n.id for n in after] == ["note-99"]


async def test_delete_note_removes_by_id() -> None:
    repo = _fast_repo()
    await repo.delete_note("note-01")
    notes = await repo.load_notes("nb-reviews")
    assert "note-01" not in {n.id for n in notes}


async def test_delete_note_unknown_id_is_no_op() -> None:
    repo = _fast_repo()
    before = (await repo.load_all())[1]
    await repo.delete_note("does-not-exist")
    after = (await repo.load_all())[1]
    assert len(before) == len(after)


async def test_add_notebook_appends() -> None:
    repo = _fast_repo()
    nb = NotebookModel(id="nb-new", name="New", parent_id=None)
    await repo.add_notebook(nb)
    notebooks, _ = await repo.load_all()
    assert nb in notebooks


async def test_export_writes_json_payload(tmp_path: Path) -> None:
    repo = _fast_repo()
    notebooks, notes = await repo.load_all()
    out = tmp_path / "export.json"
    await repo.export(notebooks, notes, str(out))
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert {nb["id"] for nb in payload["notebooks"]} == {nb.id for nb in notebooks}
    assert {n["id"] for n in payload["notes"]} == {n.id for n in notes}


async def test_load_notes_honors_default_delay() -> None:
    repo = InMemoryNoteRepository(build_seed())
    start = time.perf_counter()
    await repo.load_notes("nb-work")
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.1


async def test_save_note_honors_default_delay() -> None:
    repo = InMemoryNoteRepository(build_seed())
    _, notes = await repo.load_all()
    note = notes[0]
    start = time.perf_counter()
    await repo.save_note(note)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.15


async def test_repository_satisfies_inote_repository_protocol() -> None:
    from notes_showcase.models.note_repository import INoteRepository

    repo = _fast_repo()
    assert isinstance(repo, INoteRepository)


def test_build_seed_is_deterministic() -> None:
    notebooks_a, notes_a = build_seed()
    notebooks_b, notes_b = build_seed()
    assert notebooks_a == notebooks_b
    assert notes_a == notes_b
    assert {nb.id for nb in notebooks_a} == {
        "nb-work",
        "nb-specs",
        "nb-reviews",
        "nb-personal",
        "nb-archive",
    }
    assert {n.id for n in notes_a if n.starred} == {"note-02", "note-07", "note-10"}


@pytest.mark.parametrize(
    ("notebook_id", "expected_count"),
    [
        ("nb-reviews", 7),
        ("nb-work", 2),
        ("nb-specs", 1),
        ("nb-personal", 2),
        ("nb-archive", 0),
    ],
)
async def test_seed_distribution_matches_csharp(
    notebook_id: str, expected_count: int
) -> None:
    repo = _fast_repo()
    notes = await repo.load_notes(notebook_id)
    assert len(notes) == expected_count

"""Default INoteRepository — in-memory store with simulated I/O delays.

Mirrors the C# ``InMemoryNoteRepository`` (default delays
300/150/200/120/120/150 ms). Thread-safe within a single asyncio event loop via
an ``asyncio.Lock`` gate; safe to call from concurrent coroutines.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.notebook_model import NotebookModel


class InMemoryNoteRepository:
    """In-memory ``INoteRepository`` implementation."""

    def __init__(
        self,
        seed: tuple[list[NotebookModel], list[NoteModel]],
        *,
        load_all_delay: float = 0.300,
        load_notes_delay: float = 0.150,
        save_note_delay: float = 0.200,
        delete_note_delay: float = 0.120,
        add_notebook_delay: float = 0.120,
        export_delay: float = 0.150,
    ) -> None:
        notebooks, notes = seed
        self._notebooks: list[NotebookModel] = list(notebooks)
        self._notes: list[NoteModel] = list(notes)
        self._gate: asyncio.Lock = asyncio.Lock()
        self._load_all_delay = load_all_delay
        self._load_notes_delay = load_notes_delay
        self._save_note_delay = save_note_delay
        self._delete_note_delay = delete_note_delay
        self._add_notebook_delay = add_notebook_delay
        self._export_delay = export_delay

    async def load_all(self) -> tuple[list[NotebookModel], list[NoteModel]]:
        """Return snapshots of all notebooks and notes."""
        await asyncio.sleep(self._load_all_delay)
        async with self._gate:
            return list(self._notebooks), list(self._notes)

    async def load_notes(self, notebook_id: str) -> list[NoteModel]:
        """Return notes belonging to *notebook_id*."""
        await asyncio.sleep(self._load_notes_delay)
        async with self._gate:
            return [n for n in self._notes if n.notebook_id == notebook_id]

    async def save_note(self, note: NoteModel) -> None:
        """Insert or update *note* (stamps ``updated_at`` with UTC now)."""
        await asyncio.sleep(self._save_note_delay)
        async with self._gate:
            stamped = NoteModel(
                id=note.id,
                notebook_id=note.notebook_id,
                title=note.title,
                tags=note.tags,
                body=note.body,
                starred=note.starred,
                created_at=note.created_at,
                updated_at=datetime.now(timezone.utc),
            )
            for i, existing in enumerate(self._notes):
                if existing.id == note.id:
                    self._notes[i] = stamped
                    return
            self._notes.append(stamped)

    async def delete_note(self, note_id: str) -> None:
        """Remove the note with id *note_id* (no-op if absent)."""
        await asyncio.sleep(self._delete_note_delay)
        async with self._gate:
            self._notes = [n for n in self._notes if n.id != note_id]

    async def add_notebook(self, notebook: NotebookModel) -> None:
        """Append *notebook* to the store."""
        await asyncio.sleep(self._add_notebook_delay)
        async with self._gate:
            self._notebooks.append(notebook)

    async def export(
        self,
        notebooks: list[NotebookModel],
        notes: list[NoteModel],
        path: str,
    ) -> None:
        """Write a JSON snapshot to *path*."""
        await asyncio.sleep(self._export_delay)
        payload = {
            "notebooks": [
                {"id": n.id, "name": n.name, "parent_id": n.parent_id}
                for n in notebooks
            ],
            "notes": [
                {
                    "id": n.id,
                    "notebook_id": n.notebook_id,
                    "title": n.title,
                    "tags": list(n.tags),
                    "body": n.body,
                    "starred": n.starred,
                    "created_at": n.created_at.isoformat(),
                    "updated_at": n.updated_at.isoformat(),
                }
                for n in notes
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

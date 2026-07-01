"""INoteRepository — async persistence port for the showcase.

Mirrors the C# ``INoteRepository`` contract (scenario §6.2). The protocol is
runtime-checkable so test doubles satisfy it without explicit inheritance.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.notebook_model import NotebookModel


@runtime_checkable
class INoteRepository(Protocol):
    """Async persistence port for notebooks and notes."""

    async def load_all(self) -> tuple[list[NotebookModel], list[NoteModel]]:
        """Return all notebooks + all notes (simulated ~300 ms latency)."""
        ...

    async def load_notes(self, notebook_id: str) -> list[NoteModel]:
        """Return notes belonging to *notebook_id* (simulated ~150 ms latency)."""
        ...

    async def search_notes(
        self, term: str, token: str | None, page_size: int
    ) -> tuple[list[NoteModel], str | None]:
        """Search all notes with opaque forward-only token paging."""
        ...

    async def save_note(self, note: NoteModel) -> None:
        """Insert or update *note* (simulated ~200 ms latency)."""
        ...

    async def delete_note(self, note_id: str) -> None:
        """Remove the note with id *note_id* (simulated ~120 ms latency)."""
        ...

    async def add_notebook(self, notebook: NotebookModel) -> None:
        """Append *notebook* to the store (simulated ~120 ms latency)."""
        ...

    async def export(
        self,
        notebooks: list[NotebookModel],
        notes: list[NoteModel],
        path: str,
    ) -> None:
        """Write a JSON snapshot to *path* (simulated ~150 ms latency)."""
        ...

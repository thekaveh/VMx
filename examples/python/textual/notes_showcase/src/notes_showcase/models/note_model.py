"""NoteModel — pure-data record for a single note."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NoteModel:
    """Immutable note record.

    ``tags`` is a tuple so the dataclass remains hashable and value-equality
    is structurally honest. ``created_at`` / ``updated_at`` are timezone-aware
    UTC ``datetime`` objects (mirrors the C# ``DateTimeOffset``).
    """

    id: str
    notebook_id: str
    title: str
    tags: tuple[str, ...]
    body: str
    starred: bool
    created_at: datetime
    updated_at: datetime

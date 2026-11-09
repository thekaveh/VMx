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


def note_matches(note: NoteModel, term: str) -> bool:
    """The search rule of every notes showcase, for the notes list and the
    global search alike.

    The term is trimmed, and an empty term matches every note. Otherwise a
    note matches when its title, its body or one of its tags contains the
    term, ignoring case. Each field is matched on its own, so a term never
    spans two fields.
    """
    needle = term.strip().lower()
    if not needle:
        return True
    return (
        needle in note.title.lower()
        or needle in note.body.lower()
        or any(needle in tag.lower() for tag in note.tags)
    )

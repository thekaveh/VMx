"""Domain models + persistence port for the notes showcase."""

from notes_showcase.models.in_memory_repository import InMemoryNoteRepository
from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.note_repository import INoteRepository
from notes_showcase.models.notebook_model import NotebookModel
from notes_showcase.models.seed import build_seed
from notes_showcase.models.theme_model import (
    DARK_PRESET,
    HIGH_CONTRAST_PRESET,
    LIGHT_PRESET,
    PRESETS,
    ThemeModel,
)

__all__ = [
    "DARK_PRESET",
    "HIGH_CONTRAST_PRESET",
    "INoteRepository",
    "InMemoryNoteRepository",
    "LIGHT_PRESET",
    "NoteModel",
    "NotebookModel",
    "PRESETS",
    "ThemeModel",
    "build_seed",
]

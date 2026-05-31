"""Deterministic cross-language seed data.

Mirrors the C# ``SeedData`` content (same notebook ids, note ids, and starred
flags) so cross-language audits compare identically. Data-only — excluded from
the coverage threshold via pytest configuration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from notes_showcase.models.note_model import NoteModel
from notes_showcase.models.notebook_model import NotebookModel


def build_seed() -> tuple[list[NotebookModel], list[NoteModel]]:
    """Return the canonical seed: 5 notebooks (1 nested), 12 notes, 3 starred."""
    # Deterministic "now" so cross-language hash comparisons are stable.
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)

    notebooks: list[NotebookModel] = [
        NotebookModel(id="nb-work", name="Work", parent_id=None),
        NotebookModel(id="nb-specs", name="Specs", parent_id="nb-work"),
        NotebookModel(id="nb-reviews", name="Reviews", parent_id=None),
        NotebookModel(id="nb-personal", name="Personal", parent_id=None),
        NotebookModel(id="nb-archive", name="Archive", parent_id=None),
    ]

    notes: list[NoteModel] = []
    idx = 0

    def add(
        notebook_id: str,
        title: str,
        *,
        starred: bool = False,
        tags: tuple[str, ...] = (),
    ) -> None:
        nonlocal idx
        idx += 1
        notes.append(
            NoteModel(
                id=f"note-{idx:02d}",
                notebook_id=notebook_id,
                title=title,
                tags=tags,
                body=f"(seed body for {title})",
                starred=starred,
                created_at=now - timedelta(days=idx),
                updated_at=now - timedelta(hours=idx),
            )
        )

    add("nb-reviews", "Q1 design review")
    add("nb-reviews", "Auth migration plan", starred=True, tags=("security", "q2"))
    add("nb-reviews", "Vendor shortlist")
    add("nb-reviews", "Onboarding draft")
    add("nb-reviews", "Privacy review notes")
    add("nb-reviews", "Disaster recovery plan")
    add("nb-reviews", "Cross-team review log", starred=True)
    add("nb-work", "Standup notes")
    add("nb-work", "Roadmap snapshot")
    add("nb-specs", "MVx capability brief", starred=True)
    add("nb-personal", "Reading list")
    add("nb-personal", "Travel ideas")

    return notebooks, notes

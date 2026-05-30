# notes-showcase (Textual)

VMx flagship example — Notes Workspace, Python / Textual flavor.

This package currently contains the headless Model + ViewModel layer (Phase 3.b
of the notes-showcase implementation plan). The Textual view layer lands in
Phase 5.b. See `spec/proposals/2026-05-29-notes-showcase-scenario.md` for the
canonical scenario.

## Layout

```
src/notes_showcase/
  models/        # Pure-data records + INoteRepository port
  viewmodels/    # VMx-flavored VMs: workspace, notebooks, notes, form, …
tests/
  models/        # Repository contract + delay-timing tests
  viewmodels/    # Per-VM TDD coverage (≥ 90 % line coverage gate)
```

## Quick start

```bash
cd examples/python/textual/notes_showcase
uv sync --all-extras
uv run pytest
uv run mypy --strict src
```

# notes-showcase (TypeScript / React)

Flagship VMx example: a Notes Workspace built on React 18 + Vite, demonstrating
the 15 VMx features outlined in `spec/proposals/2026-05-29-notes-showcase-scenario.md`.

Phase 3.c (this commit) ships the **Model + ViewModel layers only** — no UI
yet. The view layer lands in Phase 5.c.

## Layout

```
src/
  models/          # Plain records + repository contract + in-memory store
  viewmodels/      # VMx-based VMs (workspace, notebooks, notes, form, etc.)
tests/
  models/          # vitest tests for models
  viewmodels/      # vitest tests for viewmodels
```

## Run

```bash
npm install
npm test           # vitest with coverage (90% lines)
npm run typecheck  # tsc --noEmit
```

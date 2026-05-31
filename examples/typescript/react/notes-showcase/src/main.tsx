/**
 * main.tsx — composition root for the Notes Workspace React app.
 *
 * See plan §5.c. Mirrors:
 *   - `examples/csharp/avalonia/NotesShowcase/Program.cs` (Phase 5.a).
 *   - `examples/python/textual/notes_showcase/src/notes_showcase/__main__.py`
 *     (Phase 5.b).
 *
 * Wiring:
 *   1. Build the model (in-memory repo seeded from `buildSeed()`).
 *   2. Build the dialog service (`ReactDialogService` portal-based modal flow).
 *   3. Build the `WorkspaceVM` via its fluent builder; defaults for hub,
 *      dispatcher, and notification hub come from `WorkspaceVMBuilder.build()`.
 *   4. `await workspace.constructAsync()` so notebooks are loaded and the
 *      first root is current before the first paint (avoids a flicker).
 *   5. Mount `<App>` via `createRoot`.
 */
import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./views/App.js";
import { ReactDialogService } from "./views/adapter/ReactDialogService.js";
import { InMemoryNoteRepository } from "./models/inMemoryRepository.js";
import { buildSeed } from "./models/seed.js";
import { WorkspaceVM } from "./viewmodels/workspaceVM.js";

import "./views/theme.css";

async function bootstrap(): Promise<void> {
  const repo = new InMemoryNoteRepository(buildSeed());
  const dialog = new ReactDialogService();
  const workspace = WorkspaceVM.builder()
    .name("workspace")
    .hint("Notes Workspace")
    .repository(repo)
    .dialogService(dialog)
    .build();

  await workspace.constructAsync();

  const host = document.getElementById("root");
  if (host === null) {
    throw new Error("Composition root: #root element not found in index.html");
  }
  createRoot(host).render(
    <React.StrictMode>
      <App workspace={workspace} dialog={dialog} />
    </React.StrictMode>,
  );
}

void bootstrap();

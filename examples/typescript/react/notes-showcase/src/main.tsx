/**
 * main.tsx — composition root for the Notes Workspace React app.
 *
 * See plan §5.c. Mirrors:
 *   - `examples/csharp/avalonia/NotesShowcase/Program.cs` (Phase 5.a).
 *   - `examples/python/textual/notes_showcase/src/notes_showcase/__main__.py`
 *     (Phase 5.b).
 *
 * Wiring:
 *   1-3. `createWorkspace()` (composition.ts) builds the model (in-memory
 *      repo seeded from `buildSeed()`, exporting through a browser download),
 *      the dialog service (`ReactDialogService` portal-based modal flow), and
 *      the `WorkspaceVM`; defaults for hub, dispatcher, and notification hub
 *      come from `WorkspaceVMBuilder.build()`.
 *   4. `await workspace.constructAsync()` so notebooks are loaded and the
 *      first root is current before the first paint (avoids a flicker).
 *   5. Mount `<App>` via `createRoot`.
 */
import React from "react";
import { createRoot } from "react-dom/client";

import { createWorkspace } from "./composition.js";
import { App } from "./views/App.js";

import "./views/theme.css";

async function bootstrap(): Promise<void> {
  const { workspace, dialog } = createWorkspace();

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

void bootstrap().catch((error: unknown) => {
  console.error("Notes Showcase failed to start", error);
});

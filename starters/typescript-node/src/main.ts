/**
 * Run the notebook flow once: construct, edit, save, recover from an error,
 * and dispose. Replace this file with your own host (CLI, server or UI).
 */
import { ConstructionStatus, __version__ } from "@thekaveh/vmx";

import { InMemoryNoteStore, NoteConflictError, NotebookApp } from "./notes.js";

const store = new InMemoryNoteStore();
const app = new NotebookApp(store, [
  { id: "1", title: "Groceries", body: "Milk, eggs" },
  { id: "2", title: "Ideas", body: "Write a starter" },
]);

try {
  console.log(`VMx ${__version__}`);
  app.start();
  console.log(`constructed: ${app.notebook.isConstructed}, current: ${app.notebook.current?.model.title}`);

  app.renameCurrent("Groceries for Monday");
  await app.saveCurrent.executeAsync();
  console.log(`saved: ${store.get("1")?.title}`);

  // Error path: the store rejects a duplicate title. `executeAsync` rejects,
  // so the caller handles the error inline and the app keeps running.
  app.select("2");
  app.renameCurrent("Groceries for Monday");
  try {
    await app.saveCurrent.executeAsync();
  } catch (error) {
    if (!(error instanceof NoteConflictError)) throw error;
    console.log(`rejected: ${error.message}`);
    app.renameCurrent("Ideas for Monday");
    await app.saveCurrent.executeAsync();
    console.log(`saved after fix: ${store.get("2")?.title}`);
  }
} finally {
  app.dispose();
  console.log(`disposed: ${app.notebook.status === ConstructionStatus.Disposed}`);
}

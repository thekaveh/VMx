/**
 * Starter smoke test: construct, edit, command, error and dispose.
 *
 * Run it with `npm test`. It also checks that the installed VMx version equals
 * the exact pin in package.json, so a partial upgrade fails here first.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  ConstructionStatus,
  PropertyChangedMessage,
  StatusTransitionError,
  __version__,
} from "@thekaveh/vmx";
import { firstValueFrom } from "rxjs";

import {
  InMemoryNoteStore,
  NoteConflictError,
  NotebookApp,
  type NoteVM,
} from "../src/notes.js";

interface PackageManifest {
  readonly dependencies: Record<string, string>;
}

const seed = [
  { id: "1", title: "Groceries", body: "Milk, eggs" },
  { id: "2", title: "Ideas", body: "Write a starter" },
] as const;

test("the installed VMx version equals the package.json pin", () => {
  const manifest = JSON.parse(
    readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
  ) as PackageManifest;
  assert.equal(__version__, manifest.dependencies["@thekaveh/vmx"]);
});

test("construct, edit, command, error and dispose", async () => {
  const store = new InMemoryNoteStore();
  const app = new NotebookApp(store, seed);
  let notes: NoteVM[] = [];
  const changes: string[] = [];
  const subscription = app.hub.messages.subscribe((message) => {
    if (message instanceof PropertyChangedMessage) changes.push(message.propertyName);
  });

  try {
    // Construct: the first construct() builds and constructs the children.
    assert.equal(app.saveCurrent.canExecute(), false);
    app.start();
    notes = [...app.notebook];
    assert.equal(app.notebook.isConstructed, true);
    assert.equal(notes.length, 2);
    assert.equal(notes.every((note) => note.isConstructed), true);
    assert.equal(app.notebook.current?.model.id, "1");

    // Edit: assigning a new model publishes a change on the hub.
    app.renameCurrent("Groceries for Monday");
    assert.equal(app.notebook.current?.modeledHint, "Groceries for Monday");
    assert.ok(changes.includes("model"));

    // Command: the predicate tracks the title, and the task saves the note.
    app.renameCurrent("   ");
    assert.equal(app.saveCurrent.canExecute(), false);
    app.renameCurrent("Groceries for Monday");
    assert.equal(app.saveCurrent.canExecute(), true);
    await app.saveCurrent.executeAsync();
    assert.equal(store.get("1")?.title, "Groceries for Monday");

    // Error, inline: executeAsync rejects with the store's error.
    app.select("2");
    app.renameCurrent("Groceries for Monday");
    await assert.rejects(app.saveCurrent.executeAsync(), NoteConflictError);
    assert.equal(store.get("2"), undefined);

    // Error, fire-and-forget: execute() routes the fault to `errors`.
    const routed = firstValueFrom(app.saveCurrent.errors);
    app.saveCurrent.execute();
    assert.ok((await routed) instanceof NoteConflictError);
    assert.equal(app.errors.length, 1);

    // Recover: fix the title and save again.
    app.renameCurrent("Ideas for Monday");
    await app.saveCurrent.executeAsync();
    assert.equal(store.size, 2);
  } finally {
    subscription.unsubscribe();
    app.dispose();
  }

  // Dispose: terminal for every VM and the command; idempotent for the app.
  assert.equal(app.notebook.status, ConstructionStatus.Disposed);
  assert.equal(notes.every((note) => note.status === ConstructionStatus.Disposed), true);
  assert.equal(app.saveCurrent.canExecute(), false);
  assert.throws(() => app.notebook.construct(), StatusTransitionError);
  app.dispose();
});

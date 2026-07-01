import { describe, expect, it } from "vitest";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { NullDialogService } from "../../src/viewmodels/dialogService.js";
import { WorkspaceVM } from "../../src/viewmodels/workspaceVM.js";

function makeWorkspace(): WorkspaceVM {
  const repo = new InMemoryNoteRepository(buildSeed(), {
    loadAllDelayMs: 0,
    loadNotesDelayMs: 0,
    saveNoteDelayMs: 0,
    addNotebookDelayMs: 0,
  });
  return WorkspaceVM.builder()
    .repository(repo)
    .dialogService(NullDialogService.INSTANCE)
    .build();
}

describe("WorkspaceVM", () => {
  it("constructAsync loads notebooks, selects first, and binds notes", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();

    expect(ws.isConstructed).toBe(true);
    expect(ws.notebooksRoot.all.length).toBe(5);
    expect(ws.notebooksRoot.current).not.toBeNull();
    // First root is nb-work (per seed); has 2 notes.
    expect(ws.notebooksRoot.current?.model.id).toBe("nb-work");
    expect(ws.notesView.inner.length).toBe(2);
    ws.dispose();
  });

  it("exposes six children via the AggregateVM6 composition", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    expect(ws.notebooksRoot).toBeDefined();
    expect(ws.notesView).toBeDefined();
    expect(ws.noteForm).toBeDefined();
    expect(ws.statusBar).toBeDefined();
    expect(ws.notifications).toBeDefined();
    expect(ws.capabilityActions).toBeDefined();
    ws.dispose();
  });

  it("newNotebookCommand only executes once constructed", async () => {
    const ws = makeWorkspace();
    expect(ws.newNotebookCommand.canExecute()).toBe(false);
    await ws.constructAsync();
    expect(ws.newNotebookCommand.canExecute()).toBe(true);
    const before = ws.notebooksRoot.all.length;
    ws.newNotebookCommand.execute();
    await new Promise((r) => setTimeout(r, 0));
    expect(ws.notebooksRoot.all.length).toBe(before + 1);
    ws.dispose();
  });

  it("newNoteCommand requires a current notebook", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    expect(ws.newNoteCommand.canExecute()).toBe(true);
    ws.notebooksRoot.current = null;
    expect(ws.newNoteCommand.canExecute()).toBe(false);
    ws.dispose();
  });

  it("setFocus updates capabilityActions projection", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    const nb = ws.notebooksRoot.current;
    expect(nb).not.toBeNull();
    ws.setFocus(nb);
    expect(ws.capabilityActions.actions.value.length).toBeGreaterThan(0);
    ws.dispose();
  });

  it("selecting a note updates capabilityActions focus", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    const note = ws.notesView.inner[0];
    expect(note).toBeDefined();

    ws.notesView.current = note;

    const labels = ws.capabilityActions.actions.value.map((a) => a.label);
    expect(labels).toContain("Close");
    expect(labels).toContain("Save");
    expect(labels).not.toContain("Expand");

    ws.notesView.current = null;
    const fallback = ws.capabilityActions.actions.value.map((a) => a.label);
    expect(fallback).toContain("Expand");
    expect(fallback).not.toContain("Save");
    ws.dispose();
  });

  it("exportCommand returns silently when dialog cancels", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    // NullDialogService.pickFileToSave returns null → no export
    await new Promise<void>((resolve) => {
      ws.exportCommand.execute();
      setTimeout(resolve, 10);
    });
    expect(ws.isConstructed).toBe(true);
    ws.dispose();
  });

  it("exportCommand persists when the dialog returns a path", async () => {
    let captured: { path: string; payload: string } | null = null;
    const repo = new InMemoryNoteRepository(
      buildSeed(),
      {
        loadAllDelayMs: 0,
        loadNotesDelayMs: 0,
        saveNoteDelayMs: 0,
        addNotebookDelayMs: 0,
        exportDelayMs: 0,
      },
      async (path, payload) => {
        captured = { path, payload };
      },
    );
    const ws = WorkspaceVM.builder()
      .repository(repo)
      .dialogService({
        pickFileToOpen: () => Promise.resolve(null),
        pickFileToSave: () => Promise.resolve("/tmp/out.json"),
        confirm: () => Promise.resolve(false),
        notify: () => Promise.resolve(),
      })
      .build();
    await ws.constructAsync();
    ws.exportCommand.execute();
    await new Promise((r) => setTimeout(r, 30));
    expect(captured).not.toBeNull();
    expect(captured!.path).toBe("/tmp/out.json");
    ws.dispose();
  });

  it("destruct cascades through the aggregate", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    ws.destruct();
    expect(ws.isConstructed).toBe(false);
    ws.dispose();
  });

  it("dispose is idempotent", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    expect(() => ws.dispose()).not.toThrow();
  });

  it("builder requires a repository", () => {
    expect(() => WorkspaceVM.builder().build()).toThrow();
  });

  it("builder honors name, hint, custom hub, dispatcher, and notificationHub", async () => {
    const { MessageHub, RxDispatcher } = await import("@thekaveh/vmx");
    const { NotificationHub } = await import("@thekaveh/vmx/notifications");
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const notifs = new NotificationHub();
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
    });
    const ws = WorkspaceVM.builder()
      .name("my-ws")
      .hint("hint")
      .repository(repo)
      .messageHub(hub)
      .dispatcher(dispatcher)
      .notificationHub(notifs)
      .build();
    await ws.constructAsync();
    expect(ws.hub).toBe(hub);
    expect(ws.isConstructed).toBe(true);
    ws.dispose();
  });

  it("setFocus equality-guards repeat focus on the same target", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    const nb = ws.notebooksRoot.current!;
    ws.setFocus(nb);
    ws.setFocus(nb); // no-op
    expect(ws.focusedVM.value).toBe(nb);
    ws.dispose();
  });

  it("newNoteCommand creates a fresh note in the current notebook", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    const beforeCount = ws.notesView.inner.length;
    ws.newNoteCommand.execute();
    await new Promise((r) => setTimeout(r, 15));
    expect(ws.notesView.inner.length).toBe(beforeCount + 1);
    ws.dispose();
  });

  // ── Round-3 Critical-2 parity: setting notesView.current rebinds noteForm
  // via the WorkspaceVM hub subscription (matches the C# + Py flavors).
  it("setting notesView.current rebinds noteForm", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    expect(ws.noteForm.hasBoundNote).toBe(false);
    await ws.notesView.bindToAsync("nb-personal");
    const first = ws.notesView.inner[0]!;
    ws.notesView.current = first;
    expect(ws.noteForm.hasBoundNote).toBe(true);
    expect(ws.noteForm.draft.title).toBe(first.title);
    expect(ws.noteForm.draft.body).toBe(first.body);
    ws.dispose();
  });

  // ── Round-4 Important-1: selecting + deleting clears the form ────────────
  // When notesView.current transitions to null (e.g. the selected note is
  // deleted) the WorkspaceVM subscription must call noteForm.unbind() so
  // the right pane does not display ghost data from the just-removed note.
  it("selecting a note then deleting it clears the form", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
      addNotebookDelayMs: 0,
      deleteNoteDelayMs: 0,
    });
    const ws = WorkspaceVM.builder()
      .repository(repo)
      // AlwaysAccept dialog so the ConfirmationDecorator proceeds with
      // the actual delete rather than short-circuiting on confirm=false.
      .dialogService({
        pickFileToOpen: () => Promise.resolve(null),
        pickFileToSave: () => Promise.resolve(null),
        confirm: () => Promise.resolve(true),
        notify: () => Promise.resolve(),
      })
      .build();
    await ws.constructAsync();
    const note = ws.notesView.inner[0]!;
    ws.notesView.current = note;
    expect(ws.noteForm.hasBoundNote).toBe(true);
    expect(ws.noteForm.draft.title).toBe(note.title);

    // Invoke the in-list delete pathway — confirm resolves true, the
    // inner task runs, and NotesViewVM.#deleteNoteAsync clears current.
    note.deleteCommand.execute();
    await new Promise((r) => setTimeout(r, 20));

    expect(ws.notesView.current).toBeNull();
    // The form must have been unbound — no ghost data left over.
    expect(ws.noteForm.hasBoundNote).toBe(false);
    expect(ws.noteForm.draft.title).toBe("");
    expect(ws.noteForm.draft.body).toBe("");
    ws.dispose();
  });
});

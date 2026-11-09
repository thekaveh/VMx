import { describe, expect, it, vi } from "vitest";
import type { IAsyncCommand } from "@thekaveh/vmx";
import { NotificationHub } from "@thekaveh/vmx/notifications";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { NullDialogService } from "../../src/viewmodels/dialogService.js";
import { WorkspaceVM } from "../../src/viewmodels/workspaceVM.js";

declare const process: {
  on(event: "unhandledRejection", listener: (reason: unknown) => void): void;
  off(event: "unhandledRejection", listener: (reason: unknown) => void): void;
};

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

  it("newNoteCommand reports the new notebook's readonly state when it notifies", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    const archive = ws.notebooksRoot.roots.find((nb) => nb.model.id === "nb-archive")!;
    const work = ws.notebooksRoot.roots.find((nb) => nb.model.id === "nb-work")!;
    let seen = ws.newNoteCommand.canExecute();
    const sub = ws.newNoteCommand.canExecuteChanged.subscribe(() => {
      seen = ws.newNoteCommand.canExecute();
    });

    ws.selectNotebook(archive);
    expect(seen).toBe(false);
    ws.selectNotebook(work);
    expect(seen).toBe(true);

    sub.unsubscribe();
    ws.dispose();
  });

  it("selectNotebook ignores a notebook dropped by populateAsync", async () => {
    const ws = makeWorkspace();
    await ws.constructAsync();
    const stale = ws.notebooksRoot.roots.find((nb) => nb.model.id === "nb-work")!;
    await ws.notebooksRoot.populateAsync();
    const fresh = ws.notebooksRoot.roots.find((nb) => nb.model.id === "nb-work")!;
    ws.selectNotebook(fresh);

    expect(() => ws.selectNotebook(stale)).not.toThrow();
    expect(ws.notebooksRoot.current).toBe(fresh);

    ws.dispose();
  });

  it("observes a failed selection bind and permits a retry", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
    });
    const ws = WorkspaceVM.builder()
      .repository(repo)
      .dialogService(NullDialogService.INSTANCE)
      .build();
    await ws.constructAsync();
    const personal = ws.notebooksRoot.roots.find((nb) => nb.model.id === "nb-personal");
    const work = ws.notebooksRoot.roots.find((nb) => nb.model.id === "nb-work");
    expect(personal).toBeDefined();
    expect(work).toBeDefined();

    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown): void => { unhandled.push(reason); };
    process.on("unhandledRejection", onUnhandled);
    try {
      repo.failNext(new Error("transient load failure"));
      ws.selectNotebook(personal!);
      await new Promise<void>((resolve) => { setTimeout(resolve, 0); });
      expect(unhandled).toEqual([]);

      ws.selectNotebook(work!);
      await new Promise<void>((resolve) => { setTimeout(resolve, 0); });
      ws.selectNotebook(personal!);
      await new Promise<void>((resolve) => { setTimeout(resolve, 0); });
      expect(ws.notesView.boundNotebookId).toBe("nb-personal");
    } finally {
      process.off("unhandledRejection", onUnhandled);
      ws.dispose();
    }
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
    const ws = WorkspaceVM.builder()
      .repository(
        new InMemoryNoteRepository(buildSeed(), {
          loadAllDelayMs: 0,
          loadNotesDelayMs: 0,
          addNotebookDelayMs: 20,
        }),
      )
      .dialogService(NullDialogService.INSTANCE)
      .build();
    expect(ws.newNotebookCommand.canExecute()).toBe(false);
    await ws.constructAsync();
    expect(ws.newNotebookCommand.canExecute()).toBe(true);
    const before = ws.notebooksRoot.all.length;
    await (ws.newNotebookCommand as IAsyncCommand).executeAsync();
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
    if (note === undefined) {
      throw new Error("expected seeded workspace to load at least one note");
    }

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
    await (ws.exportCommand as IAsyncCommand).executeAsync();
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
    await (ws.exportCommand as IAsyncCommand).executeAsync();
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
    await (ws.newNoteCommand as IAsyncCommand).executeAsync();
    expect(ws.notesView.inner.length).toBe(beforeCount + 1);
    ws.dispose();
  });

  // ── current-selection rebinding: setting notesView.current rebinds noteForm
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

  // ── cleared-selection form behavior: selecting + deleting clears the form ────────────
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

// ── ADR-0201 interaction policies (#1331) ───────────────────────────────────

function makePolicyWorkspace(): {
  ws: WorkspaceVM;
  repo: InMemoryNoteRepository;
  notifications: string[];
} {
  const repo = new InMemoryNoteRepository(buildSeed(), {
    loadAllDelayMs: 0,
    loadNotesDelayMs: 0,
    saveNoteDelayMs: 0,
    addNotebookDelayMs: 0,
  });
  const notificationHub = new NotificationHub();
  const notifications: string[] = [];
  const seen = new Set<unknown>();
  notificationHub.pending.subscribe((list) => {
    for (const notification of list) {
      if (seen.has(notification)) continue;
      seen.add(notification);
      notifications.push(notification.message);
    }
  });
  const ws = WorkspaceVM.builder()
    .repository(repo)
    .dialogService(NullDialogService.INSTANCE)
    .notificationHub(notificationHub)
    .build();
  return { ws, repo, notifications };
}

async function storedTitle(
  repo: InMemoryNoteRepository,
  notebookId: string,
  noteId: string,
): Promise<string | undefined> {
  const notes = await repo.loadNotes(notebookId);
  return notes.find((note) => note.id === noteId)?.title;
}

function noteByTitle(ws: WorkspaceVM, title: string) {
  const note = ws.notesView.inner.find((n) => n.title === title);
  if (note === undefined) throw new Error(`no note titled ${title}`);
  return note;
}

function actionBarSave(ws: WorkspaceVM): IAsyncCommand {
  const save = ws.capabilityActions.actions.value.find((a) => a.label === "Save");
  if (save === undefined) throw new Error("no Save action");
  return save.command as unknown as IAsyncCommand;
}

describe("ADR-0201 §2.1 — a search, the starred filter or a page change keeps current", () => {
  it("keeps the hidden note current with its draft, and shows it again", async () => {
    const { ws } = makePolicyWorkspace();
    await ws.constructAsync();
    const roadmap = noteByTitle(ws, "Roadmap snapshot");
    ws.notesView.current = roadmap;
    ws.noteForm.draft = { ...ws.noteForm.draft, title: "Roadmap draft" };

    ws.notesView.searchTerm = "standup";
    ws.notesView.search();
    expect(ws.notesView.visibleItems).not.toContain(roadmap);
    expect(ws.notesView.current).toBe(roadmap);
    expect(ws.noteForm.draft.title).toBe("Roadmap draft");
    expect(ws.noteForm.isDirty).toBe(true);

    ws.notesView.showStarredOnly = true;
    expect(ws.notesView.current).toBe(roadmap);
    ws.notesView.showStarredOnly = false;

    ws.notesView.searchTerm = "";
    ws.notesView.search();
    expect(ws.notesView.current).toBe(roadmap);
    expect(ws.notesView.visibleItems).toContain(roadmap);
    expect(ws.noteForm.draft.title).toBe("Roadmap draft");
    ws.dispose();
  });

  it("keeps current and the draft across a page change", async () => {
    const { ws } = makePolicyWorkspace();
    await ws.constructAsync();
    await ws.notesView.bindToAsync("nb-reviews");
    const first = ws.notesView.visibleItems[0]!;
    ws.notesView.current = first;
    ws.noteForm.draft = { ...ws.noteForm.draft, title: "Page one draft" };

    ws.notesView.moveToNextPage();
    expect(ws.notesView.visibleItems).not.toContain(first);
    expect(ws.notesView.current).toBe(first);
    expect(ws.noteForm.draft.title).toBe("Page one draft");

    ws.notesView.moveToFirstPage();
    expect(ws.notesView.visibleItems).toContain(first);
    expect(ws.notesView.current).toBe(first);
    ws.dispose();
  });
});

describe("ADR-0201 §2.2 — a note switch discards the unsaved draft", () => {
  it("shows the stored values of each note and persists nothing", async () => {
    const { ws, repo } = makePolicyWorkspace();
    await ws.constructAsync();
    const standup = noteByTitle(ws, "Standup notes");
    const roadmap = noteByTitle(ws, "Roadmap snapshot");

    ws.notesView.current = standup;
    ws.noteForm.draft = { ...ws.noteForm.draft, title: "Unsaved edit" };
    expect(ws.noteForm.isDirty).toBe(true);

    ws.notesView.current = roadmap;
    expect(ws.noteForm.draft.title).toBe("Roadmap snapshot");
    expect(ws.noteForm.isDirty).toBe(false);

    ws.notesView.current = standup;
    expect(ws.noteForm.draft.title).toBe("Standup notes");
    expect(ws.noteForm.isDirty).toBe(false);
    expect(await storedTitle(repo, "nb-work", standup.noteId)).toBe("Standup notes");
    ws.dispose();
  });
});

describe("ADR-0201 §2.3 — the action-bar Save is the editor Save", () => {
  it("persists the editor draft and posts the Saved notification", async () => {
    const { ws, repo, notifications } = makePolicyWorkspace();
    await ws.constructAsync();
    const roadmap = noteByTitle(ws, "Roadmap snapshot");
    ws.notesView.current = roadmap;
    ws.noteForm.draft = { ...ws.noteForm.draft, title: "Roadmap v2" };

    await actionBarSave(ws).executeAsync();

    expect(await storedTitle(repo, "nb-work", roadmap.noteId)).toBe("Roadmap v2");
    expect(ws.noteForm.isDirty).toBe(false);
    expect(notifications).toContain("Saved “Roadmap v2”");
    ws.dispose();
  });

  it("persists nothing when the draft is not valid", async () => {
    const { ws, repo, notifications } = makePolicyWorkspace();
    await ws.constructAsync();
    const roadmap = noteByTitle(ws, "Roadmap snapshot");
    ws.notesView.current = roadmap;
    ws.noteForm.draft = { ...ws.noteForm.draft, title: "" };
    const saveSpy = vi.spyOn(repo, "saveNote");

    await actionBarSave(ws).executeAsync();

    expect(saveSpy).not.toHaveBeenCalled();
    expect(await storedTitle(repo, "nb-work", roadmap.noteId)).toBe("Roadmap snapshot");
    expect(notifications.some((m) => m.startsWith("Saved"))).toBe(false);
    ws.dispose();
  });

  it("persists nothing when the draft is clean", async () => {
    const { ws, repo } = makePolicyWorkspace();
    await ws.constructAsync();
    ws.notesView.current = noteByTitle(ws, "Roadmap snapshot");
    const saveSpy = vi.spyOn(repo, "saveNote");

    await actionBarSave(ws).executeAsync();

    expect(saveSpy).not.toHaveBeenCalled();
    ws.dispose();
  });

  it("persists the stored model of a focused note the editor does not hold", async () => {
    const { ws, repo } = makePolicyWorkspace();
    await ws.constructAsync();
    const standup = noteByTitle(ws, "Standup notes");
    const roadmap = noteByTitle(ws, "Roadmap snapshot");
    ws.notesView.current = roadmap;
    ws.noteForm.draft = { ...ws.noteForm.draft, title: "Roadmap draft" };
    ws.setFocus(standup);
    const saveSpy = vi.spyOn(repo, "saveNote");

    await actionBarSave(ws).executeAsync();

    expect(saveSpy).toHaveBeenCalledTimes(1);
    expect(saveSpy.mock.calls[0]![0]).toBe(standup.model);
    expect(ws.noteForm.draft.title).toBe("Roadmap draft");
    ws.dispose();
  });
});

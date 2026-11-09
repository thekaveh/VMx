import { describe, expect, it, vi } from "vitest";
import type { IAsyncCommand } from "@thekaveh/vmx";
import {
  type Notification,
  NotificationHub,
  NotificationType,
} from "@thekaveh/vmx/notifications";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import type { NoteModel } from "../../src/models/noteModel.js";
import { buildSeed } from "../../src/models/seed.js";
import { NullDialogService } from "../../src/viewmodels/dialogService.js";
import { WorkspaceVM } from "../../src/viewmodels/workspaceVM.js";

declare const process: {
  on(event: "unhandledRejection", listener: (reason: unknown) => void): void;
  off(event: "unhandledRejection", listener: (reason: unknown) => void): void;
};

/** Records each notification once, when it first appears in `pending`. */
function observeNotifications(
  hub: NotificationHub,
  onPost: (notification: Notification) => void = () => {},
): Notification[] {
  const observed: Notification[] = [];
  hub.pending.subscribe((snapshot) => {
    for (const notification of snapshot) {
      if (!observed.includes(notification)) {
        observed.push(notification);
        onPost(notification);
      }
    }
  });
  return observed;
}

function makeExportWorkspace(
  savePath: string | null,
  notificationHub: NotificationHub,
  write: (path: string, payload: string) => Promise<void>,
): WorkspaceVM {
  const repo = new InMemoryNoteRepository(
    buildSeed(),
    {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
      addNotebookDelayMs: 0,
      exportDelayMs: 0,
    },
    write,
  );
  return WorkspaceVM.builder()
    .repository(repo)
    .notificationHub(notificationHub)
    .dialogService({
      pickFileToOpen: () => Promise.resolve(null),
      pickFileToSave: () => Promise.resolve(savePath),
      confirm: () => Promise.resolve(false),
      notify: () => Promise.resolve(),
    })
    .build();
}

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

  it("exportCommand posts one notification after the repository writes (#1329)", async () => {
    let written = false;
    const writtenAtPost: boolean[] = [];
    const notifications = new NotificationHub();
    const observed = observeNotifications(notifications, () => {
      writtenAtPost.push(written);
    });
    const ws = makeExportWorkspace("/tmp/out.json", notifications, async () => {
      written = true;
    });
    await ws.constructAsync();

    await (ws.exportCommand as IAsyncCommand).executeAsync();

    expect(observed.map((n) => n.type)).toEqual([NotificationType.Notification]);
    expect(observed[0]!.message).toBe("Exported to /tmp/out.json");
    expect(writtenAtPost).toEqual([true]);
    ws.dispose();
  });

  it("exportCommand cancelled by the dialog writes nothing and posts nothing (#1329)", async () => {
    let writes = 0;
    const notifications = new NotificationHub();
    const observed = observeNotifications(notifications);
    const ws = makeExportWorkspace(null, notifications, async () => {
      writes += 1;
    });
    await ws.constructAsync();

    await (ws.exportCommand as IAsyncCommand).executeAsync();

    expect(writes).toBe(0);
    expect(observed).toEqual([]);
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

/**
 * Writes each save when it starts, then holds its answer until the test
 * releases that save, so saves can settle out of order (#1379).
 */
class WriteFirstRepository extends InMemoryNoteRepository {
  readonly held: (() => void)[] = [];
  /** Indexes of the saves that throw when released, before they write. */
  readonly failing = new Set<number>();

  constructor() {
    super(buildSeed(), { loadAllDelayMs: 0, loadNotesDelayMs: 0, saveNoteDelayMs: 0 });
  }

  override async saveNote(note: NoteModel): Promise<void> {
    const index = this.held.length;
    if (!this.failing.has(index)) await super.saveNote(note);
    await new Promise<void>((resolve) => this.held.push(resolve));
    if (this.failing.has(index)) throw new Error("disk full");
  }
}

async function waitFor(condition: () => boolean): Promise<void> {
  for (let i = 0; i < 200; i += 1) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("condition not reached");
}

describe("WorkspaceVM save order", () => {
  it("an older save that settles last keeps the newer values (#1379)", async () => {
    const repo = new WriteFirstRepository();
    const ws = WorkspaceVM.builder()
      .repository(repo)
      .dialogService(NullDialogService.INSTANCE)
      .build();
    await ws.constructAsync();
    const [note, other] = ws.notesView.inner;
    const noteId = note!.model.id;
    const form = ws.noteForm;

    // The approve command admits one run at a time, so the test starts each
    // save through approveAsync, as the action-bar Save does.
    ws.notesView.current = note!;
    form.draft = { ...form.draft, title: "Older title" };
    const saveA = form.approveAsync();
    await waitFor(() => repo.held.length === 1);
    // Leave the note and return while save A is held, then start save B.
    ws.notesView.current = other!;
    ws.notesView.current = note!;
    expect(form.draft.title).not.toBe("Older title");
    form.draft = { ...form.draft, title: "Newer title" };
    const saveB = form.approveAsync();
    await waitFor(() => repo.held.length === 2);

    // The newer save settles first, then the older one.
    repo.held[1]!();
    await saveB;
    repo.held[0]!();
    await saveA;

    expect(form.draft.title).toBe("Newer title");
    expect(form.isDirty).toBe(false);
    const row = ws.notesView.inner.find((n) => n.model.id === noteId);
    expect(row?.title).toBe("Newer title");

    // A later save stores the newer values.
    form.draft = { ...form.draft, body: "Body after both saves" };
    const saveC = form.approveAsync();
    await waitFor(() => repo.held.length === 3);
    repo.held[2]!();
    await saveC;
    const stored = (await repo.loadAll()).notes.find((n) => n.id === noteId);
    expect(stored?.title).toBe("Newer title");
    expect(stored?.body).toBe("Body after both saves");
    ws.dispose();
  });

  it.each([
    ["the older save settles first", true],
    ["the newer save fails first", false],
  ])("an older save shows when the newer save fails: %s (#1379)", async (_name, olderSettlesFirst) => {
    const repo = new WriteFirstRepository();
    repo.failing.add(1);
    const ws = WorkspaceVM.builder()
      .repository(repo)
      .dialogService(NullDialogService.INSTANCE)
      .build();
    await ws.constructAsync();
    const [note, other] = ws.notesView.inner;
    const noteId = note!.model.id;
    const form = ws.noteForm;

    ws.notesView.current = note!;
    form.draft = { ...form.draft, title: "Older title" };
    const saveA = form.approveAsync().catch(() => undefined);
    await waitFor(() => repo.held.length === 1);
    ws.notesView.current = other!;
    ws.notesView.current = note!;
    form.draft = { ...form.draft, title: "Newer title" };
    const saveB = form.approveAsync().catch(() => undefined);
    await waitFor(() => repo.held.length === 2);

    const order: [number, Promise<unknown>][] = olderSettlesFirst
      ? [[0, saveA], [1, saveB]]
      : [[1, saveB], [0, saveA]];
    for (const [index, save] of order) {
      repo.held[index]!();
      await save;
    }

    const stored = (await repo.loadAll()).notes.find((n) => n.id === noteId);
    expect(stored?.title).toBe("Older title");
    const row = ws.notesView.inner.find((n) => n.model.id === noteId);
    expect(row?.title).toBe("Older title");
    // The failed save keeps its unsaved edits in the editor.
    expect(form.draft.title).toBe("Newer title");
    ws.dispose();
  });
});

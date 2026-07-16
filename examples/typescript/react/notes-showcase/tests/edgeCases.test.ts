/**
 * Edge-case backfill — Notes-Showcase flagship app (TypeScript / React flavor).
 *
 * Covers four boundary cases that the main scenario does not exercise:
 *
 *   1. Empty-on-startup     — workspace constructs cleanly with zero notebooks.
 *   2. Async failure mode   — repo failures are swallowed by VMs (no crash).
 *   3. Rapid selection race — newer ``bindToAsync`` wins over a stale one.
 *   4. Readonly notebook    — ``addNoteCommand`` gated by ``isReadonly``.
 *
 * These are not new conformance IDs — they are example-app behaviors that
 * should hold across every Notes-Showcase flavor. Cross-flavor parity is
 * maintained in ``tests/test_edge_cases.py`` for the Python flavor.
 */
import { describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";
import { NotificationHub } from "@thekaveh/vmx/notifications";

import { InMemoryNoteRepository } from "../src/models/inMemoryRepository.js";
import type { NotebookModel } from "../src/models/notebookModel.js";
import type { NoteModel } from "../src/models/noteModel.js";
import { buildSeed } from "../src/models/seed.js";
import { CapabilityActionsVM } from "../src/viewmodels/capabilityActionsVM.js";
import { NotesViewVM } from "../src/viewmodels/notesViewVM.js";
import { NoteFormVM } from "../src/viewmodels/noteFormVM.js";
import { WorkspaceVM } from "../src/viewmodels/workspaceVM.js";

function emptySeed(): {
  notebooks: readonly NotebookModel[];
  notes: readonly NoteModel[];
} {
  return { notebooks: Object.freeze([]), notes: Object.freeze([]) };
}

function makeWorkspace(seed: ReturnType<typeof buildSeed>): {
  ws: WorkspaceVM;
  repo: InMemoryNoteRepository;
} {
  const repo = new InMemoryNoteRepository(seed, {
    loadAllDelayMs: 0,
    loadNotesDelayMs: 0,
    saveNoteDelayMs: 0,
    addNotebookDelayMs: 0,
    deleteNoteDelayMs: 0,
    exportDelayMs: 0,
  });
  const ws = WorkspaceVM.builder()
    .repository(repo)
    .notificationHub(new NotificationHub())
    .build();
  return { ws, repo };
}

// ── (1) Empty-on-startup ────────────────────────────────────────────────────

describe("Edge case: empty-on-startup", () => {
  it("constructAsync succeeds with zero notebooks", async () => {
    const { ws } = makeWorkspace(emptySeed());
    await ws.constructAsync();
    expect(ws.isConstructed).toBe(true);
    // Notebooks tree is empty — no auto-selection, no focus, no current.
    expect(ws.notebooksRoot.all.length).toBe(0);
    expect(ws.notebooksRoot.roots).toEqual([]);
    expect(ws.notebooksRoot.current).toBeNull();
    // Notes view: nothing bound, nothing visible.
    expect(ws.notesView.inner.length).toBe(0);
    expect(ws.notesView.visibleItems).toEqual([]);
    expect(ws.notesView.boundNotebookId).toBeNull();
    // Form is unbound; commands stay safely disabled.
    expect(ws.noteForm.hasBoundNote).toBe(false);
    expect(ws.noteForm.isDirty).toBe(false);
    expect(ws.noteForm.approveCommand.canExecute()).toBe(false);
    // WorkspaceVM new-note command requires a current notebook.
    expect(ws.newNoteCommand.canExecute()).toBe(false);
    ws.dispose();
  });

  it("synchronous construct on an empty seed keeps the aggregate consistent", () => {
    const { ws } = makeWorkspace(emptySeed());
    ws.construct();
    expect(ws.isConstructed).toBe(true);
    expect(ws.notebooksRoot.all.length).toBe(0);
    expect(ws.notesView.inner.length).toBe(0);
    expect(ws.noteForm.hasBoundNote).toBe(false);
    ws.dispose();
  });
});

// ── (2) Async failure mode ─────────────────────────────────────────────────

describe("Edge case: async failure mode", () => {
  it("NoteFormVM.approveAsync does not advance snapshot when repo save fails", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      saveNoteDelayMs: 0,
    });
    const hub = new MessageHub();
    const notifications = new NotificationHub();
    const form = NoteFormVM.builder()
      .name("form")
      .services(hub, RxDispatcher.immediate())
      .repository(repo)
      .notificationHub(notifications)
      .build();
    form.construct();

    const { notes } = await repo.loadAll();
    const original = notes[0]!;
    form.bindTo(original);
    form.draft = { ...form.draft, title: "Edited offline" };
    const snapshotBefore = form.snapshot;

    // Arm a single-shot failure on the next save.
    repo.failNext(new Error("disk full"));
    await expect(form.approveAsync()).rejects.toThrow(/disk full/);
    // Snapshot did NOT advance — the form is still dirty.
    expect(form.snapshot).toEqual(snapshotBefore);
    expect(form.isDirty).toBe(true);
    // Recovery: next approve succeeds (failure was single-shot).
    await form.approveAsync();
    expect(form.snapshot.title).toBe("Edited offline");
    expect(form.isDirty).toBe(false);
    form.dispose();
  });

  it("WorkspaceVM.constructAsync propagates a load failure", async () => {
    const { ws, repo } = makeWorkspace(buildSeed());
    repo.failNext(new Error("network down"));
    await expect(ws.constructAsync()).rejects.toThrow(/network down/);
    // The synchronous aggregate cascade completed before populate ran.
    expect(ws.isConstructed).toBe(true);
    expect(ws.notebooksRoot.all.length).toBe(0); // populate aborted
    ws.dispose();
  });
});

// ── (3) Rapid notebook selection concurrency ────────────────────────────────

describe("Edge case: rapid notebook selection", () => {
  it("bindToAsync discards stale results when superseded", async () => {
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      // Non-zero delay so we can interleave two binds reliably.
      loadNotesDelayMs: 50,
      saveNoteDelayMs: 0,
    });
    const hub = new MessageHub();
    const view = NotesViewVM.builder()
      .name("notes")
      .services(hub, RxDispatcher.immediate())
      .repository(repo)
      .pageSize(5)
      .searchDebounceMs(150)
      .build();
    view.construct();

    // Race: kick off A and B back-to-back without awaiting between them.
    // Both call loadNotes immediately; B increments the token so A's
    // resume becomes a no-op.
    const taskA = view.bindToAsync("nb-reviews"); // 7 notes
    const taskB = view.bindToAsync("nb-personal"); // 2 notes
    await Promise.all([taskA, taskB]);

    expect(view.boundNotebookId).toBe("nb-personal");
    expect(view.inner.length).toBe(2);
    for (const n of view.inner) {
      expect(n.model.notebookId).toBe("nb-personal");
    }
    view.dispose();
  });
});

// ── (4) Readonly notebook capability gating ─────────────────────────────────

describe("Edge case: readonly notebook capability gating", () => {
  it("isReadonly defaults to false (or undefined) for plain notebooks", () => {
    const nb: NotebookModel = { id: "nb", name: "N", parentId: null };
    expect(nb.isReadonly ?? false).toBe(false);
  });

  it("CapabilityActionsVM.addNoteCommand reports canExecute=false for readonly notebooks", async () => {
    const seed = {
      notebooks: Object.freeze<NotebookModel[]>([
        { id: "nb-readonly", name: "Archive", parentId: null, isReadonly: true },
      ]),
      notes: Object.freeze<NoteModel[]>([]),
    };
    const { ws } = makeWorkspace(seed);
    await ws.constructAsync();
    expect(ws.notesView.currentNotebookIsReadonly).toBe(true);
    expect(ws.capabilityActions.addNoteCommand.canExecute()).toBe(false);
    ws.dispose();
  });

  it("CapabilityActionsVM.addNoteCommand reports canExecute=true for writable notebooks", async () => {
    const seed = {
      notebooks: Object.freeze<NotebookModel[]>([
        { id: "nb-rw", name: "Drafts", parentId: null, isReadonly: false },
      ]),
      notes: Object.freeze<NoteModel[]>([]),
    };
    const { ws } = makeWorkspace(seed);
    await ws.constructAsync();
    expect(ws.notesView.currentNotebookIsReadonly).toBe(false);
    expect(ws.capabilityActions.addNoteCommand.canExecute()).toBe(true);
    ws.dispose();
  });

  it("standalone CapabilityActionsVM without canAddNote uses an always-true default", () => {
    const hub = new MessageHub();
    const vm = CapabilityActionsVM.builder()
      .name("capabilities")
      .services(hub, RxDispatcher.immediate())
      .focusedGetter(() => null)
      .build();
    expect(vm.addNoteCommand.canExecute()).toBe(true);
    vm.dispose();
  });
});

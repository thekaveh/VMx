import { describe, expect, it, vi } from "vitest";
import {
  ConfirmationDecoratorCommand,
  declareCapabilities,
  MessageHub,
  RxDispatcher,
} from "@thekaveh/vmx";
import {
  Notification,
  NotificationHub,
} from "@thekaveh/vmx/notifications";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import type { NoteModel } from "../../src/models/noteModel.js";
import type { NotebookModel } from "../../src/models/notebookModel.js";
import { buildSeed } from "../../src/models/seed.js";
import { CapabilityActionsVM } from "../../src/viewmodels/capabilityActionsVM.js";
import { NotebooksRootVM } from "../../src/viewmodels/notebooksRootVM.js";
import { NotebookVM } from "../../src/viewmodels/notebookVM.js";
import { NoteVM } from "../../src/viewmodels/noteVM.js";

function makeNotebook(): NotebookVM {
  const hub = new MessageHub();
  const vm = NotebookVM.builder()
    .name("nb:test")
    .model({ id: "nb-test", name: "T", parentId: null } satisfies NotebookModel)
    .services(hub, RxDispatcher.immediate())
    .build();
  vm.construct();
  return vm;
}

function makeNote(): NoteVM {
  const hub = new MessageHub();
  const model: NoteModel = {
    id: "note-test",
    notebookId: "nb-test",
    title: "T",
    tags: [],
    body: "",
    starred: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  const vm = NoteVM.builder()
    .name("note:test")
    .model(model)
    .services(hub, RxDispatcher.immediate())
    .build();
  vm.construct();
  return vm;
}

function makeCap(getter: () => object | null): CapabilityActionsVM {
  const hub = new MessageHub();
  const vm = CapabilityActionsVM.builder()
    .name("capabilities")
    .services(hub, RxDispatcher.immediate())
    .focusedGetter(getter)
    .build();
  vm.construct();
  return vm;
}

describe("CapabilityActionsVM", () => {
  it("empty list when nothing is focused", () => {
    const vm = makeCap(() => null);
    expect(vm.actions.value).toEqual([]);
  });

  it("projects a notebook's capability surface", () => {
    const nb = makeNotebook();
    const vm = makeCap(() => nb);
    const labels = vm.actions.value.map((a) => a.label);
    expect(labels).toContain("Select");
    expect(labels).toContain("Expand");
    expect(labels).toContain("Collapse");
    expect(labels).toContain("Toggle Expansion");
    expect(labels).toContain("Reconstruct");
    // Notebook is NOT a NoteVM so Save/Delete must be absent.
    expect(labels).not.toContain("Save");
    expect(labels).not.toContain("Delete");
  });

  it("includes Save and Delete only for a NoteVM target", () => {
    const note = makeNote();
    const vm = makeCap(() => note);
    const labels = vm.actions.value.map((a) => a.label);
    expect(labels).toContain("Save");
    expect(labels).toContain("Delete");
    expect(labels).toContain("Close");
  });

  it("recomputeActions republishes the derived list", () => {
    let focused: object | null = null;
    const vm = makeCap(() => focused);
    expect(vm.actions.value.length).toBe(0);
    const nb = makeNotebook();
    focused = nb;
    vm.recomputeActions();
    expect(vm.actions.value.length).toBeGreaterThan(0);
  });

  it("each action command is executable end-to-end", () => {
    const nb = makeNotebook();
    const vm = makeCap(() => nb);
    const toggle = vm.actions.value.find((a) => a.label === "Toggle Expansion");
    expect(toggle).toBeDefined();
    expect(nb.isExpanded).toBe(false);
    toggle!.command.execute();
    expect(nb.isExpanded).toBe(true);
  });

  it("dispose tears down without throwing", () => {
    const vm = makeCap(() => null);
    expect(() => vm.dispose()).not.toThrow();
  });

  it("builder validates required fields", () => {
    expect(() => CapabilityActionsVM.builder().build()).toThrow();
  });

  it("focusedVM getter delegates to the supplied getter", () => {
    const nb = makeNotebook();
    const vm = makeCap(() => nb);
    expect(vm.focusedVM).toBe(nb);
  });

  it("projects every other capability label when the marker is set", () => {
    // A bag-of-markers stub: declares every capability the projector knows
    // about and supplies stub methods so each command can be built / fired.
    const allCaps = {
      canSelect: vi.fn(() => true),
      select: vi.fn(),
      canDeselect: vi.fn(() => true),
      deselect: vi.fn(),
      canToggleSelection: vi.fn(() => true),
      toggleSelection: vi.fn(),
      canExpand: vi.fn(() => true),
      expand: vi.fn(),
      canCollapse: vi.fn(() => true),
      collapse: vi.fn(),
      canToggleExpansion: vi.fn(() => true),
      toggleExpansion: vi.fn(),
      canClose: vi.fn(() => true),
      close: vi.fn(),
      canApprove: vi.fn(() => true),
      approve: vi.fn(),
      canCancel: vi.fn(() => true),
      cancel: vi.fn(),
      canCreateNew: vi.fn(() => true),
      createNew: vi.fn(),
      canReconstruct: vi.fn(() => true),
      reconstruct: vi.fn(),
    };
    declareCapabilities(
      allCaps,
      "ISelectable",
      "IDeselectable",
      "ISelectionTogglable",
      "IExpandable",
      "ICollapsible",
      "IExpansionTogglable",
      "IClosable",
      "IApprovable",
      "ICancelable",
      "INewCreatable",
      "IReconstructable",
    );
    const out = CapabilityActionsVM.project(allCaps);
    const labels = out.map((a) => a.label);
    expect(labels).toEqual([
      "Select",
      "Deselect",
      "Toggle Selection",
      "Expand",
      "Collapse",
      "Toggle Expansion",
      "Close",
      "Approve",
      "Cancel",
      "New",
      "Reconstruct",
    ]);
    // Execute each command to ensure the wiring is sound and stubs were hit.
    for (const a of out) a.command.execute();
    expect(allCaps.select).toHaveBeenCalled();
    expect(allCaps.deselect).toHaveBeenCalled();
    expect(allCaps.toggleSelection).toHaveBeenCalled();
    expect(allCaps.expand).toHaveBeenCalled();
    expect(allCaps.collapse).toHaveBeenCalled();
    expect(allCaps.toggleExpansion).toHaveBeenCalled();
    expect(allCaps.close).toHaveBeenCalled();
    expect(allCaps.approve).toHaveBeenCalled();
    expect(allCaps.cancel).toHaveBeenCalled();
    expect(allCaps.createNew).toHaveBeenCalled();
    expect(allCaps.reconstruct).toHaveBeenCalled();
  });

  it("notebooks root (INewCreatable) projects a 'New' action", () => {
    const hub = new MessageHub();
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      addNotebookDelayMs: 0,
    });
    const root = NotebooksRootVM.builder()
      .name("root")
      .services(hub, RxDispatcher.immediate())
      .repository(repo)
      .build();
    root.construct();
    const out = CapabilityActionsVM.project(root);
    expect(out.map((a) => a.label)).toContain("New");
  });

  // ── Round-3 Critical-1: capability-bar Delete reuses NoteVM.deleteCommand ─
  // so the ConfirmationDecoratorCommand + "Note deleted" notification fire
  // from the action-bar identically to the in-list delete button. Prior
  // code built a fresh RelayCommand that called note.delete() directly,
  // bypassing the gate. Parity with C# (CapabilityActionsVM.cs:121-131)
  // and Python.

  function makeNoteWithConfirm(
    confirmResult: boolean,
    notificationHub: NotificationHub | null = null,
  ): { note: NoteVM; deleted: boolean[] } {
    const deleted: boolean[] = [];
    const hub = new MessageHub();
    const model: NoteModel = {
      id: "note-cap",
      notebookId: "nb-cap",
      title: "T",
      tags: [],
      body: "",
      starred: false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    let builder = NoteVM.builder()
      .name("note:cap")
      .model(model)
      .services(hub, RxDispatcher.immediate())
      .onDelete(() => {
        deleted.push(true);
      })
      .confirmDelete(async () => confirmResult);
    if (notificationHub !== null) {
      builder = builder.notificationHub(notificationHub);
    }
    const note = builder.build();
    note.construct();
    return { note, deleted };
  }

  it("capability-bar Delete reuses note.deleteCommand (confirm=false → no delete)", async () => {
    const { note, deleted } = makeNoteWithConfirm(false);
    expect(note.deleteCommand).toBeInstanceOf(ConfirmationDecoratorCommand);
    const cap = makeCap(() => note);
    const action = cap.actions.value.find((a) => a.label === "Delete");
    expect(action).toBeDefined();
    // Same wrapped reference as note.deleteCommand (parity contract).
    expect(action!.command).toBe(note.deleteCommand);
    await (action!.command as ConfirmationDecoratorCommand).executeAsync();
    expect(deleted).toEqual([]);
  });

  it("capability-bar Delete fires notification when confirm=true", async () => {
    const notifs = new NotificationHub();
    const observed: Notification[] = [];
    notifs.pending.subscribe((snap) => {
      for (const n of snap) {
        if (!observed.includes(n)) observed.push(n);
      }
    });
    const { note, deleted } = makeNoteWithConfirm(true, notifs);
    const cap = makeCap(() => note);
    const action = cap.actions.value.find((a) => a.label === "Delete");
    await (action!.command as ConfirmationDecoratorCommand).executeAsync();
    expect(deleted).toEqual([true]);
    expect(observed.some((n) => n.message.includes("Note deleted"))).toBe(true);
  });
});

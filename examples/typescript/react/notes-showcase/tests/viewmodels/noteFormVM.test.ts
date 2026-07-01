import { describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";
import {
  NotificationHub,
  NotificationReaction,
  type INotificationHub,
} from "@thekaveh/vmx/notifications";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import type { NoteModel } from "../../src/models/noteModel.js";
import { buildSeed } from "../../src/models/seed.js";
import { NoteFormVM } from "../../src/viewmodels/noteFormVM.js";

function aNote(over: Partial<NoteModel> = {}): NoteModel {
  return {
    id: "note-99",
    notebookId: "nb-work",
    title: "Title",
    tags: [],
    body: "Body",
    starred: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...over,
  };
}

function makeForm(): {
  vm: NoteFormVM;
  hub: MessageHub;
  repo: InMemoryNoteRepository;
  notifs: INotificationHub;
} {
  const hub = new MessageHub();
  const repo = new InMemoryNoteRepository(buildSeed(), {
    saveNoteDelayMs: 0,
  });
  const notifs = new NotificationHub();
  const vm = NoteFormVM.builder()
    .name("form")
    .services(hub, RxDispatcher.immediate())
    .repository(repo)
    .notificationHub(notifs)
    .build();
  vm.construct();
  return { vm, hub, repo, notifs };
}

describe("NoteFormVM", () => {
  it("snapshot captured on bindTo; draft mirrors initial note", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote());
    expect(vm.draft.title).toBe("Title");
    expect(vm.snapshot.title).toBe("Title");
    expect(vm.isDirty).toBe(false);
  });

  it("isDirty becomes true on draft mutation", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote());
    vm.draft = { ...vm.draft, title: "Updated" };
    expect(vm.isDirty).toBe(true);
  });

  it("approve persists, clears isDirty, and re-snapshots", async () => {
    const { vm, repo } = makeForm();
    vm.bindTo(aNote({ title: "Original" }));
    vm.draft = { ...vm.draft, title: "Persisted" };
    await vm.approveAsync();
    expect(vm.isDirty).toBe(false);
    expect(vm.snapshot.title).toBe("Persisted");
    const work = await repo.loadNotes("nb-work");
    expect(work.find((n) => n.id === "note-99")?.title).toBe("Persisted");
  });

  it("approveCommand.canExecute = isDirty && isValid", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ title: "Original" }));
    expect(vm.approveCommand.canExecute()).toBe(false); // not dirty
    vm.draft = { ...vm.draft, title: "" }; // dirty but not valid
    expect(vm.approveCommand.canExecute()).toBe(false);
    vm.draft = { ...vm.draft, title: "Good" };
    expect(vm.approveCommand.canExecute()).toBe(true);
  });

  it("deny reverts the draft to snapshot", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ title: "Original" }));
    vm.draft = { ...vm.draft, title: "Stale edit" };
    expect(vm.isDirty).toBe(true);
    vm.denyCommand.execute();
    expect(vm.draft.title).toBe("Original");
    expect(vm.isDirty).toBe(false);
  });

  it("addTagCommand adds the trimmed tag and clears tagDraft", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: [] }));
    vm.tagDraft = "  security  ";
    expect(vm.addTagCommand.canExecute()).toBe(true);
    vm.addTagCommand.execute();
    expect(vm.draft.tags).toEqual(["security"]);
    expect(vm.tagDraft).toBe("");
  });

  it("addTag is a no-op on duplicate (case-insensitive) tags", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: ["Security"] }));
    vm.tagDraft = "security";
    vm.addTagCommand.execute();
    expect(vm.draft.tags.length).toBe(1);
  });

  it("removeTagCommand removes the matching tag", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: ["a", "b"] }));
    vm.removeTagCommand.execute("a");
    expect(vm.draft.tags).toEqual(["b"]);
  });

  it("publishes a 'Saved' notification on approve", async () => {
    const { vm, notifs } = makeForm();
    const titles: string[] = [];
    notifs.pending.subscribe((list) => {
      for (const n of list) {
        if (!titles.includes(n.message)) titles.push(n.message);
        notifs.resolve(n, NotificationReaction.Approve);
      }
    });
    vm.bindTo(aNote({ title: "Hi" }));
    vm.draft = { ...vm.draft, title: "Saved title" };
    await vm.approveAsync();
    expect(titles.some((t) => t.includes("Saved title"))).toBe(true);
  });

  it("denyCommand is a no-op when no note is bound", () => {
    const { vm } = makeForm();
    expect(() => vm.denyCommand.execute()).not.toThrow();
  });

  it("draft setter is a no-op before bindTo", () => {
    const { vm } = makeForm();
    vm.draft = aNote({ title: "ghost" });
    expect(vm.draft.title).not.toBe("ghost");
  });

  it("isValid requires a non-empty title", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ title: "" }));
    expect(vm.isValid).toBe(false);
    expect(vm.titleError).toBe("Title is required.");
    vm.draft = { ...vm.draft, title: "Now valid" };
    expect(vm.isValid).toBe(true);
    expect(vm.titleError).toBeNull();
  });

  it("editor mode defaults to edit and switches through DiscriminatorVM", () => {
    const { vm } = makeForm();
    expect(vm.editorMode).toBe("edit");
    expect(vm.isEditMode).toBe(true);
    expect(vm.isPreviewMode).toBe(false);
    expect(vm.showEditModeCommand.canExecute()).toBe(false);
    expect(vm.showPreviewModeCommand.canExecute()).toBe(true);

    vm.showPreviewModeCommand.execute();

    expect(vm.editorMode).toBe("preview");
    expect(vm.isEditMode).toBe(false);
    expect(vm.isPreviewMode).toBe(true);
    expect(vm.showEditModeCommand.canExecute()).toBe(true);
    expect(vm.showPreviewModeCommand.canExecute()).toBe(false);

    vm.showEditModeCommand.execute();

    expect(vm.editorMode).toBe("edit");
    expect(vm.isEditMode).toBe(true);
  });

  it("builder validates required fields", () => {
    expect(() => NoteFormVM.builder().build()).toThrow();
  });

  it("dispose tears down cleanly", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote());
    expect(() => vm.dispose()).not.toThrow();
  });

  // ── Round-3 Important B-I2 parity: bindTo notifies bindings that the
  // denyCommand / approveCommand reference has changed.
  it("bindTo emits PropertyChangedMessage for approveCommand and denyCommand", async () => {
    const { vm, hub } = makeForm();
    const { PropertyChangedMessage } = await import("@thekaveh/vmx");
    const observed: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) {
        observed.push(m.propertyName);
      }
    });
    vm.bindTo(aNote());
    expect(observed).toContain("approveCommand");
    expect(observed).toContain("denyCommand");
  });

  it("tagsText renders the draft tags as a comma-joined string", () => {
    // Round-3 Important C-I1 parity: tagsText flattens the draft tag list
    // for UI labels (mirrors Py tags_text and C# TagsText).
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: ["alpha", "beta"] }));
    expect(vm.tagsText).toBe("alpha, beta");
  });

  // ── Round-4 Minor-2 (cross-flavor parity): tagsText must be in the
  // PropertyChanged emission list so consumers that subscribe specifically
  // to "tagsText" (e.g. a chip-strip label) receive notifications after
  // every draft mutation (add / remove tag). C# already emits for
  // TagsText; Py re-emits via the DerivedProperty's _self_subject.
  it("unbind clears the tagDraft buffer (R5 Minor parity)", () => {
    // The user-typed tag input buffer survived across binding transitions
    // before R5: delete-then-rebind left the orphan text in the chip input.
    // unbind now resets tagDraft alongside the form / bound model.
    // Cross-flavor parity with C# `TagDraft = string.Empty` and Python
    // `self._tag_draft = ""`.
    const { vm } = makeForm();
    vm.bindTo(aNote());
    vm.tagDraft = "secur";
    expect(vm.tagDraft).toBe("secur");

    vm.unbind();

    expect(vm.tagDraft).toBe("");
    expect(vm.hasBoundNote).toBe(false);
  });

  it("addTag / removeTag emit PropertyChanged for tagsText", async () => {
    const { vm, hub } = makeForm();
    const { PropertyChangedMessage } = await import("@thekaveh/vmx");
    vm.bindTo(aNote({ tags: [] }));
    const observed: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) {
        observed.push(m.propertyName);
      }
    });
    vm.tagDraft = "alpha";
    vm.addTagCommand.execute();
    expect(observed).toContain("tagsText");
    observed.length = 0;
    vm.removeTagCommand.execute("alpha");
    expect(observed).toContain("tagsText");
  });
});

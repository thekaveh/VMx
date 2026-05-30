import { describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "vmx";
import {
  NotificationHub,
  NotificationReaction,
  type INotificationHub,
} from "vmx/notifications";

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
    vm.draft = { ...vm.draft, title: "Now valid" };
    expect(vm.isValid).toBe(true);
  });

  it("builder validates required fields", () => {
    expect(() => NoteFormVM.builder().build()).toThrow();
  });

  it("dispose tears down cleanly", () => {
    const { vm } = makeForm();
    vm.bindTo(aNote());
    expect(() => vm.dispose()).not.toThrow();
  });
});

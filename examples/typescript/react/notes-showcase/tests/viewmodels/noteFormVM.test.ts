import { describe, expect, it } from "vitest";
import { FormVM, MessageHub, RxDispatcher, type IAsyncCommand } from "@thekaveh/vmx";
import {
  NotificationHub,
  NotificationReaction,
  type INotificationHub,
  type Notification,
} from "@thekaveh/vmx/notifications";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import type { NoteModel } from "../../src/models/noteModel.js";
import type { RepositorySnapshot } from "../../src/models/noteRepository.js";
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

/**
 * Holds every repository write until the test releases it, and counts the
 * snapshot reads that a post-save tag refresh makes.
 */
class GatedSaveRepository extends InMemoryNoteRepository {
  readonly saveCalls: NoteModel[] = [];
  loadAllCalls = 0;
  readonly #pending: Array<() => void> = [];

  override async loadAll(): Promise<RepositorySnapshot> {
    this.loadAllCalls += 1;
    return super.loadAll();
  }

  override async saveNote(note: NoteModel): Promise<void> {
    this.saveCalls.push(note);
    await new Promise<void>((resolve) => {
      this.#pending.push(resolve);
    });
    await super.saveNote(note);
  }

  releaseSaves(): void {
    for (const release of this.#pending.splice(0)) release();
  }
}

/** Records the message of every notification the hub receives, in order. */
function recordNotifications(hub: INotificationHub): string[] {
  const seen = new Set<Notification>();
  const messages: string[] = [];
  hub.pending.subscribe((list) => {
    for (const notification of list) {
      if (seen.has(notification)) continue;
      seen.add(notification);
      messages.push(notification.message);
    }
  });
  return messages;
}

/** A form over a gated repository, with its notifications recorded. */
function makeGatedForm(): {
  vm: NoteFormVM;
  hub: MessageHub;
  repo: GatedSaveRepository;
  notifications: string[];
} {
  const hub = new MessageHub();
  const repo = new GatedSaveRepository(buildSeed(), {
    saveNoteDelayMs: 0,
    loadAllDelayMs: 0,
    loadNotesDelayMs: 0,
  });
  const notifs = new NotificationHub();
  const notifications = recordNotifications(notifs);
  const vm = NoteFormVM.builder()
    .name("form")
    .services(hub, RxDispatcher.immediate())
    .repository(repo)
    .notificationHub(notifs)
    .build();
  vm.construct();
  return { vm, hub, repo, notifications };
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

  it("a double save while the repository save is pending persists once", async () => {
    // FormVM admits one approval at a time (spec 20 §5.3, ADR-0143). A second
    // save from the awaitable path or the bound command, made while the
    // repository is still writing, must not issue a second write, and must not
    // run the post-save steps for a save that did not happen.
    const { PropertyChangedMessage } = await import("@thekaveh/vmx");
    const { vm, hub, repo, notifications } = makeGatedForm();
    vm.bindTo(aNote({ title: "Original" }));
    vm.draft = { ...vm.draft, title: "Saved once" };
    const saved: NoteModel[] = [];
    vm.onSaved.subscribe((note) => saved.push(note));
    const vmChanges: string[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage && m.sender === vm) {
        vmChanges.push(m.propertyName);
      }
    });

    const first = vm.approveAsync();
    const second = vm.approveAsync();
    const viaCommand = (vm.approveCommand as IAsyncCommand).executeAsync();
    // Every save attempt reaches the repository synchronously, so a second
    // write would already be recorded here.
    expect(repo.saveCalls.map((note) => note.title)).toEqual(["Saved once"]);

    // The refused saves complete while the first write is still pending,
    // without any post-save step: no "Saved" notification, no draft
    // re-emission, and no tag refresh.
    await Promise.all([second, viaCommand]);
    expect(repo.saveCalls).toHaveLength(1);
    expect(vm.isDirty).toBe(true);
    expect(vm.snapshot.title).toBe("Original");
    expect(notifications).toEqual([]);
    expect(vmChanges).toEqual([]);
    expect(repo.loadAllCalls).toBe(0);
    expect(saved).toEqual([]);

    repo.releaseSaves();
    await first;

    expect(repo.saveCalls).toHaveLength(1);
    expect(saved.map((note) => note.title)).toEqual(["Saved once"]);
    expect(notifications).toEqual(["Saved “Saved once”"]);
    expect(repo.loadAllCalls).toBe(1);
    expect(vmChanges).toContain("snapshot");
    expect(vm.isDirty).toBe(false);
    expect(vm.snapshot.title).toBe("Saved once");
    const stored = (await repo.loadNotes("nb-work")).filter((note) => note.id === "note-99");
    expect(stored.map((note) => note.title)).toEqual(["Saved once"]);
    vm.dispose();
  });

  it("a second save posts 'Saved' only when it wrote, however late it lands", async () => {
    // `await` always yields, so a save refused while the first one is pending
    // resumes some microtasks later, possibly after the first save has
    // published. Land the second call at every microtask offset across the
    // first save's settlement: each repository write is followed by exactly
    // one "Saved" notification and one tag refresh, and a refused call by
    // neither.
    let refusedAfterRelease = 0;
    let admittedAfterSettle = 0;
    for (let ticks = 0; ticks <= 30; ticks++) {
      const { vm, repo, notifications } = makeGatedForm();
      vm.bindTo(aNote({ title: "Original" }));
      vm.draft = { ...vm.draft, title: "Saved" };

      const first = vm.approveAsync();
      repo.releaseSaves();
      for (let tick = 0; tick < ticks; tick++) await Promise.resolve();
      const second = vm.approveAsync();
      const writes = repo.saveCalls.length;
      // An admitted second save is gated like the first; release it too.
      repo.releaseSaves();
      await Promise.all([first, second]);

      if (writes === 1) refusedAfterRelease += 1;
      else admittedAfterSettle += 1;
      expect({ ticks, notifications }).toEqual({
        ticks,
        notifications: Array<string>(writes).fill("Saved “Saved”"),
      });
      expect({ ticks, refreshes: repo.loadAllCalls }).toEqual({ ticks, refreshes: writes });
      vm.dispose();
    }
    // The sweep covers both outcomes for the second call.
    expect(refusedAfterRelease).toBeGreaterThan(0);
    expect(admittedAfterSettle).toBeGreaterThan(0);
  });

  it("rebinding while a save is pending posts no 'Saved' for either note", async () => {
    // Rebinding disposes the pending save's form, which then publishes no
    // approval (spec 20 §5.3), so the save runs no post-save step.
    const { vm, repo, notifications } = makeGatedForm();
    vm.bindTo(aNote({ title: "Original" }));
    vm.draft = { ...vm.draft, title: "Edited" };
    const saved: NoteModel[] = [];
    vm.onSaved.subscribe((note) => saved.push(note));

    const pending = vm.approveAsync();
    vm.bindTo(aNote({ id: "note-98", title: "Next note" }));
    repo.releaseSaves();
    await pending;

    expect(repo.saveCalls.map((note) => note.title)).toEqual(["Edited"]);
    expect(saved).toEqual([]);
    expect(notifications).toEqual([]);
    expect(repo.loadAllCalls).toBe(0);
    expect(vm.snapshot.title).toBe("Next note");
    vm.dispose();
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

  it("tag suggestions filter the workspace tag catalog through SearchableState", async () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: [] }));
    await vm.refreshTagSuggestionsAsync();

    vm.tagDraft = "sec";

    expect(vm.tagSuggestions).toEqual(["security"]);
    expect(vm.tagSuggestionsText).toBe("security");
  });

  it("tag suggestions omit tags already on the draft", async () => {
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: ["security"] }));
    await vm.refreshTagSuggestionsAsync();

    vm.tagDraft = "sec";

    expect(vm.tagSuggestions).toEqual([]);
    expect(vm.tagSuggestionsText).toBe("");
  });

  it("tag suggestions deduplicate mixed-case catalog entries", async () => {
    const { vm, repo } = makeForm();
    await repo.saveNote(aNote({ id: "mixed-tags", tags: ["Security", "security"] }));
    vm.bindTo(aNote({ tags: [] }));
    await vm.refreshTagSuggestionsAsync();

    vm.tagDraft = "sec";

    expect(vm.tagSuggestions).toEqual(["security"]);
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

  // ── stable-command rebinding: bindTo notifies bindings that the
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
    // flattened tag binding: tagsText flattens the draft tag list
    // for UI labels (mirrors Py tags_text and C# TagsText).
    const { vm } = makeForm();
    vm.bindTo(aNote({ tags: ["alpha", "beta"] }));
    expect(vm.tagsText).toBe("alpha, beta");
  });

  // ── derived-tag notification parity (cross-flavor parity): tagsText must be in the
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

describe("FormVM field names through the package build", () => {
  it("keeps a prototype-named field as data and leaks no inherited lookup", () => {
    const validators: Record<string, (note: NoteModel) => string | null> = {};
    Object.defineProperty(validators, "__proto__", {
      value: (note: NoteModel) => (note.title === "" ? "required" : null),
      enumerable: true,
    });
    const form = new FormVM<NoteModel>({
      initial: aNote({ title: "" }),
      persister: async () => {},
      validators,
    });

    expect(form.isValid).toBe(false);
    expect(form.fieldError("__proto__")).toBe("required");
    expect(form.fieldError("toString")).toBeUndefined();
    expect(form.approveCommand.canExecute()).toBe(false);
  });
});

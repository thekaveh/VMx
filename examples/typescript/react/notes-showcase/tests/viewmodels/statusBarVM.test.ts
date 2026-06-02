import { describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "@thekaveh/vmx";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { NoteFormVM } from "../../src/viewmodels/noteFormVM.js";
import { NotebooksRootVM } from "../../src/viewmodels/notebooksRootVM.js";
import { NotesViewVM } from "../../src/viewmodels/notesViewVM.js";
import { StatusBarVM } from "../../src/viewmodels/statusBarVM.js";

async function makeStack(): Promise<{
  bar: StatusBarVM;
  notes: NotesViewVM;
  form: NoteFormVM;
  root: NotebooksRootVM;
}> {
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();
  const repo = new InMemoryNoteRepository(buildSeed(), {
    loadAllDelayMs: 0,
    loadNotesDelayMs: 0,
    saveNoteDelayMs: 0,
  });
  const root = NotebooksRootVM.builder()
    .name("nb-root")
    .services(hub, dispatcher)
    .repository(repo)
    .build();
  root.construct();
  await root.populateAsync();

  const notes = NotesViewVM.builder()
    .name("notes")
    .services(hub, dispatcher)
    .repository(repo)
    .pageSize(5)
    .searchDebounceMs(0)
    .build();
  notes.construct();

  const form = NoteFormVM.builder()
    .name("form")
    .services(hub, dispatcher)
    .repository(repo)
    .build();
  form.construct();

  const bar = StatusBarVM.builder()
    .name("status")
    .services(hub, dispatcher)
    .notesView(notes)
    .notebooks(root)
    .noteForm(form)
    .build();
  bar.construct();
  return { bar, notes, form, root };
}

describe("StatusBarVM", () => {
  it("noteCountText reflects 0 by default", async () => {
    const { bar } = await makeStack();
    expect(bar.noteCountText.value).toBe("0 notes");
  });

  it("noteCountText updates after bindToAsync", async () => {
    const { bar, notes } = await makeStack();
    await notes.bindToAsync("nb-reviews");
    expect(bar.noteCountText.value).toBe("7 notes");
  });

  it("singular form when 1 note", async () => {
    const { bar, notes } = await makeStack();
    await notes.bindToAsync("nb-specs"); // 1 note
    expect(bar.noteCountText.value).toBe("1 note");
  });

  it("starredText counts starred items", async () => {
    const { bar, notes } = await makeStack();
    await notes.bindToAsync("nb-reviews"); // 2 starred
    expect(bar.starredText.value).toBe("2 starred");
  });

  it("editingText is 'No selection' before bindTo", async () => {
    const { bar } = await makeStack();
    expect(bar.editingText.value).toBe("No selection");
  });

  it("editingText shows the bound title", async () => {
    const { bar, form } = await makeStack();
    form.bindTo({
      id: "x",
      notebookId: "nb-work",
      title: "Hello",
      tags: [],
      body: "",
      starred: false,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    expect(bar.editingText.value).toBe("Editing: Hello");
    form.draft = { ...form.draft, title: "Hello edited" };
    expect(bar.editingText.value).toBe("Editing: Hello edited *");
  });

  it("equality-guarded — repeat emissions don't fire valueChanged", async () => {
    const { bar, notes } = await makeStack();
    await notes.bindToAsync("nb-reviews");
    const seen: string[] = [];
    bar.noteCountText.valueChanged.subscribe((v) => seen.push(v));
    // Same notebook — same count, same string. Should NOT emit.
    await notes.bindToAsync("nb-reviews");
    expect(seen.length).toBe(0);
  });

  it("notebooks accessor returns the source NotebooksRootVM", async () => {
    const { bar, root } = await makeStack();
    expect(bar.notebooks).toBe(root);
  });

  it("dispose tears down cleanly", async () => {
    const { bar } = await makeStack();
    expect(() => bar.dispose()).not.toThrow();
  });

  it("builder validates required fields", () => {
    expect(() => StatusBarVM.builder().build()).toThrow();
  });
});

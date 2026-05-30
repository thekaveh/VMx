/**
 * App smoke tests (Phase 5.c).
 *
 * Mirrors:
 *   - `examples/csharp/avalonia/NotesShowcase.Tests/SmokeTests.cs`.
 *   - `examples/python/textual/notes_showcase/tests/views/test_smoke.py`.
 *
 * Asserts the headless end-to-end wiring:
 *   1. Four root notebooks appear after `constructAsync()`.
 *   2. Typing in the title input flips `noteForm.isDirty` true and enables
 *      the Save button — the §6.1 two-way binding gap fix from Phase 5.a/5.b.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "../../src/views/App.js";
import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { ReactDialogService } from "../../src/views/adapter/ReactDialogService.js";
import { WorkspaceVM } from "../../src/viewmodels/workspaceVM.js";

afterEach(() => {
  cleanup();
});

function buildWorkspace(): {
  workspace: WorkspaceVM;
  dialog: ReactDialogService;
} {
  const repo = new InMemoryNoteRepository(buildSeed(), {
    // Zero out delays so tests don't depend on real timers; the showcase's
    // default 300/150-ms delays are demo-only (see `inMemoryRepository.ts`).
    loadAllDelayMs: 0,
    loadNotesDelayMs: 0,
    saveNoteDelayMs: 0,
    deleteNoteDelayMs: 0,
    addNotebookDelayMs: 0,
    exportDelayMs: 0,
  });
  const dialog = new ReactDialogService();
  const workspace = WorkspaceVM.builder()
    .name("workspace")
    .repository(repo)
    .dialogService(dialog)
    .build();
  return { workspace, dialog };
}

describe("App smoke", () => {
  it("renders four root notebooks after constructAsync", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();

    render(<App workspace={workspace} dialog={dialog} />);

    // Top-level notebooks live as <li role="treeitem"> children of the
    // <ul role="tree">. The `aria-level` filter requires axe-style parsing
    // that jsdom's testing-library doesn't ship, so query directly.
    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    const rootItems = within(tree).getAllByRole("treeitem")
      .filter((el) => el.parentElement === tree);
    expect(rootItems).toHaveLength(4);
  });

  it("editing a note title flips dirty and enables Save", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();

    render(<App workspace={workspace} dialog={dialog} />);

    // Pick the first visible note from the notes list and click it.
    const notesList = await screen.findByRole("listbox", { name: /notes/i });
    const firstNote = within(notesList).getAllByRole("option")[0];
    expect(firstNote).toBeDefined();
    fireEvent.click(firstNote as HTMLElement);

    // The form should now show a Title input and a Save button.
    // Note: there's another "Save" button in the capability-actions row,
    // so we scope the lookup to the form's button row by its DOM role.
    const titleInput = await screen.findByLabelText("Title");
    const form = (titleInput as HTMLInputElement).closest("form");
    expect(form).not.toBeNull();
    const saveButton = within(form as HTMLFormElement).getByRole("button", {
      name: "Save",
    });
    expect((saveButton as HTMLButtonElement).disabled).toBe(true);

    // Type a new character — Save should become enabled and the VM dirty.
    fireEvent.change(titleInput, {
      target: { value: `${(titleInput as HTMLInputElement).value} edited` },
    });

    expect(workspace.noteForm.isDirty).toBe(true);
    expect((saveButton as HTMLButtonElement).disabled).toBe(false);
  });
});

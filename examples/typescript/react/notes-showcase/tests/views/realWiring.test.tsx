/**
 * Real-wiring regression tests — the golden path through actual DOM events.
 *
 * The pass-6 real-wiring audit found the React showcase broken at several
 * view/VM seams in ways the VM-level suite masked (tests called VM methods
 * directly and asserted VM state). These tests fire DOM events and assert
 * rendered DOM, so a regression in the wiring fails here even when every
 * VM-level test stays green.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

async function selectFirstNote(): Promise<HTMLInputElement> {
  const notesList = await screen.findByRole("listbox", { name: /notes/i });
  const firstNote = within(notesList).getAllByRole("option")[0];
  fireEvent.click(firstNote as HTMLElement);
  return (await screen.findByLabelText("Title")) as HTMLInputElement;
}

describe("real wiring", () => {
  it("Revert click restores the rendered title (stable deny command)", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const titleInput = await selectFirstNote();
    const original = titleInput.value;
    fireEvent.change(titleInput, { target: { value: "Discard me" } });
    expect(workspace.noteForm.isDirty).toBe(true);

    const form = titleInput.closest("form") as HTMLFormElement;
    fireEvent.click(within(form).getByRole("button", { name: "Revert" }));

    // The DOM (not just the VM) must show the reverted value.
    await waitFor(() => {
      expect(
        (screen.getByLabelText("Title") as HTMLInputElement).value,
      ).toBe(original);
    });
    expect(workspace.noteForm.isDirty).toBe(false);
  });

  it("Save click refreshes the list row label", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const titleInput = await selectFirstNote();
    fireEvent.change(titleInput, { target: { value: "Retitled by test" } });
    const form = titleInput.closest("form") as HTMLFormElement;
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    const notesList = await screen.findByRole("listbox", { name: /notes/i });
    await waitFor(() => {
      expect(
        within(notesList)
          .getAllByRole("option")
          .some((el) => el.textContent?.includes("Retitled by test")),
      ).toBe(true);
    });
  });

  it("+ Notebook click renders the new notebook in the tree", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    const before = within(tree)
      .getAllByRole("treeitem")
      .filter((el) => el.parentElement === tree).length;

    fireEvent.click(screen.getByRole("button", { name: "+ Notebook" }));

    await waitFor(() => {
      const after = within(tree)
        .getAllByRole("treeitem")
        .filter((el) => el.parentElement === tree).length;
      expect(after).toBe(before + 1);
    });
  });

  it("selecting another notebook rebinds the notes list", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const firstId = workspace.notesView.boundNotebookId;
    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    const rootItems = within(tree)
      .getAllByRole("treeitem")
      .filter((el) => el.parentElement === tree);
    // Click the second root notebook's label row.
    const target = rootItems[1] as HTMLElement;
    fireEvent.click(within(target).getByText(/.+/));

    await waitFor(() => {
      expect(workspace.notesView.boundNotebookId).not.toBe(firstId);
    });
    expect(workspace.notebooksRoot.current?.model.id).toBe(
      workspace.notesView.boundNotebookId,
    );
  });

  it("pagination buttons disable on the only page", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);
    await screen.findByRole("listbox", { name: /notes/i });

    // Seeded "Work" notebook fits on one page (pageSize 5) — every move
    // command must render disabled (the mirror was previously vacuous).
    for (const name of ["First page", "Previous page", "Next page", "Last page"]) {
      const btn = screen.getByRole("button", { name });
      expect((btn as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("capability-bar Save and Close act on the focused note", async () => {
    // Spy on the repo so the Save assertion pins the onSave wiring (a
    // reverted handler must fail this, not just the Close half).
    const repo = new InMemoryNoteRepository(buildSeed(), {
      loadAllDelayMs: 0,
      loadNotesDelayMs: 0,
      saveNoteDelayMs: 0,
      deleteNoteDelayMs: 0,
      addNotebookDelayMs: 0,
      exportDelayMs: 0,
    });
    let saveCalls = 0;
    const originalSave = repo.saveNote.bind(repo);
    repo.saveNote = async (note) => {
      saveCalls += 1;
      await originalSave(note);
    };
    const dialog = new ReactDialogService();
    const workspace = WorkspaceVM.builder()
      .name("workspace")
      .repository(repo)
      .dialogService(dialog)
      .build();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    await selectFirstNote();
    const current = workspace.notesView.current;
    expect(current).not.toBeNull();

    const bar = await screen.findByRole("toolbar", { name: /actions/i });
    fireEvent.click(within(bar).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(saveCalls).toBeGreaterThan(0);
    });
    // Close clears the selection → editor unbinds.
    fireEvent.click(within(bar).getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(workspace.notesView.current).toBeNull();
    });
    expect(workspace.noteForm.hasBoundNote).toBe(false);
  });
});

/**
 * Keyboard shortcuts of the Notes Workspace (the `useHotkeys` map in Layout).
 *
 * Each documented binding must run its command when its combination reaches
 * `window`. The new-note and new-notebook bindings use Alt, so they avoid the
 * combinations that Chromium reserves on Windows and Linux. Alt also changes
 * `KeyboardEvent.key` on macOS, so those bindings match `KeyboardEvent.code`.
 *
 * The matcher accepts `ctrlKey` or `metaKey` as Mod on every platform, so
 * these tests do not depend on the platform.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "../../../src/views/App.js";
import { InMemoryNoteRepository } from "../../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../../src/models/seed.js";
import { ReactDialogService } from "../../../src/views/adapter/ReactDialogService.js";
import { WorkspaceVM } from "../../../src/viewmodels/workspaceVM.js";

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

function untitledRows(notesList: HTMLElement): number {
  return within(notesList).queryAllByRole("option", { name: /Untitled/ }).length;
}

function rootNotebooks(tree: HTMLElement): number {
  return within(tree)
    .getAllByRole("treeitem")
    .filter((el) => el.parentElement === tree).length;
}

// Gives an async command time to finish, so a negative assertion means
// "did not run" rather than "has not run yet".
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

describe("Notes Workspace keyboard shortcuts", () => {
  it("Ctrl+Alt+N runs new note", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const notesList = await screen.findByRole("listbox", { name: /notes/i });
    const button = screen.getByRole("button", { name: "+ Note" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(untitledRows(notesList)).toBe(0);

    fireEvent.keyDown(window, { key: "n", code: "KeyN", ctrlKey: true, altKey: true });

    await waitFor(() => expect(untitledRows(notesList)).toBe(1));
  });

  it("Cmd+Option+N runs new note when Option changes the key value", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const notesList = await screen.findByRole("listbox", { name: /notes/i });
    const button = screen.getByRole("button", { name: "+ Note" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));

    // macOS: Option produces a dead-key character in `key`, but `code` stays KeyN.
    fireEvent.keyDown(window, { key: "˜", code: "KeyN", metaKey: true, altKey: true });

    await waitFor(() => expect(untitledRows(notesList)).toBe(1));
  });

  it("Ctrl+Alt+Shift+N runs new notebook", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    const button = screen.getByRole("button", { name: "+ Notebook" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    const before = rootNotebooks(tree);

    fireEvent.keyDown(window, { key: "N", code: "KeyN", ctrlKey: true, altKey: true, shiftKey: true });

    await waitFor(() => expect(rootNotebooks(tree)).toBe(before + 1));
  });

  it("Cmd+Option+Shift+N runs new notebook when Option changes the key value", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    const button = screen.getByRole("button", { name: "+ Notebook" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    const before = rootNotebooks(tree);

    // The key value is a stand-in for whatever Option + Shift produces.
    fireEvent.keyDown(window, { key: "˝", code: "KeyN", metaKey: true, altKey: true, shiftKey: true });

    await waitFor(() => expect(rootNotebooks(tree)).toBe(before + 1));
  });

  it("Mod+E opens the export dialog", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const exportButton = screen.getByRole("button", { name: "Export…" }) as HTMLButtonElement;
    await waitFor(() => expect(exportButton.disabled).toBe(false));

    fireEvent.keyDown(window, { key: "e", ctrlKey: true });

    expect(await screen.findByLabelText("Filename")).toBeTruthy();
  });

  it("Mod+S saves the current note", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const titleInput = await selectFirstNote();
    fireEvent.change(titleInput, { target: { value: "Hotkey title" } });
    const form = titleInput.closest("form") as HTMLFormElement;
    const save = within(form).getByRole("button", { name: "Save" }) as HTMLButtonElement;
    await waitFor(() => expect(save.disabled).toBe(false));

    fireEvent.keyDown(window, { key: "s", ctrlKey: true });

    expect(await screen.findByText(/Saved “Hotkey title”/)).toBeTruthy();
  });

  it("Ctrl+N and Cmd+N no longer run new note", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const notesList = await screen.findByRole("listbox", { name: /notes/i });
    const button = screen.getByRole("button", { name: "+ Note" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));

    fireEvent.keyDown(window, { key: "n", code: "KeyN", ctrlKey: true });
    await settle();
    fireEvent.keyDown(window, { key: "n", code: "KeyN", metaKey: true });
    await settle();

    expect(untitledRows(notesList)).toBe(0);
  });

  it("Ctrl+Shift+N and Cmd+Shift+N no longer run new notebook", async () => {
    const { workspace, dialog } = buildWorkspace();
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    const button = screen.getByRole("button", { name: "+ Notebook" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    const before = rootNotebooks(tree);

    fireEvent.keyDown(window, { key: "N", code: "KeyN", ctrlKey: true, shiftKey: true });
    await settle();
    fireEvent.keyDown(window, { key: "N", code: "KeyN", metaKey: true, shiftKey: true });
    await settle();

    expect(rootNotebooks(tree)).toBe(before);
  });
});

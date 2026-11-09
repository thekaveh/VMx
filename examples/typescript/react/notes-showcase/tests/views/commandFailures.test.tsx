/**
 * Command-failure wiring (#1394).
 *
 * `AsyncRelayCommand.execute()` sends a rejected task to the command's
 * `errors` channel. The toolbar binds that channel through `useCommand`'s
 * `onError`, so a failed New note shows an error toast instead of failing
 * silently.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "../../src/views/App.js";
import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import type { NoteModel } from "../../src/models/noteModel.js";
import { buildSeed } from "../../src/models/seed.js";
import { ReactDialogService } from "../../src/views/adapter/ReactDialogService.js";
import { WorkspaceVM } from "../../src/viewmodels/workspaceVM.js";

afterEach(() => {
  cleanup();
});

class FullDiskRepository extends InMemoryNoteRepository {
  override async saveNote(_note: NoteModel): Promise<void> {
    throw new Error("disk full");
  }
}

describe("command failures", () => {
  it("a failed New note shows an error toast", async () => {
    const repo = new FullDiskRepository(buildSeed(), {
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
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    const newNote = screen.getByRole("button", { name: "+ Note" }) as HTMLButtonElement;
    await waitFor(() => { expect(newNote.disabled).toBe(false); });
    fireEvent.click(newNote);

    const toasts = screen.getByRole("status", { name: "Notifications" });
    await waitFor(() => {
      expect(within(toasts).getByText("New note failed: disk full")).toBeTruthy();
    });
  });
});

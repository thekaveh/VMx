import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildSeed } from "../../../src/models/seed.js";
import { InMemoryNoteRepository } from "../../../src/models/inMemoryRepository.js";
import { App } from "../../../src/views/App.js";
import { ReactDialogService } from "../../../src/views/adapter/ReactDialogService.js";
import { WorkspaceVM } from "../../../src/viewmodels/workspaceVM.js";
import type { NotebookVM } from "../../../src/viewmodels/notebookVM.js";

afterEach(() => {
  cleanup();
});

async function renderWorkspace(): Promise<WorkspaceVM> {
  const repository = new InMemoryNoteRepository(buildSeed(), {
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
    .repository(repository)
    .dialogService(dialog)
    .build();
  await workspace.constructAsync();
  render(<App workspace={workspace} dialog={dialog} />);
  return workspace;
}

function notebook(ws: WorkspaceVM, id: string): NotebookVM {
  const nb = ws.notebooksRoot.all.find((candidate) => candidate.model.id === id);
  if (nb === undefined) throw new Error(`missing notebook ${id}`);
  return nb;
}

describe("NotebooksTree selection", () => {
  it("collapsing the current notebook keeps it selected without reloading notes", async () => {
    const ws = await renderWorkspace();
    const work = notebook(ws, "nb-work");
    act(() => {
      ws.selectNotebook(work);
      work.expand();
    });
    const select = vi.spyOn(ws, "selectNotebook");
    const bind = vi.spyOn(ws.notesView, "bindToAsync");

    fireEvent.click(await screen.findByRole("button", { name: "Collapse Work" }));

    expect(work.isExpanded).toBe(false);
    expect(ws.notebooksRoot.current).toBe(work);
    expect(select).not.toHaveBeenCalled();
    expect(bind).not.toHaveBeenCalled();
  });

  it("collapsing an ancestor of the current notebook selects the ancestor", async () => {
    const ws = await renderWorkspace();
    const work = notebook(ws, "nb-work");
    const specs = notebook(ws, "nb-specs");
    act(() => {
      work.expand();
      ws.selectNotebook(specs);
    });
    const select = vi.spyOn(ws, "selectNotebook");

    fireEvent.click(await screen.findByRole("button", { name: "Collapse Work" }));

    expect(select).toHaveBeenCalledTimes(1);
    expect(ws.notebooksRoot.current).toBe(work);
  });
});

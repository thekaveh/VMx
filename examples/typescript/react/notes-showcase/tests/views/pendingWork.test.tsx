/**
 * Real-UI regressions for work that is still pending when the user moves on:
 * a save in flight across a note switch, a global search overtaken by typing,
 * the Export… download, and keyboard / active-descendant state of the notes
 * listbox when the current note is not on the page.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWorkspace } from "../../src/composition.js";
import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { ReactDialogService } from "../../src/views/adapter/ReactDialogService.js";
import { App } from "../../src/views/App.js";
import { WorkspaceVM } from "../../src/viewmodels/workspaceVM.js";

const ZERO = {
  loadAllDelayMs: 0,
  loadNotesDelayMs: 0,
  saveNoteDelayMs: 0,
  deleteNoteDelayMs: 0,
  addNotebookDelayMs: 0,
  exportDelayMs: 0,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function mount(delays: Partial<typeof ZERO> = {}): Promise<{
  workspace: WorkspaceVM;
  repo: InMemoryNoteRepository;
}> {
  const repo = new InMemoryNoteRepository(buildSeed(), { ...ZERO, ...delays });
  const dialog = new ReactDialogService();
  const workspace = WorkspaceVM.builder()
    .name("workspace")
    .repository(repo)
    .dialogService(dialog)
    .build();
  await workspace.constructAsync();
  render(<App workspace={workspace} dialog={dialog} />);
  return { workspace, repo };
}

function noteRows(): HTMLElement[] {
  return within(screen.getByRole("listbox", { name: "Notes" })).getAllByRole("option");
}

describe("pending work survives the user moving on", () => {
  it("a save still in flight when another note is selected completes its effects", async () => {
    const { workspace, repo } = await mount({ saveNoteDelayMs: 40 });
    await screen.findByRole("listbox", { name: "Notes" });

    fireEvent.click(noteRows()[0] as HTMLElement);
    const title = (await screen.findByLabelText("Title")) as HTMLInputElement;
    expect(title.value).toBe("Standup notes");
    fireEvent.change(title, { target: { value: "Renamed mid-save" } });
    const form = title.closest("form") as HTMLFormElement;
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    // Switch before the repository save resolves; the new note binds at once.
    fireEvent.click(noteRows()[1] as HTMLElement);
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Roadmap snapshot");

    // The saved row, the NoteVM model, and the toast all catch up.
    await waitFor(() => {
      expect(noteRows()[0]?.textContent).toContain("Renamed mid-save");
    });
    const saved = workspace.notesView.visibleItems[0];
    expect(saved?.model.title).toBe("Renamed mid-save");
    await screen.findByText("Saved “Renamed mid-save”");
    expect((await repo.loadAll()).notes.find((n) => n.id === "note-08")?.title).toBe(
      "Renamed mid-save",
    );
    // The editor still shows the note the user switched to.
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Roadmap snapshot");

    // Returning to the saved note edits the saved title, not the stale one.
    fireEvent.click(noteRows()[0] as HTMLElement);
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Renamed mid-save");
  });

  it("returning to a note during its save shows and keeps the saved values (#761)", async () => {
    const { repo } = await mount({ saveNoteDelayMs: 40 });
    await screen.findByRole("listbox", { name: "Notes" });

    fireEvent.click(noteRows()[0] as HTMLElement);
    const title = (await screen.findByLabelText("Title")) as HTMLInputElement;
    expect(title.value).toBe("Standup notes");
    fireEvent.change(title, { target: { value: "Renamed" } });
    fireEvent.click(within(title.closest("form") as HTMLFormElement).getByRole("button", { name: "Save" }));

    // Leave and return before the repository save resolves.
    fireEvent.click(noteRows()[1] as HTMLElement);
    fireEvent.click(noteRows()[0] as HTMLElement);

    // When the save settles, the clean editor shows the saved title.
    await waitFor(() => {
      expect(noteRows()[0]?.textContent).toContain("Renamed");
    });
    await waitFor(() => {
      expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Renamed");
    });

    // A later save keeps the saved title instead of writing the old one back.
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Body after rename" } });
    const form = screen.getByLabelText("Title").closest("form") as HTMLFormElement;
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(async () => {
      const stored = (await repo.loadAll()).notes.find((n) => n.id === "note-08");
      expect(stored?.body).toBe("Body after rename");
      expect(stored?.title).toBe("Renamed");
    });
  });

  it("a save that settles after the user returned and edited keeps the unsaved edits (#761)", async () => {
    await mount({ saveNoteDelayMs: 40 });
    await screen.findByRole("listbox", { name: "Notes" });

    fireEvent.click(noteRows()[0] as HTMLElement);
    const title = (await screen.findByLabelText("Title")) as HTMLInputElement;
    fireEvent.change(title, { target: { value: "Renamed" } });
    fireEvent.click(within(title.closest("form") as HTMLFormElement).getByRole("button", { name: "Save" }));

    // Return to the note mid-save and edit it before the save settles.
    fireEvent.click(noteRows()[1] as HTMLElement);
    fireEvent.click(noteRows()[0] as HTMLElement);
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Unsaved body" } });

    await waitFor(() => {
      expect(noteRows()[0]?.textContent).toContain("Renamed");
    });
    await screen.findByText("Saved “Renamed”");

    // The settle does not clobber the unsaved edit.
    expect((screen.getByLabelText("Body") as HTMLTextAreaElement).value).toBe("Unsaved body");
    const form = screen.getByLabelText("Title").closest("form") as HTMLFormElement;
    expect((within(form).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("global search shows the latest term after typing over an in-flight search", async () => {
    const { workspace } = await mount({ loadNotesDelayMs: 30 });
    const input = screen.getByRole("searchbox", { name: "Search all notes" });

    // "Q" starts a fetch; "Travel" arrives while it is still in flight.
    fireEvent.change(input, { target: { value: "Q" } });
    fireEvent.change(input, { target: { value: "Travel" } });

    const results = screen.getByRole("list", { name: "Global search results" });
    await waitFor(() => {
      expect(within(results).queryAllByRole("listitem").map((li) => li.firstChild?.textContent))
        .toEqual(["Travel ideas"]);
    });
    await waitFor(() => {
      expect(workspace.globalSearch.refreshCommand.isExecuting).toBe(false);
    });
    expect(within(results).getAllByRole("listitem")).toHaveLength(1);
  });

  it("Export… saves the workspace as a browser download", async () => {
    const blobs: Blob[] = [];
    const createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return "blob:notes-export";
    });
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });

    const { workspace, dialog } = createWorkspace(ZERO);
    await workspace.constructAsync();
    render(<App workspace={workspace} dialog={dialog} />);

    fireEvent.click(screen.getByRole("button", { name: "Export…" }));
    const filename = (await screen.findByLabelText("Filename")) as HTMLInputElement;
    fireEvent.submit(filename.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(downloads).toEqual(["notes-export.json"]);
    });
    expect(blobs).toHaveLength(1);
    const payload = JSON.parse(await (blobs[0] as Blob).text()) as {
      notes: { title: string }[];
    };
    expect(payload.notes.map((n) => n.title)).toContain("Travel ideas");
    await waitFor(() => {
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:notes-export");
    });
  });
});

describe("notes listbox with no current note on the page", () => {
  async function openReviews(): Promise<WorkspaceVM> {
    const { workspace } = await mount();
    const tree = await screen.findByRole("tree", { name: /notebooks/i });
    fireEvent.click(within(tree).getByText("Reviews"));
    await screen.findByText("Page 1 of 2");
    return workspace;
  }

  it("first ArrowDown with no selection selects row 1", async () => {
    const workspace = await openReviews();
    expect(workspace.notesView.current).toBeNull();

    fireEvent.keyDown(screen.getByRole("listbox", { name: "Notes" }), { key: "ArrowDown" });

    expect(workspace.notesView.current?.model.title).toBe("Q1 design review");
    expect(noteRows()[0]?.getAttribute("aria-selected")).toBe("true");
  });

  it("aria-activedescendant names only a rendered row", async () => {
    await openReviews();
    const listbox = screen.getByRole("listbox", { name: "Notes" });
    fireEvent.click(noteRows()[0] as HTMLElement);
    const active = listbox.getAttribute("aria-activedescendant");
    expect(active).not.toBeNull();
    expect(document.getElementById(active as string)).not.toBeNull();

    // The current note is now on the other page.
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Page 2 of 2")).toBeTruthy();
    const offPage = listbox.getAttribute("aria-activedescendant");
    if (offPage !== null) expect(document.getElementById(offPage)).not.toBeNull();
    expect(offPage).toBeNull();
  });
});

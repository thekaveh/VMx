import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it } from "vitest";

import { buildSeed } from "../../../src/models/seed.js";
import { InMemoryNoteRepository } from "../../../src/models/inMemoryRepository.js";
import { App } from "../../../src/views/App.js";
import { ReactDialogService } from "../../../src/views/adapter/ReactDialogService.js";
import { WorkspaceVM } from "../../../src/viewmodels/workspaceVM.js";

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

describe("composite widget keyboard accessibility", () => {
  it("keeps focus on the tree and supports standard visible-node navigation", async () => {
    await renderWorkspace();
    const tree = await screen.findByRole("tree", { name: "Notebooks" });
    tree.focus();
    expect(document.activeElement).toBe(tree);
    expect(tree.tabIndex).toBe(0);
    expect(within(tree).getAllByRole("treeitem").every((item) => item.tabIndex < 0)).toBe(true);

    const expandable = within(tree).getAllByRole("treeitem").find(
      (item) => item.getAttribute("aria-expanded") === "false",
    );
    expect(expandable).toBeDefined();
    fireEvent.click((expandable as HTMLElement).querySelector(".notebooks-tree-node") as HTMLElement);
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    expect(expandable?.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    const selected = within(expandable as HTMLElement).getAllByRole("treeitem").find(
      (item) => item.getAttribute("aria-selected") === "true",
    );
    expect(selected).toBeDefined();
    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(expandable?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(expandable?.getAttribute("aria-expanded")).toBe("false");
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    expect(expandable?.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    expect(within(tree).getAllByRole("treeitem")[1]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tree, { key: "ArrowUp" });
    expect(expandable?.getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(tree, { key: "End" });
    const visible = within(tree).getAllByRole("treeitem");
    expect(visible.at(-1)?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tree, { key: "Home" });
    expect(visible[0]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tree, { key: "ArrowUp" });
    fireEvent.keyDown(tree, { key: "Enter" });
    fireEvent.keyDown(tree, { key: " " });
    fireEvent.keyDown(tree, { key: "Unmapped" });
    expect(visible[0]?.getAttribute("aria-selected")).toBe("true");
  });

  it("uses one listbox tab stop and supports Home, End, Up, and Down", async () => {
    const workspace = await renderWorkspace();
    const list = await screen.findByRole("listbox", { name: "Notes" });
    const options = within(list).getAllByRole("option");
    list.focus();
    expect(document.activeElement).toBe(list);
    expect(options.every((option) => option.tabIndex < 0)).toBe(true);

    fireEvent.keyDown(list, { key: "End" });
    expect(options.at(-1)?.getAttribute("aria-selected")).toBe("true");
    expect(workspace.notesView.current?.noteId).toBe(options.at(-1)?.id.replace("note-", ""));
    fireEvent.keyDown(list, { key: "ArrowUp" });
    expect(options.at(-2)?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "Home" });
    expect(options[0]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "ArrowUp" });
    fireEvent.keyDown(list, { key: "Enter" });
    fireEvent.keyDown(list, { key: " " });
    fireEvent.keyDown(list, { key: "Unmapped" });
    expect(options[0]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(options[1]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "End" });
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(options.at(-1)?.getAttribute("aria-selected")).toBe("true");
  });

  it("has no automatically detectable serious accessibility violations", async () => {
    await renderWorkspace();
    const results = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical"))
      .toEqual([]);
  });
});

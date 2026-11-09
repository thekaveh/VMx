/**
 * ThemeControls — ADR-0201 §2.4 theme control strip.
 *
 * Each control runs one ThemeVM command: a button per preset runs
 * `setThemeCommand`, "HC" runs `toggleHighContrast`, and "A-" / "A+" run
 * `setFontScale` with the current factor minus or plus 0.1.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

describe("ThemeControls (ADR-0201 §2.4)", () => {
  it("renders one button per preset that runs setThemeCommand", async () => {
    const ws = await renderWorkspace();
    const strip = await screen.findByRole("group", { name: "Theme controls" });

    for (const preset of ws.theme.presets) {
      fireEvent.click(within(strip).getByRole("button", { name: preset.name }));
      expect(ws.theme.model.name).toBe(preset.name);
      expect(ws.theme.model.followsSystem).toBe(false);
    }
  });

  it("HC toggles high contrast", async () => {
    const ws = await renderWorkspace();
    const strip = await screen.findByRole("group", { name: "Theme controls" });
    const before = ws.theme.model.highContrast;

    const hc = within(strip).getByRole("button", { name: "Toggle high contrast" });
    expect(hc.textContent).toBe("HC");
    fireEvent.click(hc);
    expect(ws.theme.model.highContrast).toBe(!before);
    fireEvent.click(hc);
    expect(ws.theme.model.highContrast).toBe(before);
  });

  it("A+ and A- step the font scale by 0.1", async () => {
    const ws = await renderWorkspace();
    const strip = await screen.findByRole("group", { name: "Theme controls" });
    expect(ws.theme.model.fontScaleFactor).toBe(1.0);

    const increase = within(strip).getByRole("button", { name: "Increase font size" });
    const decrease = within(strip).getByRole("button", { name: "Decrease font size" });
    expect(increase.textContent).toBe("A+");
    expect(decrease.textContent).toBe("A-");

    fireEvent.click(increase);
    expect(ws.theme.model.fontScaleFactor).toBeCloseTo(1.1, 10);
    fireEvent.click(decrease);
    expect(ws.theme.model.fontScaleFactor).toBeCloseTo(1.0, 10);
    fireEvent.click(decrease);
    expect(ws.theme.model.fontScaleFactor).toBeCloseTo(0.9, 10);
  });

  it("ships no accent or follow-system control", async () => {
    await renderWorkspace();
    const strip = await screen.findByRole("group", { name: "Theme controls" });
    const labels = within(strip)
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent);
    expect(labels).toHaveLength(6);
    expect(labels.some((label) => /accent|system/i.test(label ?? ""))).toBe(false);
  });
});

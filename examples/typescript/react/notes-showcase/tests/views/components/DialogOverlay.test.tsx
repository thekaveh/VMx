import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReactDialogService } from "../../../src/views/adapter/ReactDialogService.js";
import { DialogOverlay } from "../../../src/views/components/DialogOverlay.js";

afterEach(cleanup);

function renderOverlay(service: ReactDialogService): HTMLElement {
  render(
    <>
      <main data-dialog-background><button type="button">Open</button></main>
      <DialogOverlay service={service} />
    </>,
  );
  return screen.getByRole("button", { name: "Open" });
}

describe("DialogOverlay accessibility", () => {
  it("traps focus, makes the background inert, and restores focus after Escape", async () => {
    const service = new ReactDialogService();
    const opener = renderOverlay(service);
    opener.focus();
    let result: Promise<boolean> | undefined;
    act(() => { result = service.confirm("Delete note?", "Confirm deletion"); });

    const dialog = await screen.findByRole("dialog", { name: "Confirm deletion" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const ok = screen.getByRole("button", { name: "OK" });
    await waitFor(() => expect(document.activeElement).toBe(cancel));
    const background = document.querySelector<HTMLElement>("[data-dialog-background]");
    expect((background as HTMLElement & { inert: boolean }).inert).toBe(true);
    expect(background?.getAttribute("aria-hidden")).toBe("true");

    ok.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(ok);

    fireEvent.keyDown(dialog, { key: "Escape" });
    await expect(result).resolves.toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(opener));
    expect((background as HTMLElement & { inert: boolean }).inert).toBe(false);
    expect(background?.hasAttribute("aria-hidden")).toBe(false);
  });

  it("focuses the filename and treats Escape as file cancellation", async () => {
    const service = new ReactDialogService();
    renderOverlay(service);
    let result: Promise<string | null> | undefined;
    act(() => { result = service.pickFileToSave(null, "Export", "notes.json"); });

    const input = await screen.findByLabelText("Filename");
    await waitFor(() => expect(document.activeElement).toBe(input));
    fireEvent.keyDown(input, { key: "Escape" });
    await expect(result).resolves.toBeNull();
  });

  it("dismisses an alert dialog with Escape", async () => {
    const service = new ReactDialogService();
    renderOverlay(service);
    let result: Promise<void> | undefined;
    act(() => { result = service.notify("Saved", "Done", "info"); });

    const dialog = await screen.findByRole("alertdialog", { name: "Done" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    await expect(result).resolves.toBeUndefined();
  });
});

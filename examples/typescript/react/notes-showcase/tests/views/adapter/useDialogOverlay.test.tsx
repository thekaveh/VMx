/**
 * useDialogOverlay — adapter tests (Phase 5.c).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { act, type JSX } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { ReactDialogService } from "../../../src/views/adapter/ReactDialogService.js";
import { useDialogOverlay } from "../../../src/views/adapter/useDialogOverlay.js";

afterEach(() => {
  cleanup();
});

function Probe({ svc }: { svc: ReactDialogService }): JSX.Element {
  const request = useDialogOverlay(svc);
  return <span data-testid="kind">{request === null ? "none" : request.kind}</span>;
}

describe("useDialogOverlay", () => {
  it("renders 'none' initially", () => {
    const svc = new ReactDialogService();
    render(<Probe svc={svc} />);
    expect(screen.getByTestId("kind").textContent).toBe("none");
  });

  it("re-renders on confirm() publication", () => {
    const svc = new ReactDialogService();
    render(<Probe svc={svc} />);
    act(() => {
      void svc.confirm("?");
    });
    expect(screen.getByTestId("kind").textContent).toBe("confirm");
  });

  it("re-renders to 'none' on close()", () => {
    const svc = new ReactDialogService();
    render(<Probe svc={svc} />);
    act(() => {
      void svc.pickFileToSave();
    });
    expect(screen.getByTestId("kind").textContent).toBe("saveFile");
    act(() => {
      svc.close();
    });
    expect(screen.getByTestId("kind").textContent).toBe("none");
  });

  it("unsubscribes on unmount", () => {
    const svc = new ReactDialogService();
    const { unmount } = render(<Probe svc={svc} />);
    unmount();
    act(() => {
      void svc.confirm("after-unmount");
    });
  });
});

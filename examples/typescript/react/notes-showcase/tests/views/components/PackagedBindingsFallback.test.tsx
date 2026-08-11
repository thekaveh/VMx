import { cleanup, render, screen } from "@testing-library/react";
import { NEVER } from "rxjs";
import { afterEach, describe, expect, it } from "vitest";
import { DerivedProperty } from "@thekaveh/vmx";

import { StatusBar } from "../../../src/views/components/StatusBar.js";
import type { WorkspaceVM } from "../../../src/viewmodels/workspaceVM.js";

afterEach(cleanup);

describe("packaged React binding fallbacks", () => {
  it("renders stable placeholders while derived properties are unseeded", () => {
    const statusBar = {
      noteCountText: new DerivedProperty<string>(NEVER),
      starredText: new DerivedProperty<string>(NEVER),
      editingText: new DerivedProperty<string>(NEVER),
    };
    const workspace = { statusBar } as unknown as WorkspaceVM;

    render(<StatusBar ws={workspace} />);

    expect(screen.getByText("0 notes")).toBeDefined();
    expect(screen.getByText("0 starred")).toBeDefined();
    expect(screen.getByText("No selection")).toBeDefined();
  });
});

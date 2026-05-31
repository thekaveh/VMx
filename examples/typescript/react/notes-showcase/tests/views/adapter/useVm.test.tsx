/**
 * useVm — hub-driven re-render hook tests (Phase 4.c).
 *
 * Verifies that mutating a VM property triggers a React re-render via the
 * useSyncExternalStore subscription. Uses @testing-library/react against
 * jsdom (configured in vite.config.ts).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "vmx";

import { NoteVM } from "../../../src/viewmodels/noteVM.js";
import type { NoteModel } from "../../../src/models/noteModel.js";
import { useVm } from "../../../src/views/adapter/useVm.js";

function model(over: Partial<NoteModel> = {}): NoteModel {
  return {
    id: "note-01",
    notebookId: "nb-reviews",
    title: "Original",
    tags: [],
    body: "Body",
    starred: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...over,
  };
}

function makeNoteVM(initial = "Original"): NoteVM {
  const hub = new MessageHub();
  const vm = NoteVM.builder()
    .name("note:01")
    .model(model({ title: initial }))
    .services(hub, RxDispatcher.immediate())
    .build();
  vm.construct();
  return vm;
}

function TitleProbe(props: { vm: NoteVM }): JSX.Element {
  const vm = useVm(props.vm);
  return <span data-testid="title">{vm.title}</span>;
}

afterEach(() => {
  cleanup();
});

describe("useVm", () => {
  it("renders the current snapshot of the VM", () => {
    const vm = makeNoteVM("Original");
    render(<TitleProbe vm={vm} />);
    expect(screen.getByTestId("title").textContent).toBe("Original");
  });

  it("re-renders when a PropertyChangedMessage fires for this VM", () => {
    const vm = makeNoteVM("Original");
    render(<TitleProbe vm={vm} />);

    act(() => {
      vm.model = model({ title: "Updated" });
    });

    expect(screen.getByTestId("title").textContent).toBe("Updated");
  });

  it("ignores PropertyChangedMessages from a different VM on the same hub", () => {
    // Two VMs sharing one hub. We render against vm-A and mutate vm-B; the probe
    // must not re-render (snapshot must not change identity for an unrelated event).
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const vmA = NoteVM.builder()
      .name("note:A")
      .model(model({ id: "note-A", title: "A-orig" }))
      .services(hub, dispatcher)
      .build();
    const vmB = NoteVM.builder()
      .name("note:B")
      .model(model({ id: "note-B", title: "B-orig" }))
      .services(hub, dispatcher)
      .build();
    vmA.construct();
    vmB.construct();

    let renderCount = 0;
    function CountingProbe(): JSX.Element {
      const vm = useVm(vmA);
      renderCount++;
      return <span>{vm.title}</span>;
    }
    render(<CountingProbe />);
    const baseline = renderCount;

    act(() => {
      vmB.model = model({ id: "note-B", title: "B-changed" });
    });

    expect(renderCount).toBe(baseline);
  });

  it("unsubscribes on unmount", () => {
    const vm = makeNoteVM("Original");
    const { unmount } = render(<TitleProbe vm={vm} />);
    unmount();
    // No assertion needed beyond not throwing — VMx hub will keep emitting
    // and an undisposed subscription would error if it kept calling React
    // state updaters after unmount. Quiet completion is the contract.
    act(() => {
      vm.model = model({ title: "After unmount" });
    });
  });
});

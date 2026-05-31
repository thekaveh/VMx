/**
 * useVmCollection — CompositeVM → React array bridge tests (Phase 4.c).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { ComponentVM, CompositeVM, MessageHub, RxDispatcher } from "vmx";

import { useVmCollection } from "../../../src/views/adapter/useVmCollection.js";

function makeComposite(initial: number): {
  hub: MessageHub;
  dispatcher: ReturnType<typeof RxDispatcher.immediate>;
  composite: CompositeVM<ComponentVM>;
} {
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();
  const composite = CompositeVM.builder<ComponentVM>()
    .name("c")
    .services(hub, dispatcher)
    .children(() => {
      const out: ComponentVM[] = [];
      for (let i = 0; i < initial; i++) {
        out.push(
          ComponentVM.builder()
            .name(`child:${String(i)}`)
            .services(hub, dispatcher)
            .build(),
        );
      }
      return out;
    })
    .build();
  composite.construct();
  return { hub, dispatcher, composite };
}

function Probe(props: {
  composite: CompositeVM<ComponentVM>;
}): JSX.Element {
  const items = useVmCollection(props.composite);
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index} data-testid="row">
          {item.name}
        </li>
      ))}
    </ul>
  );
}

afterEach(() => {
  cleanup();
});

describe("useVmCollection", () => {
  it("returns the initial snapshot of items", () => {
    const { composite } = makeComposite(2);
    render(<Probe composite={composite} />);
    expect(screen.getAllByTestId("row")).toHaveLength(2);
  });

  it("re-renders with the new array on add", () => {
    const { composite, hub, dispatcher } = makeComposite(1);
    render(<Probe composite={composite} />);
    expect(screen.getAllByTestId("row")).toHaveLength(1);

    act(() => {
      const fresh = ComponentVM.builder()
        .name("child:new")
        .services(hub, dispatcher)
        .build();
      composite.add(fresh);
    });
    const rows = screen.getAllByTestId("row");
    expect(rows).toHaveLength(2);
    expect(rows[1]?.textContent).toBe("child:new");
  });

  it("re-renders on remove", () => {
    const { composite } = makeComposite(3);
    render(<Probe composite={composite} />);
    expect(screen.getAllByTestId("row")).toHaveLength(3);

    act(() => {
      composite.removeAt(1);
    });
    expect(screen.getAllByTestId("row")).toHaveLength(2);
  });

  it("re-renders on reset (clear)", () => {
    const { composite } = makeComposite(2);
    render(<Probe composite={composite} />);
    expect(screen.getAllByTestId("row")).toHaveLength(2);

    act(() => {
      composite.clear();
    });
    expect(screen.queryAllByTestId("row")).toHaveLength(0);
  });

  it("unsubscribes on unmount", () => {
    const { composite, hub, dispatcher } = makeComposite(1);
    const { unmount } = render(<Probe composite={composite} />);
    unmount();
    act(() => {
      composite.add(
        ComponentVM.builder()
          .name("after-unmount")
          .services(hub, dispatcher)
          .build(),
      );
    });
    // Quiet completion — see useVm test for the same assertion shape.
  });
});

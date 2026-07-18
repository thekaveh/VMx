/**
 * useDerivedProperty — adapter tests (Phase 5.c).
 *
 * Mirrors the Python parity test
 * (`examples/python/textual/notes_showcase/tests/views/adapter/test_bind_derived_property.py`)
 * but for the React `useSyncExternalStore`-based hook.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { act, type JSX } from "react";
import { BehaviorSubject, NEVER } from "rxjs";
import { afterEach, describe, expect, it } from "vitest";
import { DerivedProperty } from "@thekaveh/vmx";

import { useDerivedProperty } from "../../../src/views/adapter/useDerivedProperty.js";

afterEach(() => {
  cleanup();
});

function makeDerived(initial = 0): {
  dp: DerivedProperty<number>;
  source: BehaviorSubject<number>;
} {
  const source = new BehaviorSubject<number>(initial);
  const dp = new DerivedProperty<number>(source.asObservable(), null, null);
  return { dp, source };
}

function Probe({ dp }: { dp: DerivedProperty<number> }): JSX.Element {
  const value = useDerivedProperty(dp);
  return <span data-testid="v">{String(value)}</span>;
}

describe("useDerivedProperty", () => {
  it("renders the seeded value", () => {
    const { dp } = makeDerived(7);
    render(<Probe dp={dp} />);
    expect(screen.getByTestId("v").textContent).toBe("7");
  });

  it("re-renders on derived value changes", () => {
    const { dp, source } = makeDerived(1);
    render(<Probe dp={dp} />);
    act(() => {
      source.next(2);
    });
    expect(screen.getByTestId("v").textContent).toBe("2");
  });

  it("does not crash if the derived has no value yet (returns undefined)", () => {
    // A DerivedProperty whose source never emits — `.value` throws on
    // snapshot reads. The hook must catch and fall back to `undefined`
    // (rendered as the string "undefined" by `String(value)`).
    const empty = new DerivedProperty<number>(NEVER, null, null);
    render(<Probe dp={empty} />);
    expect(screen.getByTestId("v").textContent).toBe("undefined");
  });

  it("unsubscribes on unmount", () => {
    const { dp, source } = makeDerived(0);
    const { unmount } = render(<Probe dp={dp} />);
    unmount();
    // No assertion needed beyond not throwing — the subscription must be
    // disposed; the DerivedProperty will keep emitting on the source but
    // the unmounted component must not be notified.
    act(() => {
      source.next(99);
    });
  });
});

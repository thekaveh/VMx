import { StrictMode, type JSX } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { BehaviorSubject, Observable, Subject } from "rxjs";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { DerivedProperty } from "@thekaveh/vmx";

import { useDerivedProperty } from "../src/index.js";

// The internal @thekaveh/vmx seam the hook observes (#415).
const OBSERVE_STATE = Symbol.for("@thekaveh/vmx:DerivedProperty.observeState");
type ObserveState = (listener: () => void) => () => void;

function seamOf<T>(property: DerivedProperty<T>): ObserveState {
  const observe = (property as unknown as Partial<Record<symbol, ObserveState>>)[OBSERVE_STATE];
  if (observe === undefined) throw new Error("this @thekaveh/vmx build lacks the seam");
  return observe.bind(property);
}

/** Wraps the seam on one instance to count the hook's live listeners. */
function countListeners<T>(property: DerivedProperty<T>): () => number {
  const observe = seamOf(property);
  let active = 0;
  Object.defineProperty(property, OBSERVE_STATE, {
    value: (listener: () => void): (() => void) => {
      active += 1;
      const stop = observe(listener);
      let stopped = false;
      return () => {
        if (!stopped) {
          stopped = true;
          active -= 1;
        }
        stop();
      };
    },
  });
  return () => active;
}

function text(value: unknown): string {
  return value === undefined ? "pending" : String(value);
}

function mount<T>(property: DerivedProperty<T>, strict = false) {
  let renders = 0;
  function Probe({ of }: { of: DerivedProperty<T> }): JSX.Element {
    renders += 1;
    return <span>{text(useDerivedProperty(of))}</span>;
  }
  const tree = (of: DerivedProperty<T>): JSX.Element =>
    strict ? <StrictMode><Probe of={of} /></StrictMode> : <Probe of={of} />;
  const view = render(tree(property));
  return {
    text: () => view.container.textContent,
    renders: () => renders,
    rerender: (of: DerivedProperty<T>) => view.rerender(tree(of)),
    unmount: () => view.unmount(),
  };
}

let consoleError: MockInstance<typeof console.error>;

beforeEach(() => {
  consoleError = vi.spyOn(console, "error");
});

afterEach(() => {
  cleanup();
  // No act warnings or late-update errors in any case.
  expect(consoleError).not.toHaveBeenCalled();
  consoleError.mockRestore();
});

describe("useDerivedProperty initialization", () => {
  it("renders a delayed first value when it arrives", () => {
    const source = new Subject<number>();
    const view = mount(new DerivedProperty(source));
    expect(view.text()).toBe("pending");

    act(() => source.next(42));

    expect(view.text()).toBe("42");
    expect(view.renders()).toBe(2);
  });

  it("renders an already initialized value on the first render", () => {
    const view = mount(new DerivedProperty(new BehaviorSubject(7)));

    expect(view.text()).toBe("7");
    expect(view.renders()).toBe(1);
  });

  it("renders later changes after a delayed first value", () => {
    const source = new Subject<number>();
    const view = mount(new DerivedProperty(source));

    act(() => source.next(1));
    act(() => source.next(2));

    expect(view.text()).toBe("2");
    expect(view.renders()).toBe(3);
  });

  it("does not rerender for a repeated equal first value", () => {
    const source = new Subject<number>();
    const view = mount(new DerivedProperty(source));

    act(() => source.next(5));
    act(() => source.next(5));

    expect(view.text()).toBe("5");
    expect(view.renders()).toBe(2);
  });

  it("renders a legitimate null first value", () => {
    const source = new Subject<number | null>();
    const view = mount(new DerivedProperty(source));

    act(() => source.next(null));

    expect(view.text()).toBe("null");
    expect(view.renders()).toBe(2);
  });

  it("keeps the unseeded result for an undefined first value, then renders later values", () => {
    const source = new Subject<number | undefined>();
    const property = new DerivedProperty(source);
    const view = mount(property);

    act(() => source.next(undefined));
    expect(view.text()).toBe("pending");
    expect(view.renders()).toBe(1);
    expect(property.value).toBeUndefined();

    act(() => source.next(3));
    expect(view.text()).toBe("3");
  });

  it("keeps rendering undefined for a never-initialized source", () => {
    const view = mount(new DerivedProperty<number>(new Observable(() => {})));

    expect(view.text()).toBe("pending");
    expect(view.renders()).toBe(1);
  });

  it("observes through one upstream subscription and keeps valueChanged counts", () => {
    let subscriptions = 0;
    const source = new Subject<number>();
    const cold = new Observable<number>((subscriber) => {
      subscriptions += 1;
      return source.subscribe(subscriber);
    });
    const property = new DerivedProperty(cold);
    const changes: number[] = [];
    property.valueChanged.subscribe((value) => changes.push(value));
    const first = mount(property, true);
    const second = mount(property);

    act(() => source.next(1));
    act(() => source.next(2));

    expect(subscriptions).toBe(1);
    expect(changes).toEqual([2]);
    expect(first.text()).toBe("2");
    expect(second.text()).toBe("2");
  });
});

describe("useDerivedProperty subscription ownership", () => {
  it("holds one listener under StrictMode and releases it on unmount", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    const listeners = countListeners(property);
    const view = mount(property, true);
    expect(listeners()).toBe(1);

    act(() => source.next(1));
    expect(view.text()).toBe("1");
    view.unmount();

    expect(listeners()).toBe(0);
    source.next(2);
  });

  it("moves its listener when the property is replaced", () => {
    const firstSource = new Subject<number>();
    const first = new DerivedProperty(firstSource);
    const secondSource = new Subject<number>();
    const second = new DerivedProperty(secondSource);
    const firstListeners = countListeners(first);
    const secondListeners = countListeners(second);
    const view = mount(first);

    view.rerender(second);
    expect(firstListeners()).toBe(0);
    expect(secondListeners()).toBe(1);

    act(() => firstSource.next(1));
    expect(view.text()).toBe("pending");
    act(() => secondSource.next(2));
    expect(view.text()).toBe("2");
  });

  it("stays unseeded when the property is disposed before its first value", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    const listeners = countListeners(property);
    const view = mount(property);

    act(() => property.dispose());
    source.next(1);

    expect(view.text()).toBe("pending");
    expect(view.renders()).toBe(1);
    view.unmount();
    expect(listeners()).toBe(0);
  });

  it("does not update after unmounting before the first value", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    const listeners = countListeners(property);
    const view = mount(property);

    view.unmount();
    source.next(1);

    expect(listeners()).toBe(0);
    expect(view.renders()).toBe(1);
    expect(property.value).toBe(1);
  });

  it("settles on the latest value when a first-value observer publishes again", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    seamOf(property)(() => {
      if (property.value === 1) source.next(2);
    });
    const listeners = countListeners(property);
    const view = mount(property);

    act(() => source.next(1));

    expect(view.text()).toBe("2");
    view.unmount();
    expect(listeners()).toBe(0);
  });

  it("keeps a shared property alive for the remaining hook when another unmounts first", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    const listeners = countListeners(property);
    const leaving = mount(property);
    const staying = mount(property);

    leaving.unmount();
    expect(listeners()).toBe(1);
    act(() => source.next(1));
    expect(staying.text()).toBe("1");
    act(() => source.next(2));

    expect(staying.text()).toBe("2");
    expect(property.value).toBe(2);
    expect(leaving.renders()).toBe(1);
  });

  it("rejects a property without the core seam", () => {
    consoleError.mockImplementation(() => {});
    const legacy = {
      get value(): number {
        return 1;
      },
      valueChanged: new Subject<number>(),
    } as unknown as DerivedProperty<number>;

    expect(() => mount(legacy)).toThrow(/@thekaveh\/vmx 3\.24\.1 or later/);
    consoleError.mockReset();
  });
});

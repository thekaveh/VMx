// The internal state seam @thekaveh/vmx-react uses to observe the silent
// first value (#415). Not part of the spec surface, so no conformance ID.
import { Observable, Subject } from "rxjs";
import { describe, expect, it } from "vitest";

import { DerivedProperty } from "../../src/properties/index.js";

const OBSERVE_STATE = Symbol.for("@thekaveh/vmx:DerivedProperty.observeState");

type ObserveState = (listener: () => void) => () => void;

function observeState<T>(property: DerivedProperty<T>, listener: () => void): () => void {
  const observe = (property as unknown as Record<symbol, ObserveState | undefined>)[OBSERVE_STATE];
  if (typeof observe !== "function") throw new Error("seam missing");
  return observe.call(property, listener);
}

describe("DerivedProperty internal state seam", () => {
  it("signals the silent first value and every later change, but not equal repeats", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    const changes: number[] = [];
    property.valueChanged.subscribe((value) => changes.push(value));
    let signals = 0;
    observeState(property, () => (signals += 1));

    source.next(1);
    expect(signals).toBe(1);
    expect(changes).toEqual([]);
    source.next(1);
    expect(signals).toBe(1);
    source.next(2);
    expect(signals).toBe(2);
    expect(changes).toEqual([2]);
  });

  it("signals after valueChanged, so a reader sees the new value", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    const order: string[] = [];
    property.valueChanged.subscribe(() => order.push("valueChanged"));
    observeState(property, () => order.push(`state:${property.value}`));

    source.next(1);
    source.next(2);

    expect(order).toEqual(["state:1", "valueChanged", "state:2"]);
  });

  it("does not subscribe upstream again", () => {
    let subscriptions = 0;
    const cold = new Observable<number>((subscriber) => {
      subscriptions += 1;
      subscriber.next(1);
    });
    const property = new DerivedProperty(cold);

    const stop = observeState(property, () => {});

    expect(subscriptions).toBe(1);
    expect(property.value).toBe(1);
    stop();
  });

  it("stops signalling after unsubscribe or dispose, and is not an own or enumerable key", () => {
    const source = new Subject<number>();
    const property = new DerivedProperty(source);
    let signals = 0;
    const stop = observeState(property, () => (signals += 1));
    stop();
    stop();
    source.next(1);
    expect(signals).toBe(0);

    observeState(property, () => (signals += 1));
    property.dispose();
    source.next(2);
    expect(signals).toBe(0);
    expect(Object.getOwnPropertySymbols(property)).toEqual([]);
    expect(Object.keys(Object.getPrototypeOf(property) as object)).not.toContain(String(OBSERVE_STATE));
  });
});

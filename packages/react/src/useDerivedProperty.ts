import { useCallback } from "react";
import type { DerivedProperty } from "@thekaveh/vmx";

import { useVersionedSelector } from "./internal/useVersionedSelector.js";

// Internal @thekaveh/vmx seam (3.24.1+). It signals the first value, which a
// DerivedProperty stores without a valueChanged emission (DPROP-009), and
// every later change, without subscribing to the property's sources again.
const OBSERVE_STATE = Symbol.for("@thekaveh/vmx:DerivedProperty.observeState");

type ObserveState = (listener: () => void) => () => void;

function observeState<T>(property: DerivedProperty<T>, listener: () => void): () => void {
  const observe = (property as unknown as Partial<Record<symbol, ObserveState>>)[OBSERVE_STATE];
  if (typeof observe !== "function") {
    throw new TypeError(
      "useDerivedProperty requires a DerivedProperty from @thekaveh/vmx 3.24.1 or later.",
    );
  }
  return observe.call(property, listener);
}

/** Observe a DerivedProperty; unseeded properties yield `undefined`. */
export function useDerivedProperty<T>(property: DerivedProperty<T>): T | undefined {
  const sourceSubscribe = useCallback(
    (invalidate: () => void): (() => void) => observeState(property, invalidate),
    [property],
  );
  return useVersionedSelector(sourceSubscribe, (): T | undefined => {
    try {
      return property.value;
    } catch {
      return undefined;
    }
  });
}

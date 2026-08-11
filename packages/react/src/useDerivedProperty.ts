import { useCallback } from "react";
import type { DerivedProperty } from "@thekaveh/vmx";

import { useVersionedSelector } from "./internal/useVersionedSelector.js";

/** Observe a DerivedProperty; unseeded properties yield `undefined`. */
export function useDerivedProperty<T>(property: DerivedProperty<T>): T | undefined {
  const sourceSubscribe = useCallback(
    (invalidate: () => void): (() => void) => {
      const subscription = property.valueChanged.subscribe({ next: invalidate });
      return () => subscription.unsubscribe();
    },
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

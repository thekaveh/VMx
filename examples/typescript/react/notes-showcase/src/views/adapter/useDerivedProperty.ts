/**
 * useDerivedProperty — React PropertyBridge for a VMx `DerivedProperty<T>`.
 *
 * See scenario doc §7.1 (PropertyBridge), plan §5.c, and Phase 5.b parity:
 * the Python Textual adapter's `bind_derived_property` (commit `6ad6a76`) was
 * added with exactly the same rationale documented here.
 *
 * **Why a dedicated hook?** `DerivedProperty` lives outside the hub message
 * graph. It owns its own `valueChanged` rxjs `Observable` and never publishes
 * a `PropertyChangedMessage` (see `langs/typescript/src/properties/derivedProperty.ts`).
 * `useVm` (which filters PropertyChangedMessages from the VM's hub) therefore
 * cannot observe derived recomputation. Without this hook, view code would
 * have to subscribe to the derived observable directly — a §6.1 Pure-VM-contract
 * violation, and exactly the same gap Phase 5.b flagged in Textual.
 *
 * **DerivedProperty seeding semantics** (spec ch. 15): `valueChanged` only
 * emits on *change* — not on the first source emission. `.value` throws while
 * the property has never received a source emission. The DerivedProperties in
 * this example are all backed by `BehaviorSubject` sources (see e.g.
 * `statusBarVM.ts`, `notesViewVM.ts`, `capabilityActionsVM.ts`), which seed
 * a synchronous first value on construction — so by the time React renders,
 * `.value` is safe to read. We still wrap it in a try/catch and fall back to
 * `undefined as T` so unrelated callers (or hot-path mid-construction renders)
 * don't crash; the value will be updated on the next emission.
 */
import { useCallback, useSyncExternalStore } from "react";
import type { DerivedProperty } from "@thekaveh/vmx";

export function useDerivedProperty<T>(dp: DerivedProperty<T>): T {
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = dp.valueChanged.subscribe({
        next: () => notify(),
      });
      return () => subscription.unsubscribe();
    },
    [dp],
  );

  // getSnapshot must return a stable reference between calls when nothing
  // has changed (useSyncExternalStore's strict-equal compare). DerivedProperty
  // already equality-guards via Object.is internally, so successive reads of
  // `.value` return the same reference until the next change emission.
  const getSnapshot = useCallback((): T => {
    try {
      return dp.value;
    } catch {
      // Pre-emission read. Subscriber above will fire on the first emission.
      return undefined as T;
    }
  }, [dp]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

import { useCallback } from "react";
import type { IMessageHub } from "@thekaveh/vmx";

import { useVersionedSelector, type Equality } from "./internal/useVersionedSelector.js";

export interface HubBackedValue {
  readonly hub: IMessageHub;
}

/**
 * The VMs whose hub messages belong to `vm`: the object itself and every VM
 * its public `wrappedBase` chain reaches. A forwarding decorator delegates its
 * hub and setters to the wrapped VM, which sends each message as its own
 * sender (ADR-0213). A `wrappedBase` getter that throws ends the chain.
 */
function messageSenders(vm: object): ReadonlySet<unknown> {
  const senders = new Set<unknown>([vm]);
  let current: unknown = vm;
  for (;;) {
    let next: unknown;
    try {
      next = (current as { readonly wrappedBase?: unknown }).wrappedBase;
    } catch {
      return senders;
    }
    if (typeof next !== "object" || next === null || senders.has(next)) return senders;
    senders.add(next);
    current = next;
  }
}

export function useVm<TVm extends object & HubBackedValue>(vm: TVm): TVm;
export function useVm<TVm extends object & HubBackedValue, TSelected>(
  vm: TVm,
  selector: (vm: TVm) => TSelected,
  equality?: Equality<TSelected>,
): TSelected;
export function useVm<TVm extends object & HubBackedValue, TSelected>(
  vm: TVm,
  selector?: (vm: TVm) => TSelected,
  equality?: Equality<TSelected>,
): TVm | TSelected {
  const sourceSubscribe = useCallback(
    (invalidate: () => void): (() => void) => {
      const senders = messageSenders(vm);
      const subscription = vm.hub.messages.subscribe({
        next: (message) => {
          // Whole-VM invalidation covers every message this VM publishes:
          // property, lifecycle, collection, and tree-structure changes.
          // Comparing the sender, not the message class, also works when
          // two copies of @thekaveh/vmx are installed.
          if (senders.has(message.sender)) invalidate();
        },
      });
      return () => subscription.unsubscribe();
    },
    [vm],
  );

  const selected = useVersionedSelector(
    sourceSubscribe,
    (version) => selector === undefined ? version : selector(vm),
    selector === undefined ? Object.is : (equality ?? Object.is),
    selector === undefined,
  );
  return selector === undefined ? vm : selected as TSelected;
}

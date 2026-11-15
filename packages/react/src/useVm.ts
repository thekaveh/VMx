import { useCallback } from "react";
import type { IMessageHub } from "@thekaveh/vmx";

import { useVersionedSelector, type Equality } from "./internal/useVersionedSelector.js";
import {
  retainSenderTracker,
  senderRevision,
  type SenderRevision,
} from "./internal/senderRevisions.js";

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

/** A version that only a server render or hydration reads, so it never reaches the hub. */
const SERVER_VERSION = -1;

/**
 * The whole-VM selection: the hook version and the sender count read at render
 * time. `revision` is `undefined` when the hub cannot be tracked.
 */
interface WholeVmSelection {
  readonly version: number;
  readonly revision: SenderRevision | undefined;
}

const SERVER_SELECTION: WholeVmSelection = { version: SERVER_VERSION, revision: undefined };

function wholeVmSelection(vm: HubBackedValue & object, version: number): WholeVmSelection {
  if (version === SERVER_VERSION) return SERVER_SELECTION;
  return { version, revision: senderRevision(vm.hub, messageSenders(vm)) };
}

/**
 * Two whole-VM selections match when the version and the sender count are
 * unchanged on the same tracker. An untracked selection never matches. The
 * subscribe step then catches up, as it did before the tracker existed.
 */
function sameWholeVmSelection(current: WholeVmSelection, next: WholeVmSelection): boolean {
  const before = current.revision;
  const after = next.revision;
  return current.version === next.version && before !== undefined && after !== undefined &&
    before.tracker === after.tracker && before.count === after.count;
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
  const wholeVm = selector === undefined;
  const sourceSubscribe = useCallback(
    (invalidate: () => void): (() => void) => {
      const senders = messageSenders(vm);
      // Retain the tracker before this hook subscribes, so it counts each
      // message first. Only the whole-VM form needs the count.
      const releaseTracker = wholeVm ? retainSenderTracker(vm.hub) : undefined;
      const subscription = vm.hub.messages.subscribe({
        next: (message) => {
          // Whole-VM invalidation covers every message this VM publishes:
          // property, lifecycle, collection, and tree-structure changes.
          // Comparing the sender, not the message class, also works when
          // two copies of @thekaveh/vmx are installed.
          if (senders.has(message.sender)) invalidate();
        },
      });
      return () => {
        subscription.unsubscribe();
        releaseTracker?.();
      };
    },
    [vm, wholeVm],
  );

  const selected = useVersionedSelector<WholeVmSelection | TSelected>(
    sourceSubscribe,
    (version) => selector === undefined ? wholeVmSelection(vm, version) : selector(vm),
    (current, next) => selector === undefined
      ? sameWholeVmSelection(current as WholeVmSelection, next as WholeVmSelection)
      : (equality ?? Object.is)(current as TSelected, next as TSelected),
    wholeVm ? SERVER_VERSION : undefined,
  );
  return selector === undefined ? vm : selected as TSelected;
}

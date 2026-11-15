import type { IMessageHub } from "@thekaveh/vmx";

/**
 * Counts the hub messages that each sender publishes. A whole-VM `useVm`
 * reads the count during render, so its subscribe step can tell whether the VM
 * changed in between without forcing a second render (#1661).
 *
 * One tracker per hub subscribes to the hub when first needed. A subscribed
 * whole-VM hook retains the tracker. When the last retainer unsubscribes, the
 * tracker ends its hub subscription in a microtask, so a StrictMode remount
 * that unsubscribes and resubscribes in the same tick keeps it.
 */
interface Tracker {
  readonly counts: WeakMap<object, number>;
  subscription: { unsubscribe(): void } | undefined;
  /** False after the hub's message stream completes or errors. */
  live: boolean;
  retainers: number;
}

export interface SenderRevision {
  readonly tracker: Tracker;
  readonly count: number;
}

const trackers = new WeakMap<IMessageHub, Tracker>();

function trackerFor(hub: IMessageHub): Tracker {
  const existing = trackers.get(hub);
  if (existing !== undefined) return existing;
  const tracker: Tracker = { counts: new WeakMap(), subscription: undefined, live: true, retainers: 0 };
  trackers.set(hub, tracker);
  tracker.subscription = hub.messages.subscribe({
    next: ({ sender }) => {
      // WeakMap keys must be objects. A message from a non-object sender
      // cannot match a VM, so it is not counted.
      if (typeof sender !== "object" || sender === null) return;
      tracker.counts.set(sender, (tracker.counts.get(sender) ?? 0) + 1);
    },
    complete: () => { tracker.live = false; },
    error: () => { tracker.live = false; },
  });
  return tracker;
}

function releaseIfUnretained(hub: IMessageHub, tracker: Tracker): void {
  if (tracker.retainers > 0 || trackers.get(hub) !== tracker) return;
  trackers.delete(hub);
  tracker.subscription?.unsubscribe();
}

/**
 * Keep the hub's tracker subscribed until the returned function runs. Call it
 * from a subscribe function, never from render. Calling the function again
 * does nothing.
 */
export function retainSenderTracker(hub: IMessageHub): () => void {
  const tracker = trackerFor(hub);
  tracker.retainers += 1;
  let retained = true;
  return () => {
    if (!retained) return;
    retained = false;
    tracker.retainers -= 1;
    if (tracker.retainers === 0) queueMicrotask(() => releaseIfUnretained(hub, tracker));
  };
}

/**
 * The message count of `senders` on `hub`, read now, or `undefined` when the
 * hub cannot be tracked. A caller treats `undefined` as "changed", so the
 * subscribe step catches up as it did before the tracker existed.
 */
export function senderRevision(
  hub: IMessageHub,
  senders: ReadonlySet<unknown>,
): SenderRevision | undefined {
  const tracker = trackerFor(hub);
  if (!tracker.live) return undefined;
  let count = 0;
  // WeakMap.get returns undefined for a primitive key, so non-object senders add nothing.
  for (const sender of senders) count += tracker.counts.get(sender as object) ?? 0;
  return { tracker, count };
}

import type { Subscription } from "rxjs";
import type { IMessageHub } from "@thekaveh/vmx";

export interface VmxStore {
  readonly hub: IMessageHub;
  readonly subscribe: (listener: () => void) => () => void;
  readonly getSnapshot: () => number;
  readonly getServerSnapshot: () => number;
  dispose(): void;
}

/**
 * Adapt one VMx hub to React's external-store protocol.
 *
 * The store connects lazily, shares one hub subscription across all React
 * consumers, and collapses a synchronous hub drain (including `hub.batch`)
 * into one microtask invalidation without discarding any VMx messages.
 */
export function createVmxStore(hub: IMessageHub): VmxStore {
  const listeners = new Set<() => void>();
  let hubSubscription: Subscription | null = null;
  let snapshot = 0;
  let invalidationPending = false;
  let disposed = false;

  const flush = (): void => {
    invalidationPending = false;
    if (disposed) return;
    for (const listener of [...listeners]) listener();
  };

  const scheduleInvalidation = (): void => {
    if (invalidationPending || disposed) return;
    // The snapshot must change synchronously with the external store so React
    // can detect an interleaved mutation during concurrent rendering. Listener
    // delivery remains coalesced to one microtask per synchronous hub drain.
    snapshot += 1;
    invalidationPending = true;
    queueMicrotask(flush);
  };

  const connect = (): boolean => {
    if (hubSubscription !== null || disposed) return false;
    hubSubscription = hub.messages.subscribe({ next: scheduleInvalidation });
    // A hub is intentionally disconnected while it has no React listeners.
    // Advancing once on every connection makes React's mandatory
    // post-subscribe snapshot check catch mutations that happened while idle
    // or between render and subscription installation.
    snapshot += 1;
    return true;
  };

  const disconnect = (): void => {
    hubSubscription?.unsubscribe();
    hubSubscription = null;
  };

  const subscribe = (listener: () => void): (() => void) => {
    if (disposed) return () => {};
    listeners.add(listener);
    connect();
    let active = true;
    return () => {
      if (!active) return;
      active = false;
      listeners.delete(listener);
      if (listeners.size === 0) disconnect();
    };
  };

  const getSnapshot = (): number => snapshot;
  const getServerSnapshot = (): number => snapshot;

  return {
    hub,
    subscribe,
    getSnapshot,
    getServerSnapshot,
    dispose: () => {
      if (disposed) return;
      disposed = true;
      disconnect();
      listeners.clear();
    },
  };
}

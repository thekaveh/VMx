/**
 * useVmCollection — React CollectionBridge for a VMx `IVmCollection`.
 *
 * See scenario doc §7.1 (CollectionBridge) and §7.3 (TS adapter signature) and
 * plan §4.c.
 *
 * Subscribes to `composite.collectionChanged` (rxjs `Observable<CollectionChangedEvent>`
 * — see `langs/typescript/src/composites/compositeVMBase.ts`). On every event,
 * bumps a version counter so `useSyncExternalStore` re-renders the binding
 * component with a fresh array snapshot read from the live composite.
 *
 * The returned array is a defensive *copy* of the composite's current children
 * — React relies on referential change to schedule re-renders for list
 * containers (`Array.map` consumers compare item identity for keys), so we
 * never expose the internal `_children` array directly. The cost is a single
 * `Array.from(...)` per collection event, which is negligible for any UI-scale
 * list.
 *
 * Matches the C# `ObservableCollectionBridge<T>` (Phase 4.a) and Python
 * `bind_collection` (Phase 4.b) at the contract level: one subscription per
 * composite, drained on unmount.
 */
import { useCallback, useRef, useSyncExternalStore } from "react";
import type { ComponentVMBase, IVmCollection } from "@thekaveh/vmx";

export function useVmCollection<VM extends ComponentVMBase>(
  collection: IVmCollection<VM>,
): VM[] {
  // Cached snapshot: we must return the same reference between successive
  // getSnapshot calls when nothing has changed, otherwise useSyncExternalStore
  // would loop forever (it compares strict-equal). We rebuild the snapshot
  // only when a collection event has fired since the last build.
  const snapshotRef = useRef<{ version: number; items: VM[] } | null>(null);
  const versionRef = useRef(0);

  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = collection.collectionChanged.subscribe({
        next: () => {
          versionRef.current += 1;
          notify();
        },
      });
      return () => subscription.unsubscribe();
    },
    [collection],
  );

  const getSnapshot = useCallback((): VM[] => {
    const cached = snapshotRef.current;
    if (cached !== null && cached.version === versionRef.current) {
      return cached.items;
    }
    const items = Array.from(collection);
    snapshotRef.current = { version: versionRef.current, items };
    return items;
  }, [collection]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

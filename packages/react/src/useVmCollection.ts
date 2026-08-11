import { useCallback, useRef, useSyncExternalStore } from "react";
import type { ComponentVMBase, IVmCollection } from "@thekaveh/vmx";

/** Return a cached immutable snapshot of any common VMx child collection. */
export function useVmCollection<TVm extends ComponentVMBase>(
  collection: IVmCollection<TVm>,
): readonly TVm[] {
  const versionRef = useRef(0);
  const snapshotRef = useRef<{
    readonly collection: IVmCollection<TVm>;
    readonly version: number;
    readonly items: readonly TVm[];
  } | null>(null);

  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = collection.collectionChanged.subscribe({
        next: () => {
          versionRef.current += 1;
          notify();
        },
      });
      const cached = snapshotRef.current;
      const current = Array.from(collection);
      if (
        cached === null || cached.collection !== collection ||
        cached.items.length !== current.length ||
        cached.items.some((item, index) => !Object.is(item, current[index]))
      ) versionRef.current += 1;
      return () => subscription.unsubscribe();
    },
    [collection],
  );

  const getSnapshot = useCallback((): readonly TVm[] => {
    const cached = snapshotRef.current;
    if (
      cached?.collection === collection &&
      cached.version === versionRef.current
    ) return cached.items;
    const items = Array.from(collection);
    snapshotRef.current = { collection, version: versionRef.current, items };
    return items;
  }, [collection]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

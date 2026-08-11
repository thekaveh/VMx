import { useCallback, useRef, useSyncExternalStore } from "react";
import type { ObservableList } from "@thekaveh/vmx";

/** Return a cached immutable snapshot of a VMx ObservableList. */
export function useObservableList<T>(list: ObservableList<T>): readonly T[] {
  const versionRef = useRef(0);
  const snapshotRef = useRef<{
    readonly list: ObservableList<T>;
    readonly version: number;
    readonly items: readonly T[];
  } | null>(null);

  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const bump = (): void => {
        versionRef.current += 1;
        notify();
      };
      const subscriptions = [
        list.itemAdded.subscribe({ next: bump }),
        list.itemRemoved.subscribe({ next: bump }),
        list.itemReplaced.subscribe({ next: bump }),
        list.reset.subscribe({ next: bump }),
      ];
      const cached = snapshotRef.current;
      const current = list.toArray();
      if (
        cached === null || cached.list !== list ||
        cached.items.length !== current.length ||
        cached.items.some((item, index) => !Object.is(item, current[index]))
      ) versionRef.current += 1;
      return () => subscriptions.forEach((subscription) => subscription.unsubscribe());
    },
    [list],
  );

  const getSnapshot = useCallback((): readonly T[] => {
    const cached = snapshotRef.current;
    if (cached?.list === list && cached.version === versionRef.current) return cached.items;
    const items = list.toArray();
    snapshotRef.current = { list, version: versionRef.current, items };
    return items;
  }, [list]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

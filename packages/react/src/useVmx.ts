import { useSyncExternalStoreWithSelector } from "use-sync-external-store/with-selector";

import type { Equality } from "./internal/useVersionedSelector.js";
import type { VmxStore } from "./store.js";

/** Select React state from a shared VMx store with equality-based rendering. */
export function useVmx<T>(
  store: VmxStore,
  selector: () => T,
  equality: Equality<T> = Object.is,
): T {
  return useSyncExternalStoreWithSelector(
    store.subscribe,
    store.getSnapshot,
    store.getServerSnapshot,
    selector,
    equality,
  );
}

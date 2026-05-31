/**
 * useDialogOverlay — adapter hook surfacing the currently-open dialog request.
 *
 * See `ReactDialogService.tsx` for the architecture rationale. The dialog
 * service owns a `BehaviorSubject<DialogRequest | null>`; this hook wraps it
 * in `useSyncExternalStore` so a single `DialogOverlay` component can render
 * the active modal without holding React state itself — keeping §6.1 Pure-VM
 * contract (no `useState` / `useReducer` in components) intact.
 *
 * Mirrors `useVm` / `useCommand` / `useVmCollection` / `useDerivedProperty` —
 * one subscription per service, drained on unmount.
 */
import { useCallback, useSyncExternalStore } from "react";

import type { DialogRequest, ReactDialogService } from "./ReactDialogService.js";

export function useDialogOverlay(
  service: ReactDialogService,
): DialogRequest | null {
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = service.current.subscribe({ next: () => notify() });
      return () => subscription.unsubscribe();
    },
    [service],
  );

  // BehaviorSubject seeds an initial value (`null`) synchronously, so the
  // snapshot read here is always safe. Identity stability: the same
  // `DialogRequest` reference is held while the dialog is open, so React's
  // strict-equal compare in useSyncExternalStore correctly skips re-renders
  // when an unrelated subject emission happens between renders.
  const getSnapshot = useCallback(
    (): DialogRequest | null => service.currentValue,
    [service],
  );

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

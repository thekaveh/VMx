/**
 * useVm — React 18 PropertyBridge for a VMx ViewModel.
 *
 * See scenario doc §7.1 (PropertyBridge) and §7.3 (TS adapter signature) and
 * plan §4.c.
 *
 * Subscribes once to the VM's hub via `useSyncExternalStore` — the canonical
 * React 18 primitive for external-store-driven re-renders (handles tearing,
 * Strict Mode double-subscription, and concurrent rendering correctly). Each
 * incoming `PropertyChangedMessage` whose `sender` is the same VM bumps the
 * snapshot version, which forces React to re-render the calling component.
 *
 * The hook returns the VM itself; callers read live values through the VM's
 * getters (`vm.title`, `vm.isDirty`, etc.). This matches the
 * whole-VM-subscription decision in §7.2 — the UI binds individual properties
 * through framework-idiomatic accessors on top of one subscription.
 *
 * **Pure-VM contract** (§6.1): this file is the *only* place under `views/`
 * permitted to subscribe to the VM's hub. View components must read VMs
 * exclusively through this hook (or `useCommand` / `useVmCollection`).
 *
 * **Cross-language note**: the VMx TS `PropertyChangedMessage` field is
 * `sender` (not `source`), matching the Python flavour's discovery in Phase
 * 4.b. The Avalonia adapter (Phase 4.a) uses INPC directly so does not need
 * this filter, but the predicate here mirrors `bind_property._on_next`
 * exactly.
 */
import { useCallback, useRef, useSyncExternalStore } from "react";
import { PropertyChangedMessage, type IMessage } from "vmx";

import { resolveHub } from "./_hubAccessor.js";

export function useVm<T extends object>(vm: T): T {
  // Snapshot is a monotonically-increasing version counter held in a ref. We
  // return it via getSnapshot; useSyncExternalStore compares strict-equal to
  // decide whether to re-render. The VM identity itself is stable across
  // hub events, so using the VM as the snapshot would never trigger updates.
  const versionRef = useRef(0);

  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = resolveHub(vm).messages.subscribe({
        next: (message: IMessage) => {
          if (
            message instanceof PropertyChangedMessage &&
            message.sender === vm
          ) {
            versionRef.current += 1;
            notify();
          }
        },
      });
      return () => subscription.unsubscribe();
    },
    [vm],
  );

  const getSnapshot = useCallback(() => versionRef.current, []);

  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return vm;
}

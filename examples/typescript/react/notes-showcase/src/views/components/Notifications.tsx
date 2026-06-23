/**
 * Notifications — auto-dismissing toast overlay (bottom-right).
 *
 * See plan §5.c. Reads `ws.notifications.visible` through `useVm` — the VM
 * publishes a `PropertyChangedMessage("visible")` on every add/remove (see
 * `notificationsVM.ts`), so `useVm` correctly re-renders this component.
 *
 * Pure-VM contract (§6.1): no React state.
 */
import type React from "react";

import { useVm } from "../adapter/useVm.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

// Stable per-instance keys: the visible list splices from the front as toasts
// auto-dismiss, so an index key would re-associate DOM nodes with the wrong
// toast (content/animation glitch). Each NotificationVM is a stable reference,
// so memoize a monotonic key by object identity (GC'd with the VM).
const toastKeys = new WeakMap<object, number>();
let toastKeySeq = 0;
function toastKey(vm: object): number {
  let key = toastKeys.get(vm);
  if (key === undefined) {
    key = ++toastKeySeq;
    toastKeys.set(vm, key);
  }
  return key;
}

export interface NotificationsProps {
  readonly ws: WorkspaceVM;
}

export const Notifications: React.FC<NotificationsProps> = ({ ws }) => {
  const vm = useVm(ws.notifications);
  return (
    <div className="notifications" role="region" aria-label="Notifications">
      {vm.visible.map((n) => (
        <div key={toastKey(n)} className="notifications-toast">
          {n.notification.message}
        </div>
      ))}
    </div>
  );
};

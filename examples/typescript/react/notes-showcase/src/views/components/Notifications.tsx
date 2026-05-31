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

export interface NotificationsProps {
  readonly ws: WorkspaceVM;
}

export const Notifications: React.FC<NotificationsProps> = ({ ws }) => {
  const vm = useVm(ws.notifications);
  return (
    <div className="notifications" role="region" aria-label="Notifications">
      {vm.visible.map((n, idx) => (
        <div key={idx} className="notifications-toast">
          {n.notification.message}
        </div>
      ))}
    </div>
  );
};

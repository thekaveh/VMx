/**
 * NotifyModal — informational toast (modal flavor — see scenario doc §5.1
 * and Phase 5.b parity NotifyScreen). Reserved for `IDialogService.notify`
 * usages; the toast region (`Notifications` component) handles
 * `INotificationHub` flows instead.
 */
import type React from "react";

import type { DialogRequest } from "../../adapter/ReactDialogService.js";
import { ModalShell } from "./ModalShell.js";

export const NotifyModal: React.FC<{ request: DialogRequest }> = ({ request }) => (
  <ModalShell
    activationKey={request}
    role="alertdialog"
    ariaLabel={request.title ?? request.message}
    onEscape={() => request.resolveVoid()}
  >
    <div className="dialog-window">
      {request.title !== null && <div className="dialog-title">{request.title}</div>}
      <p>{request.message}</p>
      <div className="dialog-buttons">
        <button type="button" onClick={() => request.resolveVoid()}>OK</button>
      </div>
    </div>
  </ModalShell>
);

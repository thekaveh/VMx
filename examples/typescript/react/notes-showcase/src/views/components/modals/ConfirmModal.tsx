/**
 * ConfirmModal — yes/no confirmation dialog.
 *
 * See plan §5.c. Resolves the `DialogRequest` with `true` / `false` via the
 * request's `resolveBool` callback; the dialog service then clears its
 * `BehaviorSubject` so this overlay unmounts.
 *
 * Pure-VM contract (§6.1): no React state. The component is a pure render of
 * the request record.
 */
import type React from "react";

import type { DialogRequest } from "../../adapter/ReactDialogService.js";
import { ModalShell } from "./ModalShell.js";

export const ConfirmModal: React.FC<{ request: DialogRequest }> = ({ request }) => (
  <ModalShell
    activationKey={request}
    ariaLabel={request.title ?? request.message}
    onEscape={() => request.resolveBool(false)}
  >
    <div className="dialog-window">
      {request.title !== null && <div className="dialog-title">{request.title}</div>}
      <p>{request.message}</p>
      <div className="dialog-buttons">
        <button type="button" onClick={() => request.resolveBool(false)}>Cancel</button>
        <button type="button" onClick={() => request.resolveBool(true)}>OK</button>
      </div>
    </div>
  </ModalShell>
);

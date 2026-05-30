/**
 * DialogOverlay — single host for portal-mounted modal dialogs.
 *
 * See plan §5.c and `adapter/ReactDialogService.tsx` for the architecture.
 * Reads the current dialog request (or `null`) from the service via
 * `useDialogOverlay` and dispatches to the matching modal component.
 *
 * Pure-VM contract (§6.1): no React state. The overlay state lives inside
 * `ReactDialogService`'s `BehaviorSubject<DialogRequest | null>`, accessed
 * through `useSyncExternalStore`.
 */
import type React from "react";

import type { ReactDialogService } from "../adapter/ReactDialogService.js";
import { useDialogOverlay } from "../adapter/useDialogOverlay.js";
import { ConfirmModal } from "./modals/ConfirmModal.js";
import { NotifyModal } from "./modals/NotifyModal.js";
import { SaveFileModal } from "./modals/SaveFileModal.js";

export interface DialogOverlayProps {
  readonly service: ReactDialogService;
}

export const DialogOverlay: React.FC<DialogOverlayProps> = ({ service }) => {
  const request = useDialogOverlay(service);
  if (request === null) return null;

  switch (request.kind) {
    case "confirm":
      return <ConfirmModal request={request} />;
    case "saveFile":
    case "openFile":
      return <SaveFileModal request={request} />;
    case "notify":
      return <NotifyModal request={request} />;
    default:
      return null;
  }
};

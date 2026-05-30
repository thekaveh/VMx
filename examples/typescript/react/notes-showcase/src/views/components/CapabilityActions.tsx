/**
 * CapabilityActions — capability-action button row above the status bar.
 *
 * See plan §5.c. Reads `ws.capabilityActions.actions` (a
 * `DerivedProperty<readonly ActionVM[]>`) through `useDerivedProperty` and
 * renders one button per action. Each action's `ICommand` is bound through
 * `useCommand`.
 *
 * Pure-VM contract (§6.1): no React state.
 */
import type React from "react";

import { useCommand } from "../adapter/useCommand.js";
import { useDerivedProperty } from "../adapter/useDerivedProperty.js";
import type { ActionVM } from "../../viewmodels/actionVM.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

export interface CapabilityActionsProps {
  readonly ws: WorkspaceVM;
}

export const CapabilityActions: React.FC<CapabilityActionsProps> = ({ ws }) => {
  const actions = useDerivedProperty(ws.capabilityActions.actions);
  return (
    <div className="capability-actions" role="toolbar" aria-label="Capability actions">
      {(actions ?? []).map((action, idx) => (
        <CapabilityButton key={`${action.label}-${idx}`} action={action} />
      ))}
    </div>
  );
};

const CapabilityButton: React.FC<{ action: ActionVM }> = ({ action }) => {
  const cmd = useCommand(action.command);
  return (
    <button type="button" onClick={cmd.execute} disabled={!cmd.canExecute}>
      {action.label}
    </button>
  );
};

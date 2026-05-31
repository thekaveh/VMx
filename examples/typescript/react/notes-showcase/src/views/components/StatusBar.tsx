/**
 * StatusBar — bottom status line (3 derived slots).
 *
 * See plan §5.c (live-updating derived gap fix, parity with Phase 5.b
 * Textual which adopted `bind_derived_property`). Each slot binds through
 * `useDerivedProperty`, which subscribes to the `DerivedProperty.valueChanged`
 * observable directly — `DerivedProperty` does *not* publish on the hub, so
 * `useVm` cannot observe it.
 *
 * Pure-VM contract (§6.1): no React state.
 */
import type React from "react";

import { useDerivedProperty } from "../adapter/useDerivedProperty.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

export interface StatusBarProps {
  readonly ws: WorkspaceVM;
}

export const StatusBar: React.FC<StatusBarProps> = ({ ws }) => {
  const noteCount = useDerivedProperty(ws.statusBar.noteCountText);
  const starred = useDerivedProperty(ws.statusBar.starredText);
  const editing = useDerivedProperty(ws.statusBar.editingText);

  return (
    <div className="status-bar" role="status">
      <span>{noteCount ?? "0 notes"}</span>
      <span>{starred ?? "0 starred"}</span>
      <span>{editing ?? "No selection"}</span>
    </div>
  );
};

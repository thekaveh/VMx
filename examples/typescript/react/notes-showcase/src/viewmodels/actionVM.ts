/**
 * ActionVM — pure presentation record for one capability-derived action.
 *
 * Used by CapabilityActionsVM to project a focused VM's capability surface
 * into a flat list of (label, command) tuples for the view layer (Phase 5.c).
 *
 * See spec §14.4 (capability dispatch) and the C# `ActionVM.cs` parity record.
 */
import type { ICommand } from "vmx";

export interface ActionVM {
  readonly label: string;
  readonly command: ICommand;
}

/** Helper factory mirroring the C# / Python `ActionVM(label, command)` constructor. */
export function makeActionVM(label: string, command: ICommand): ActionVM {
  return { label, command };
}

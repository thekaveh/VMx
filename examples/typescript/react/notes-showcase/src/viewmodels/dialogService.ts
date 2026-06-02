/**
 * Re-export of VMx core's IDialogService + NullDialogService so the example
 * has a stable, local import path. The host-side React implementation lands
 * in Phase 4.c (adapter); for now tests pass a NullDialogService.
 *
 * See scenario doc §6.2 (Dialog port) and ADR-0029.
 */
export type {
  IDialogService,
  FileFilter,
  NotificationSeverity,
} from "@thekaveh/vmx";
export { NullDialogService } from "@thekaveh/vmx";

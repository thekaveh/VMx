/**
 * NullDialogService — null-object implementation of {@link IDialogService}.
 *
 * All methods return the safest default:
 * - `pickFileToOpen` / `pickFileToSave` → `null` (treat as cancel)
 * - `confirm` → `false` (avoids triggering destructive operations)
 * - `notify` → no-op
 *
 * Stateless — safe to share via {@link NullDialogService.INSTANCE}.
 * See spec/19-dialogs.md §3 and ADR-0017.
 */
import type { FileFilter, IDialogService, NotificationSeverity } from "./dialogService.js";

export class NullDialogService implements IDialogService {
  /** Shared singleton instance (the service holds no state). */
  static readonly INSTANCE: NullDialogService = new NullDialogService();

  pickFileToOpen(
    _filter?: FileFilter | null,
    _title?: string | null,
  ): Promise<string | null> {
    return Promise.resolve(null);
  }

  pickFileToSave(
    _filter?: FileFilter | null,
    _title?: string | null,
    _suggestedName?: string | null,
  ): Promise<string | null> {
    return Promise.resolve(null);
  }

  confirm(_message: string, _title?: string | null): Promise<boolean> {
    return Promise.resolve(false);
  }

  notify(
    _message: string,
    _title?: string | null,
    _severity?: NotificationSeverity,
  ): Promise<void> {
    return Promise.resolve();
  }
}

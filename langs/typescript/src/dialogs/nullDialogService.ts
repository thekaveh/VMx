/**
 * NullDialogService — null-object implementation of {@link IDialogService}.
 *
 * All methods return the safest default:
 * - `pickFileToOpen` / `pickFileToSave` → `null` (treat as cancel)
 * - `confirm` → `false` (avoids triggering destructive operations)
 * - `notify` → no-op
 *
 * Stateless — safe to share via {@link NullDialogService.INSTANCE}.
 * See spec/19-dialogs.md §4 and ADR-0017.
 */
import type { FileFilter, IModalDialogService, NotificationSeverity } from "./dialogService.js";
import type { ModalVM } from "./modalVM.js";

export class NullDialogService implements IModalDialogService {
  /** Shared singleton instance (the service holds no state). */
  static readonly INSTANCE: NullDialogService = new NullDialogService();

  // Singleton: consume via INSTANCE (matches the other null variants and C#).
  private constructor() {}

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

  present<T>(modalVm: ModalVM<T>): Promise<T> {
    modalVm.dismiss(modalVm.cancellationResult);
    return Promise.resolve(modalVm.cancellationResult);
  }
}

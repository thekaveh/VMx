/**
 * IDialogService contract — host-side modal interactions.
 *
 * See spec/19-dialogs.md and ADR-0029.
 */

/** Severity level for a notification presented via {@link IDialogService.notify}. */
export type NotificationSeverity = "info" | "warning" | "error";

/** Describes a file-type filter for file-picker dialogs. */
export interface FileFilter {
  /** Human-readable label, e.g. `"Image files"`. */
  readonly description: string;
  /** File extension patterns, e.g. `["*.png", "*.jpg"]`. */
  readonly extensions: readonly string[];
}

/**
 * Host-side service contract for modal interactions: file pick, confirm prompt,
 * and severity-tagged notify. See spec/19-dialogs.md §2.
 */
export interface IDialogService {
  /**
   * Presents a file-open dialog. Returns the selected path, or `null` on cancel.
   * All parameters are optional.
   */
  pickFileToOpen(
    filter?: FileFilter | null,
    title?: string | null,
  ): Promise<string | null>;

  /**
   * Presents a file-save dialog. Returns the selected path, or `null` on cancel.
   * All parameters are optional.
   */
  pickFileToSave(
    filter?: FileFilter | null,
    title?: string | null,
    suggestedName?: string | null,
  ): Promise<string | null>;

  /**
   * Presents a confirmation prompt. Returns `true` when confirmed,
   * `false` when cancelled or dismissed.
   */
  confirm(message: string, title?: string | null): Promise<boolean>;

  /**
   * Presents a notification with the given severity. Severity defaults to `"info"`
   * when not supplied. Returns when acknowledged or dismissed.
   */
  notify(
    message: string,
    title?: string | null,
    severity?: NotificationSeverity,
  ): Promise<void>;
}

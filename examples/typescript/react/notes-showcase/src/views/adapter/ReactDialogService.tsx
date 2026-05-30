/**
 * ReactDialogService — VMx `IDialogService` for React apps.
 *
 * See scenario doc §7.1 (DialogService) and §7.3 (TS adapter signature) and
 * plan §4.c.
 *
 * **Phase 4.c status**: ships the *adapter shell only* — every method throws
 * `Error("…Phase 5.c…")` with an explicit pointer to the modal components
 * that Phase 5.c will deliver under `views/modals/`. This mirrors:
 *
 *   - `AvaloniaDialogService.Confirm` / `Notify` (Phase 4.a, commit `1a25c3d`).
 *   - `TextualDialogService.*` (Phase 4.b, commit `bf20ea4`).
 *
 * **Why not a `window.confirm` / `window.prompt` fallback?**
 *   The Avalonia and Textual adapters explicitly leave their `confirm`/`notify`
 *   as `NotImplementedException` placeholders rather than substitute a
 *   non-modal stand-in. Three-flavor parity matters more than a temporary
 *   browser-native fallback that would diverge from the cross-language audit
 *   surface (Phase 9). Phase 5.c replaces this whole shell with proper React
 *   portal-mounted modals; until then, the type exists so the composition
 *   root and parity wiring compile today.
 *
 * The `setOverlay` hook is reserved for Phase 5.c: it lets the host component
 * register a setter that the dialog service will eventually call to push a
 * `Modal` element into a top-level portal. It is wired now (and tested
 * implicitly by the Phase 5.c smoke test) so Phase 5.c can land without
 * widening the public surface.
 */
import type { ReactNode } from "react";
import type {
  FileFilter,
  IDialogService,
  NotificationSeverity,
} from "vmx";

const PHASE_5C_MSG = (method: string): string =>
  `ReactDialogService.${method} requires the Phase 5.c modal portal ` +
  "(views/modals/ is not built until Phase 5.c).";

type OverlaySetter = (overlay: ReactNode | null) => void;

export class ReactDialogService implements IDialogService {
  /**
   * Phase 5.c integration hook. Will be called once during host mount with a
   * setter that pushes a `ReactNode` (or `null` to clear) into the app's
   * top-level overlay slot (a React portal target). Currently a no-op stub:
   * every method below throws before the setter would be invoked. Phase 5.c
   * replaces this stub with a real implementation that stores the setter and
   * dispatches modal nodes through it.
   */
  bindOverlaySetter(_setter: OverlaySetter): void {
    // Intentional no-op: Phase 5.c will store the setter and wire it through
    // the methods below. The signature is fixed now so composition compiles.
  }

  /** Phase 5.c: replace with a portal-mounted file-open dialog. */
  pickFileToOpen(
    _filter?: FileFilter | null,
    _title?: string | null,
  ): Promise<string | null> {
    return Promise.reject(new Error(PHASE_5C_MSG("pickFileToOpen")));
  }

  /** Phase 5.c: replace with a portal-mounted file-save dialog. */
  pickFileToSave(
    _filter?: FileFilter | null,
    _title?: string | null,
    _suggestedName?: string | null,
  ): Promise<string | null> {
    return Promise.reject(new Error(PHASE_5C_MSG("pickFileToSave")));
  }

  /** Phase 5.c: replace with a portal-mounted ConfirmModal. */
  confirm(_message: string, _title?: string | null): Promise<boolean> {
    return Promise.reject(new Error(PHASE_5C_MSG("confirm")));
  }

  /** Phase 5.c: replace with a portal-mounted NotificationToast. */
  notify(
    _message: string,
    _title?: string | null,
    _severity?: NotificationSeverity,
  ): Promise<void> {
    return Promise.reject(new Error(PHASE_5C_MSG("notify")));
  }
}

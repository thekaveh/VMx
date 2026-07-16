/**
 * ReactDialogService — VMx `IDialogService` for React apps.
 *
 * See scenario doc §7.1 (DialogService) and §7.3 (TS adapter signature) and
 * plan §5.c.
 *
 * **Phase 5.c implementation.** The Phase 4.c shell threw on every method;
 * Phase 5.c replaces that with a real portal-mounted modal flow. Mirrors:
 *
 *   - `AvaloniaDialogService.Confirm` / `Notify` (Phase 5.a, commit `ed8195d`).
 *   - `TextualDialogService.*` (Phase 5.b, commit `6ad6a76`).
 *
 * **Architecture** (§6.1 Pure-VM contract):
 *   - The dialog service holds a `BehaviorSubject<DialogRequest | null>` of
 *     the current open dialog request — a pure data record (no React types).
 *     Concurrent calls wait in a FIFO queue, satisfying DIA-006 without
 *     replacing an active request or orphaning its promise.
 *   - A `DialogOverlay` component reads the subject through the
 *     `useDialogOverlay` hook (see `useDialogOverlay.ts`), which wraps
 *     `useSyncExternalStore` over the subject. That keeps `Layout.tsx` and
 *     every other component free of `useState` / `useReducer`.
 *   - Modal components (`ConfirmModal`, `SaveFileModal`) invoke `onResolve`
 *     callbacks that the service set up when opening — the current promise
 *     settles and the subject advances to the next queued request or clears.
 *
 * **Why a `BehaviorSubject` and not a setter binding?**
 *   The setter-binding approach in the plan's initial sketch required a
 *   `useState` somewhere in the view tree to hold the current overlay node.
 *   A rxjs `BehaviorSubject` + `useSyncExternalStore` pushes that state into
 *   the adapter where it belongs and matches the contract enforced for every
 *   other binding hook in this adapter (`useVm` / `useCommand` /
 *   `useVmCollection` / `useDerivedProperty`).
 */
import { BehaviorSubject, type Observable } from "rxjs";
import type {
  FileFilter,
  IDialogService,
  NotificationSeverity,
} from "@thekaveh/vmx";

/** Variant tag for the current dialog request (drives `DialogOverlay`'s render). */
export type DialogKind = "confirm" | "saveFile" | "openFile" | "notify";

/** Pure-data request record exposed to view components via `useDialogOverlay`. */
export interface DialogRequest {
  readonly kind: DialogKind;
  readonly title: string | null;
  readonly message: string;
  /** For "saveFile": initial suggested file name. */
  readonly suggestedName: string | null;
  /** For "notify": severity (info / warning / error / success). */
  readonly severity: NotificationSeverity | null;
  /** Caller-supplied resolver for "confirm". */
  readonly resolveBool: (value: boolean) => void;
  /** Caller-supplied resolver for "saveFile" / "openFile". */
  readonly resolveString: (value: string | null) => void;
  /** Caller-supplied resolver for "notify". */
  readonly resolveVoid: () => void;
}

const noopBool = (_: boolean): void => {};
const noopString = (_: string | null): void => {};
const noopVoid = (): void => {};

interface PendingDialog {
  readonly request: DialogRequest;
  readonly cancel: () => void;
}

export class ReactDialogService implements IDialogService {
  readonly #current = new BehaviorSubject<DialogRequest | null>(null);
  #active: PendingDialog | null = null;
  readonly #queue: PendingDialog[] = [];

  /**
   * Observable of the currently-open dialog request (or `null` when nothing
   * is open). Bound by the `DialogOverlay` component through
   * `useDialogOverlay`. Stable identity per service instance.
   */
  get current(): Observable<DialogRequest | null> {
    return this.#current.asObservable();
  }

  /** Synchronous read of the current request. Used by `getSnapshot`. */
  get currentValue(): DialogRequest | null {
    return this.#current.getValue();
  }

  /** Cancels the current request with its neutral result and advances the queue. */
  close(): void {
    this.#active?.cancel();
  }

  #open<T>(
    buildRequest: (complete: (value: T) => void) => DialogRequest,
    cancelledValue: T,
  ): Promise<T> {
    return new Promise<T>((resolve) => {
      let entry: PendingDialog | null = null;
      const complete = (value: T): void => {
        if (entry !== null) this.#settle(entry, () => resolve(value));
      };
      entry = {
        request: buildRequest(complete),
        cancel: () => complete(cancelledValue),
      };
      this.#enqueue(entry);
    });
  }

  #enqueue(entry: PendingDialog): void {
    if (this.#active !== null) {
      this.#queue.push(entry);
      return;
    }
    this.#active = entry;
    this.#current.next(entry.request);
  }

  #settle(entry: PendingDialog, settlePromise: () => void): void {
    if (this.#active !== entry) return;
    const next = this.#queue.shift() ?? null;
    this.#active = next;
    settlePromise();
    this.#current.next(next?.request ?? null);
  }

  pickFileToOpen(
    filter: FileFilter | null = null,
    title: string | null = null,
  ): Promise<string | null> {
    void filter;
    return this.#open<string | null>(
      (complete) => ({
        kind: "openFile",
        title,
        message: "Open file",
        suggestedName: null,
        severity: null,
        resolveBool: noopBool,
        resolveString: complete,
        resolveVoid: noopVoid,
      }),
      null,
    );
  }

  pickFileToSave(
    filter: FileFilter | null = null,
    title: string | null = null,
    suggestedName: string | null = null,
  ): Promise<string | null> {
    void filter;
    return this.#open<string | null>(
      (complete) => ({
        kind: "saveFile",
        title,
        message: "Save file",
        suggestedName,
        severity: null,
        resolveBool: noopBool,
        resolveString: complete,
        resolveVoid: noopVoid,
      }),
      null,
    );
  }

  confirm(message: string, title: string | null = null): Promise<boolean> {
    return this.#open<boolean>(
      (complete) => ({
        kind: "confirm",
        title,
        message,
        suggestedName: null,
        severity: null,
        resolveBool: complete,
        resolveString: noopString,
        resolveVoid: noopVoid,
      }),
      false,
    );
  }

  notify(
    message: string,
    title: string | null = null,
    severity: NotificationSeverity = "info",
  ): Promise<void> {
    return this.#open<void>(
      (complete) => ({
        kind: "notify",
        title,
        message,
        suggestedName: null,
        severity,
        resolveBool: noopBool,
        resolveString: noopString,
        resolveVoid: () => complete(),
      }),
      undefined,
    );
  }
}

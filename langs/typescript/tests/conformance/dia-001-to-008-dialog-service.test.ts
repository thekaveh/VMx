// DIA-001..DIA-008 conformance tests — VMx IDialogService (host modal interactions).
// See spec/19-dialogs.md and ADR-0029.

import { describe, expect, it } from "vitest";

import {
  ConfirmationDecoratorCommand,
  confirm as fluentConfirm,
  confirmWithDialogService,
  RelayCommand,
} from "../../src/index.js";
import type { IDialogService, FileFilter, NotificationSeverity } from "../../src/index.js";
import { NullDialogService } from "../../src/index.js";

// ---------------------------------------------------------------------------
// DIA-001 — PickFileToOpen contract
// ---------------------------------------------------------------------------

describe("DIA-001", () => {
  it("PickFileToOpen returns null in null impl, all params optional", async () => {
    const sut: IDialogService = NullDialogService.INSTANCE;

    const r1 = await sut.pickFileToOpen();
    const r2 = await sut.pickFileToOpen(null, null);
    const r3 = await sut.pickFileToOpen(
      { description: "Images", extensions: ["*.png", "*.jpg"] },
      "Open image",
    );

    expect(r1).toBeNull();
    expect(r2).toBeNull();
    expect(r3).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// DIA-002 — PickFileToSave contract
// ---------------------------------------------------------------------------

describe("DIA-002", () => {
  it("PickFileToSave returns null in null impl, all params optional", async () => {
    const sut: IDialogService = NullDialogService.INSTANCE;

    const r1 = await sut.pickFileToSave();
    const r2 = await sut.pickFileToSave(null, null, null);
    const r3 = await sut.pickFileToSave(
      { description: "Text files", extensions: ["*.txt"] },
      "Save as",
      "output.txt",
    );

    expect(r1).toBeNull();
    expect(r2).toBeNull();
    expect(r3).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// DIA-003 — Confirm contract
// ---------------------------------------------------------------------------

describe("DIA-003", () => {
  it("Confirm returns false in null impl (safest default)", async () => {
    const sut: IDialogService = NullDialogService.INSTANCE;

    const r1 = await sut.confirm("Are you sure?");
    const r2 = await sut.confirm("Delete this item?", "Confirm delete");

    expect(r1).toBe(false);
    expect(r2).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// DIA-004 — Notify contract
// ---------------------------------------------------------------------------

describe("DIA-004", () => {
  it("Notify completes without error for all severities", async () => {
    const sut: IDialogService = NullDialogService.INSTANCE;

    // Default severity (info).
    await expect(sut.notify("Hello")).resolves.toBeUndefined();

    // Explicit severities.
    const severities: NotificationSeverity[] = ["info", "warning", "error"];
    for (const sev of severities) {
      await expect(sut.notify("msg", "title", sev)).resolves.toBeUndefined();
    }
  });
});

// ---------------------------------------------------------------------------
// DIA-005 — NullDialogService null-object behavior
// ---------------------------------------------------------------------------

describe("DIA-005", () => {
  it("NullDialogService: pickFile* returns null; confirm returns false; notify no-op", async () => {
    const sut = NullDialogService.INSTANCE;

    expect(await sut.pickFileToOpen()).toBeNull();
    expect(await sut.pickFileToSave()).toBeNull();
    expect(await sut.confirm("msg")).toBe(false);
    await expect(sut.notify("msg")).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// DIA-006 — Reentrancy is implementation-defined
// ---------------------------------------------------------------------------

/** Queueing implementation: serialises concurrent calls. */
class QueuingDialogService implements IDialogService {
  readonly #queue: Array<{ resolve: (v: boolean) => void }> = [];

  pickFileToOpen(_filter?: FileFilter | null, _title?: string | null): Promise<string | null> {
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
    return new Promise((resolve) => {
      this.#queue.push({ resolve });
    });
  }

  notify(
    _message: string,
    _title?: string | null,
    _severity?: NotificationSeverity,
  ): Promise<void> {
    return Promise.resolve();
  }

  completeNext(result: boolean): void {
    this.#queue.shift()!.resolve(result);
  }
}

/** Immediate-rejecting implementation: second call resolves immediately with false. */
class RejectingDialogService implements IDialogService {
  #activeResolve: ((v: boolean) => void) | null = null;

  pickFileToOpen(_filter?: FileFilter | null, _title?: string | null): Promise<string | null> {
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
    if (this.#activeResolve !== null) {
      // Reentrant — reject immediately.
      return Promise.resolve(false);
    }
    return new Promise((resolve) => {
      this.#activeResolve = resolve;
    });
  }

  notify(
    _message: string,
    _title?: string | null,
    _severity?: NotificationSeverity,
  ): Promise<void> {
    return Promise.resolve();
  }

  completeActive(result: boolean): void {
    this.#activeResolve?.(result);
    this.#activeResolve = null;
  }
}

describe("DIA-006", () => {
  it("Queueing implementation: both concurrent calls resolve with valid values", async () => {
    const queuing = new QueuingDialogService();

    const p1 = queuing.confirm("first");
    const p2 = queuing.confirm("second");

    queuing.completeNext(true);
    queuing.completeNext(false);

    expect(await p1).toBe(true);
    expect(await p2).toBe(false);
  });

  it("Rejecting implementation: reentrant call resolves immediately with false", async () => {
    const rejecting = new RejectingDialogService();

    const pA = rejecting.confirm("active");
    const pB = rejecting.confirm("reentrant");

    // pB should already be resolved (Promise.resolve wraps a settled value).
    expect(await pB).toBe(false);

    // Complete the first call — no exception.
    rejecting.completeActive(true);
    expect(await pA).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// DIA-007 — Cancellation completes with safe default, does not throw
// ---------------------------------------------------------------------------

/**
 * Opt-in cancellable dialog: each call stays pending until the user answers
 * (`answer*`) or the AbortSignal fires. An uncancelled answer is a real file
 * path / `true`, so the cancelled safe defaults (`null` / `false`) are
 * distinguishable from the non-cancelled results.
 */
class CancellationAwareDialogService implements IDialogService {
  #resolveFile: ((v: string | null) => void) | null = null;
  #resolveConfirm: ((v: boolean) => void) | null = null;

  answerFile(path: string): void {
    this.#resolveFile?.(path);
  }

  answerConfirm(value: boolean): void {
    this.#resolveConfirm?.(value);
  }

  pickFileToOpen(
    _filter?: FileFilter | null,
    _title?: string | null,
    signal?: AbortSignal,
  ): Promise<string | null> {
    return new Promise<string | null>((resolve) => {
      if (signal?.aborted) {
        resolve(null);
        return;
      }
      this.#resolveFile = resolve;
      signal?.addEventListener("abort", () => resolve(null), { once: true });
    });
  }

  pickFileToSave(
    _filter?: FileFilter | null,
    _title?: string | null,
    _suggestedName?: string | null,
  ): Promise<string | null> {
    return Promise.resolve(null);
  }

  confirm(
    _message: string,
    _title?: string | null,
    signal?: AbortSignal,
  ): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      if (signal?.aborted) {
        resolve(false);
        return;
      }
      this.#resolveConfirm = resolve;
      signal?.addEventListener("abort", () => resolve(false), { once: true });
    });
  }

  notify(
    _message: string,
    _title?: string | null,
    _severity?: NotificationSeverity,
  ): Promise<void> {
    return Promise.resolve();
  }
}

describe("DIA-007", () => {
  it("Cancelled pickFileToOpen returns null without throwing", async () => {
    const svc = new CancellationAwareDialogService();

    // Control: an uncancelled pick yields a real path (non-null).
    const uncancelled = svc.pickFileToOpen(null, null, new AbortController().signal);
    svc.answerFile("/chosen/file.txt");
    expect(await uncancelled).toBe("/chosen/file.txt");

    // Cancelled before the dialog.
    const before = new AbortController();
    before.abort();
    await expect(svc.pickFileToOpen(null, null, before.signal)).resolves.toBeNull();

    // Cancelled during the dialog; a later answer is ignored.
    const during = new AbortController();
    const pending = svc.pickFileToOpen(null, null, during.signal);
    during.abort();
    svc.answerFile("/too/late.txt");
    await expect(pending).resolves.toBeNull();
  });

  it("Cancelled confirm returns false without throwing", async () => {
    const svc = new CancellationAwareDialogService();

    // Control: an uncancelled confirm yields true.
    const uncancelled = svc.confirm("msg", null, new AbortController().signal);
    svc.answerConfirm(true);
    expect(await uncancelled).toBe(true);

    const before = new AbortController();
    before.abort();
    await expect(svc.confirm("msg", null, before.signal)).resolves.toBe(false);

    const during = new AbortController();
    const pending = svc.confirm("msg", null, during.signal);
    during.abort();
    svc.answerConfirm(true);
    await expect(pending).resolves.toBe(false);
  });
});

// ---------------------------------------------------------------------------
// DIA-008 — ConfirmationDecoratorCommand integration
// ---------------------------------------------------------------------------

/** Controllable dialog service for DIA-008. */
class ControllableDialogService implements IDialogService {
  nextResult = false;

  pickFileToOpen(_filter?: FileFilter | null, _title?: string | null): Promise<string | null> {
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
    return Promise.resolve(this.nextResult);
  }

  notify(
    _message: string,
    _title?: string | null,
    _severity?: NotificationSeverity,
  ): Promise<void> {
    return Promise.resolve();
  }
}

describe("DIA-008", () => {
  it("ConfirmationDecoratorCommand with dialogService.confirm constructs valid command graph", async () => {
    const dialog = new ControllableDialogService();
    let innerExecuted = false;

    const inner = RelayCommand.builder()
      .task(() => {
        innerExecuted = true;
      })
      .build();

    const safeCmd = fluentConfirm(inner, () => dialog.confirm("Proceed?"));

    expect(safeCmd).toBeInstanceOf(ConfirmationDecoratorCommand);
    expect(safeCmd.canExecute()).toBe(true);

    // When dialog returns false: inner must NOT execute.
    dialog.nextResult = false;
    await safeCmd.executeAsync();
    expect(innerExecuted).toBe(false);

    // When dialog returns true: inner MUST execute.
    dialog.nextResult = true;
    await safeCmd.executeAsync();
    expect(innerExecuted).toBe(true);

    // Also exercise the dedicated confirmWithDialogService overload. Spec
    // DIA-008 explicitly covers both the lambda form above and this fluent
    // overload.
    let overloadExecuted = false;
    const inner2 = RelayCommand.builder()
      .task(() => {
        overloadExecuted = true;
      })
      .build();
    const overloadCmd = confirmWithDialogService(inner2, dialog, "Proceed?");

    expect(overloadCmd).toBeInstanceOf(ConfirmationDecoratorCommand);
    expect(overloadCmd.canExecute()).toBe(true);

    dialog.nextResult = false;
    await overloadCmd.executeAsync();
    expect(overloadExecuted).toBe(false);

    dialog.nextResult = true;
    await overloadCmd.executeAsync();
    expect(overloadExecuted).toBe(true);
  });
});

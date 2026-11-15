/**
 * Parent transfer and container compensation for ComponentVMBase (internal).
 *
 * `beginParentTransfer` stages a child's move from its old container to a new
 * one as one transaction. `compensateAutoConstruct` returns an auto-started
 * child to Destructed after a failed container change (spec/06 §4.2, ADR-0218
 * rule 7). Nothing here is part of the public API; the package index does not
 * export this module.
 */
import type { Subscription } from "rxjs";
import type { ComponentVMBase, IOwningParentVM } from "./componentVMBase.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import { reportUnhandled } from "../services/reportUnhandled.js";

/** @internal One-shot staged old-parent removal. */
export class ParentTransfer {
  #finished = false;

  constructor(
    private readonly commitAction: () => void,
    private readonly rollbackAction: () => void,
  ) {}

  commit(): void {
    if (this.#finished) throw new Error("Parent transfer is already finished");
    this.#finished = true;
    this.commitAction();
  }

  rollback(): void {
    if (this.#finished) throw new Error("Parent transfer is already finished");
    this.#finished = true;
    this.rollbackAction();
  }
}

/** @internal Commit ownership without interrupting destination publication. */
export function captureParentTransferCommit(transfer: ParentTransfer): Error | undefined {
  try {
    transfer.commit();
  } catch (error) {
    return error instanceof Error
      ? error
      : new Error("Parent transfer commit failed", { cause: error });
  }
  return undefined;
}

/** Internal failure raised when consumer lifecycle code prevents exact rollback. */
export class ContainerRollbackError extends Error {
  readonly rollbackError: unknown;

  constructor(originalError: unknown, rollbackError: unknown) {
    super("Container mutation failed and lifecycle compensation also failed", {
      cause: originalError,
    });
    this.name = "ContainerRollbackError";
    this.rollbackError = rollbackError;
  }
}

/** Set by the `ComponentVMBase` static block: runs `continuation` once `vm` is released. */
let runWhenReleased: (vm: ComponentVMBase, continuation: () => void) => void;

/** @internal Install the seam that `compensateAutoConstruct` calls. */
export function setRunWhenReleased(
  run: (vm: ComponentVMBase, continuation: () => void) => void,
): void {
  runWhenReleased = run;
}

/**
 * @internal Return a child that a failed container change auto-started to
 * `Destructed` (spec/06 §4.2, ADR-0218 rule 7). Call it after the rollback
 * took the child out of the container. Returns the failure of an immediate
 * compensation, or `undefined`.
 *
 * - A child that was not `Destructed` before the change is left alone.
 * - A `Constructed` child is destructed now.
 * - A child whose construct is still in flight is not waited for. Once its
 *   construct settles `Constructed` with no parent, its `destruct()` runs. A
 *   failure of that later call goes to `reportUnhandled` (ADR-0200 §2.3).
 */
export function compensateAutoConstruct(
  child: ComponentVMBase,
  originalStatus: ConstructionStatus,
): unknown {
  if (originalStatus !== ConstructionStatus.Destructed) return undefined;
  if (child.status === ConstructionStatus.Constructed) {
    try {
      child.destruct();
    } catch (error) {
      return error;
    }
    return undefined;
  }
  if (child.status !== ConstructionStatus.Constructing) return undefined;
  let done = false;
  let subscription: Subscription | undefined;
  const stop = (): boolean => {
    if (done) return false;
    done = true;
    subscription?.unsubscribe();
    return true;
  };
  subscription = child.propertyChanged.subscribe({
    next: (name) => {
      // "isConstructed" is the last per-status notification _setStatus raises.
      if (name !== "isConstructed" || child.status === ConstructionStatus.Constructing) return;
      if (!stop()) return;
      // Destruct only after the child released its in-flight guard.
      runWhenReleased(child._ownershipIdentity, () => {
        if (child.status !== ConstructionStatus.Constructed || child._parent !== null) return;
        try {
          child.destruct();
        } catch (error) {
          reportUnhandled(error);
        }
      });
    },
    // The child's notifications ended: it is Disposed.
    complete: () => { stop(); },
  });
  return undefined;
}

/** @internal Validate exclusive ownership/cycles and stage the old removal. */
export function beginParentTransfer(
  child: ComponentVMBase,
  destination: IOwningParentVM,
): ParentTransfer {
  const identity = child._ownershipIdentity;
  if (identity._ownershipInProgress) {
    throw new Error(
      `Cannot transfer '${child.name}': ownership transaction is already in progress`,
    );
  }
  identity._ownershipInProgress = true;
  let staged: ParentTransfer | null;
  try {
    if (destination.containsChild(child)) {
      throw new Error(`Cannot add '${child.name}': destination already contains that identity`);
    }

    let cursor: IOwningParentVM | null = destination;
    while (cursor !== null) {
      if (cursor.owner._ownershipIdentity === identity) {
        throw new Error(`Cannot add '${child.name}': operation would create a parent cycle`);
      }
      cursor = cursor.ownerParent;
    }
    staged = child._parent?.detachForTransfer(child) ?? null;
  } catch (error) {
    identity._ownershipInProgress = false;
    throw error;
  }

  const finish = (commit: boolean): void => {
    try {
      if (staged !== null) {
        if (commit) staged.commit();
        else staged.rollback();
      }
    } finally {
      identity._ownershipInProgress = false;
    }
  };
  return new ParentTransfer(() => finish(true), () => finish(false));
}

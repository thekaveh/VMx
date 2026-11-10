/**
 * ComponentVMBase — abstract base for all ComponentVM variants.
 *
 * Manages:
 * - Status state machine (construct / destruct / reconstruct / dispose)
 * - Hub publishing (ConstructionStatusChangedMessage, PropertyChangedMessage)
 * - Built-in RelayCommands (select, deselect, selectNext, selectPrev, reconstruct)
 * - Selection predicates and delegation to parent
 * - propertyChanged Observable
 *
 * See spec/05-component-vm.md and spec/02-lifecycle.md.
 */
import { Subject } from "rxjs";
import type { Observable, SchedulerLike, Subscription } from "rxjs";
import type { ViewModelType } from "./types.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import { StatusTransitionError } from "../lifecycle/exceptions.js";
import { requireTransition } from "../lifecycle/transitionValidator.js";
import { ConstructionStatusChangedMessage } from "../messages/constructionStatusChanged.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import { RelayCommand } from "../commands/relayCommand.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import { isSchedulerCancelled } from "../services/cancelledSchedulers.js";
import { reportUnhandled } from "../services/reportUnhandled.js";
import { declareCapabilities } from "../capabilities/registry.js";
import { disposeBestEffort } from "./disposal.js";

/** Minimal parent interface used by a child for selection delegation. */
export interface IParentVM {
  readonly supportsChildSelection: boolean;
  readonly currentChild: ComponentVMBase | null;
  selectChild(vm: ComponentVMBase): void;
  deselectChild(vm: ComponentVMBase): void;
}

/** @internal Ownership-capable parent link used only by VMx containers. */
export interface IOwningParentVM extends IParentVM {
  readonly owner: ComponentVMBase;
  readonly ownerParent: IOwningParentVM | null;
  containsChild(vm: ComponentVMBase): boolean;
  detachForTransfer(vm: ComponentVMBase): ParentTransfer;
  /**
   * Called once by a child right after it publishes Disposed from its own
   * `dispose()`. A composite clears `current` if that child is still current
   * (spec/06 §4.3 rule 9, ADR-0189); other parents do nothing.
   */
  childDisposed(vm: ComponentVMBase): void;
}

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

export interface DisposableResource {
  dispose(): void;
}

export interface UnsubscribableResource {
  unsubscribe(): void;
}

export type OwnedResource =
  | (() => void)
  | DisposableResource
  | UnsubscribableResource;

/** Outcome of a lifecycle hook whose completion was deferred to child settles. */
interface DeferredLifecycleResult {
  readonly failed: boolean;
  readonly error: unknown;
  /** True when the error was not already surfaced by the failing child. */
  readonly rethrow: boolean;
}

/** A joined child settled outside the target; it surfaced its own failure. */
class JoinedChildFailure extends Error {}

/** One-shot completion of a lifecycle hook deferred by `_transitionChildren`. */
class DeferredLifecycle {
  #result: DeferredLifecycleResult | null = null;
  #callback: ((result: DeferredLifecycleResult) => void) | null = null;

  settle(result: DeferredLifecycleResult): void {
    if (this.#result !== null) return;
    this.#result = result;
    const callback = this.#callback;
    this.#callback = null;
    callback?.(result);
  }

  then(callback: (result: DeferredLifecycleResult) => void): void {
    if (this.#result !== null) callback(this.#result);
    else this.#callback = callback;
  }
}

/** The first failure recorded in a background `construct()` or `destruct()` flush. */
interface BackgroundScheduling {
  failure: { error: unknown } | null;
  /**
   * Set when an error left the flush before any failure was recorded (#1052).
   * That error is then the first failure, and later ones are not recorded.
   */
  flushFailed: boolean;
}

/**
 * The outermost background `construct()` or `destruct()` that is still inside
 * its `schedule()` call, per scheduler that serves both channels (#726, #1053).
 * A rollback failure anywhere in that flush is recorded here. That call throws
 * the first one after the flush drains, so no rollback queued in it is lost.
 */
const activeSharedDrains = new WeakMap<SchedulerLike, BackgroundScheduling>();

/**
 * Run `schedule` as the outermost drain of `scheduler` if none is active, then
 * throw the first failure of the flush. An error that leaves the flush, for
 * example from an action that VMx did not queue, is that first failure unless
 * a failure was recorded before it (#1052). Then that error is reported
 * through `reportUnhandled` (ADR-0200 §2.3).
 */
function drainBackground(scheduler: SchedulerLike | null, schedule: () => void): void {
  const scheduling: BackgroundScheduling = { failure: null, flushFailed: false };
  const outermost = scheduler !== null && !activeSharedDrains.has(scheduler);
  if (outermost) activeSharedDrains.set(scheduler, scheduling);
  let thrown: { error: unknown } | null = null;
  try {
    schedule();
  } catch (error) {
    thrown = { error };
  } finally {
    if (outermost) activeSharedDrains.delete(scheduler);
  }
  const recorded = scheduling.failure;
  if (recorded !== null && thrown !== null && thrown.error !== recorded.error) {
    reportUnhandled(thrown.error);
  }
  const failure = recorded ?? thrown;
  if (failure !== null) throw failure.error;
}

/**
 * The VMx actions that a flush error dropped and that run now, per scheduler
 * (#1052). VMx work queued on that scheduler while they run joins this queue,
 * so it does not start a nested flush. Each dropped action's finalizer starts
 * or joins this queue in turn, so the order is that of the finalizers plus the
 * work they queue, not the order of a normal flush. Work that joins the queue
 * goes straight to it, past any `_scheduleForeground` override; this happens
 * only while a failed flush tears down.
 */
const recoveries = new WeakMap<SchedulerLike, Array<() => void>>();

/**
 * Run `run`, a VMx action that an error in a flush of `scheduler` dropped.
 *
 * rxjs calls this from the finalizer of the dropped action, while the flush
 * error is on its way to the caller. That error leaves the flush first, so a
 * failure of the recovered work is a later failure of the same flush. It is
 * reported through `reportUnhandled` (ADR-0200 §2.3) and is never thrown from
 * here: a throw from a finalizer would replace the flush error.
 */
function recoverDropped(scheduler: SchedulerLike, run: () => void): void {
  const drain = activeSharedDrains.get(scheduler);
  if (drain !== undefined) drain.flushFailed = true;
  const active = recoveries.get(scheduler);
  if (active !== undefined) {
    active.push(run);
    return;
  }
  const queue = [run];
  recoveries.set(scheduler, queue);
  try {
    for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
      try {
        next();
      } catch (error) {
        // A later failure of a failed flush (see above).
        reportUnhandled(error);
      }
    }
  } finally {
    recoveries.delete(scheduler);
  }
}

/**
 * The actions that VMx queued on a scheduler and that have not run yet
 * (#1053). These are the lifecycle completions on the foreground, the
 * background actions of `construct()` and `destruct()`, and the asynchronous
 * selection deliveries of a composite (#1421).
 */
interface CountedActions {
  pending: number;
  /** Changes each time a counted action is queued or runs. */
  version: number;
}

const countedActions = new WeakMap<SchedulerLike, CountedActions>();

function countedActionsOf(scheduler: SchedulerLike): CountedActions {
  let counted = countedActions.get(scheduler);
  if (counted === undefined) {
    counted = { pending: 0, version: 0 };
    countedActions.set(scheduler, counted);
  }
  return counted;
}

/**
 * Queue `work` through `schedule` as a counted action of `scheduler` (#1053).
 *
 * An error in a flush of `scheduler` unsubscribes the actions queued behind
 * it, including an error from an action that VMx did not queue. The finalizer
 * added here runs on any unsubscribe of the action. When the action has not
 * run and `scheduler` has not marked itself cancelled, the finalizer treats
 * the action as dropped and runs `work`, so the VM still settles (#1052).
 * VMx never unsubscribes these actions itself. A custom scheduler that cancels
 * queued work by unsubscribing it calls the public `markSchedulerCancelled`
 * first, as `ManualDispatcher` does; otherwise VMx runs that work, including
 * lifecycle work and asynchronous selection deliveries (ADR-0200).
 * `schedule` returns null when it cannot give the action's subscription, such
 * as for an override of `_scheduleForeground`.
 */
function scheduleCounted(
  scheduler: SchedulerLike,
  schedule: (work: () => void) => Subscription | null,
  work: () => void,
): void {
  const counted = countedActionsOf(scheduler);
  counted.pending++;
  counted.version++;
  let ran = false;
  const run = (): void => {
    if (ran) return;
    ran = true;
    counted.pending = Math.max(0, counted.pending - 1);
    counted.version++;
    work();
  };
  const recovery = recoveries.get(scheduler);
  if (recovery !== undefined) {
    recovery.push(run);
    return;
  }
  // A custom SchedulerLike can return an object without rxjs `add`.
  const subscription: Partial<Subscription> | null = schedule(run);
  if (typeof subscription?.add === "function" && subscription.closed !== true) {
    subscription.add(() => {
      if (!ran && !isSchedulerCancelled(scheduler)) recoverDropped(scheduler, run);
    });
  }
}

/** A foreground schedule whose subscription VMx keeps for recovery (#1052). */
interface ForegroundTracking {
  readonly work: () => void;
  subscription: Subscription | null;
}

export abstract class ComponentVMBase {
  readonly #name: string;
  readonly #hint: string;
  readonly #hub: IMessageHub;
  readonly #dispatcher: IDispatcher;
  readonly #onConstructCb: (() => void) | null;
  readonly #onDestructCb: (() => void) | null;
  readonly #background: boolean;

  #status: ConstructionStatus = ConstructionStatus.Destructed;
  #inFlight = false;
  /** Waiting-parent continuations that run once the in-flight guard is released. */
  #afterRelease: Array<() => void> = [];
  #isCurrent = false;
  /** @internal Set by CompositeVMBase / GroupVM to wire parent-child selection delegation. */
  #parent: IOwningParentVM | null = null;
  get _parent(): IOwningParentVM | null { return this.#parent; }
  set _parent(value: IOwningParentVM | null) { this.#parent = value; }
  /** @internal Rejects nested ownership changes until the active mutation commits. */
  _ownershipInProgress = false;
  /** @internal Canonical component identity shared by forwarding decorators. */
  // eslint-disable-next-line @typescript-eslint/prefer-return-this-type -- decorators return the wrapped root
  get _ownershipIdentity(): ComponentVMBase { return this; }

  readonly #propertyChangedSubject = new Subject<string>();
  readonly #statusTrigger = new Subject<void>();
  #triggersDisposed = false;
  #activePropertyNotifications = 0;
  #propertyNotificationTeardownPending = false;
  #ownedResources: OwnedResource[] = [];
  /** Member VMs registered through `ownMember`, in registration order. */
  #members: ComponentVMBase[] = [];
  /** Set once `dispose()` starts, so a re-entrant call is a no-op. */
  #disposeStarted = false;
  /**
   * Set when the inline dispose cascade starts, before the first child or
   * member is disposed (spec/02 §7.2, ADR-0175). From then on no lifecycle
   * call starts, no hook is admitted, and no status other than Disposed
   * commits.
   */
  #cascadeStarted = false;
  #activeLifecycleHook = false;
  #terminalCleanupPending = false;
  #terminalCleanupStarted = false;
  /** Set by `_transitionChildren` while a hook waits for a pending child. */
  #deferredLifecycle: DeferredLifecycle | null = null;
  /** Cancels the active child-settle subscription, if any. */
  #cancelChildWait: (() => void) | null = null;
  /** The foreground work whose subscription `_scheduleForeground` reports (#1052). */
  #foregroundTracking: ForegroundTracking | null = null;

  readonly #selectCommand: RelayCommand;
  readonly #deselectCommand: RelayCommand;
  readonly #selectNextCommand: RelayCommand;
  readonly #selectPreviousCommand: RelayCommand;
  readonly #reconstructCommand: RelayCommand;

  constructor(opts: {
    name: string;
    /** Defaults to `""`. */
    hint?: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    background?: boolean;
  }) {
    this.#name = opts.name;
    this.#hint = opts.hint ?? "";
    this.#hub = opts.hub;
    this.#dispatcher = opts.dispatcher;
    this.#onConstructCb = opts.onConstruct ?? null;
    this.#onDestructCb = opts.onDestruct ?? null;
    this.#background = opts.background ?? false;

    const trigger = this.#statusTrigger.asObservable();

    this.#selectCommand = RelayCommand.builder()
      .predicate(() => this.canSelect())
      .task(() => this.select())
      .triggers(trigger)
      .build();

    this.#deselectCommand = RelayCommand.builder()
      .predicate(() => this.canDeselect())
      .task(() => this.deselect())
      .triggers(trigger)
      .build();

    // SelectNext / SelectPrevious are placeholder stubs on the leaf base —
    // sibling navigation requires parent enumeration, which Composite/Group
    // override. The hardcoded `predicate(() => false)` makes the command's
    // canExecute report false for any orphan leaf, mirroring GRP-002's
    // "predicates always return false when there's no navigation slot"
    // pattern (spec/12-conformance.md §9 GRP-002).
    //
    // VMX-104: the status trigger is wired here too (matching select/deselect
    // and the C#/Python/Swift flavors) so canExecuteChanged fires on lifecycle
    // transitions. The predicate still returns false, but a bound view's
    // "next/previous" affordance now refreshes on status changes instead of
    // going stale — the prior TS-only omission left these commands without any
    // canExecuteChanged signal.
    this.#selectNextCommand = RelayCommand.builder()
      .predicate(() => false)
      .triggers(trigger)
      .build();

    this.#selectPreviousCommand = RelayCommand.builder()
      .predicate(() => false)
      .triggers(trigger)
      .build();

    this.#reconstructCommand = RelayCommand.builder()
      .predicate(() => this.canReconstruct())
      .task(() => this.reconstruct())
      .triggers(trigger)
      .build();

    // Lifecycle capabilities are baseline per spec/14-capabilities.md rule 2.
    declareCapabilities(
      this,
      "IConstructable",
      "IDestructable",
      "IReconstructable",
    );
  }

  // ── Identity ────────────────────────────────────────────────────────────

  get name(): string {
    return this.#name;
  }

  get hint(): string {
    return this.#hint;
  }

  get hub(): IMessageHub {
    return this.#hub;
  }

  abstract get type(): ViewModelType;

  // ── Status ───────────────────────────────────────────────────────────────

  get status(): ConstructionStatus {
    return this.#status;
  }

  /** Disposed, or the inline dispose cascade has started (spec/02 §7.2). */
  #isDisposedOrCascading(): boolean {
    return this.#status === ConstructionStatus.Disposed || this.#cascadeStarted;
  }

  /**
   * A lifecycle call that starts during the inline dispose cascade fails with
   * the error of the same call on a Disposed VM, before the idempotent no-op,
   * the legality check and the in-flight check (spec/02 §7.2, ADR-0175).
   */
  #refuseDuringDisposeCascade(operation: string): void {
    if (this.#cascadeStarted) {
      throw new StatusTransitionError(ConstructionStatus.Disposed, operation);
    }
  }

  get isConstructed(): boolean {
    return this.#status === ConstructionStatus.Constructed;
  }

  // ── IsCurrent ────────────────────────────────────────────────────────────

  get isCurrent(): boolean {
    return this.#isCurrent;
  }

  _setIsCurrent(value: boolean): void {
    if (this._commitIsCurrent(value)) this._publishIsCurrent();
  }

  /**
   * Internal: commits the current flag without publishing it and reports
   * whether it changed. A composite commits `current` and both flags before it
   * publishes any of them (spec/06 §4.3 rule 1, ADR-0173).
   */
  _commitIsCurrent(value: boolean): boolean {
    // Post-dispose guard: spec/02 invariant 3 — Disposed is terminal. A
    // selection change on an already-disposed VM publishes nothing (VMX-006).
    // Only a change to false still applies, when the composite stops making
    // this VM current (ADR-0189); a change to true is a no-op.
    if (this.#status === ConstructionStatus.Disposed) {
      if (!value) this.#isCurrent = false;
      return false;
    }
    if (this.#isCurrent === value) return false;
    this.#isCurrent = value;
    return true;
  }

  /** Internal: publishes a flag change that `_commitIsCurrent` reported. */
  _publishIsCurrent(): void {
    this._notifyPropertyChanged("isCurrent");
  }

  // ── propertyChanged observable ───────────────────────────────────────────

  get propertyChanged(): Observable<string> {
    return this.#propertyChangedSubject.asObservable();
  }

  /**
   * Emit `propertyName` only on the VM-local `propertyChanged` stream. A
   * forwarding decorator emits through its canonical ownership identity, whose
   * stream it exposes (#1352).
   */
  protected _raisePropertyChanged(propertyName: string): void {
    const owner = this._ownershipIdentity;
    if (owner !== this) {
      owner._raisePropertyChanged(propertyName);
      return;
    }
    if (!this.#triggersDisposed) {
      this.#propertyChangedSubject.next(propertyName);
    }
  }

  /**
   * Publish one hub message, then one VM-local notification for assigned
   * state. A forwarding decorator publishes through its canonical ownership
   * identity: the message names that VM as its sender (#1352).
   */
  protected _notifyPropertyChanged(propertyName: string): void {
    const owner = this._ownershipIdentity;
    if (owner !== this) {
      owner._notifyPropertyChanged(propertyName);
      return;
    }
    if (this.#status === ConstructionStatus.Disposed || this.#triggersDisposed) return;
    this.#activePropertyNotifications += 1;
    try {
      try {
        this.#hub.send(PropertyChangedMessage.create(this, this.#name, propertyName));
      } finally {
        // Complete the admitted pair even when a hub observer disposes this VM.
        this.#propertyChangedSubject.next(propertyName);
      }
    } finally {
      this.#activePropertyNotifications -= 1;
      if (
        this.#activePropertyNotifications === 0 &&
        this.#propertyNotificationTeardownPending
      ) {
        this.#propertyNotificationTeardownPending = false;
        this.#propertyChangedSubject.complete();
      }
    }
  }

  // ── Built-in commands ────────────────────────────────────────────────────

  get selectCommand(): RelayCommand {
    return this.#selectCommand;
  }

  get deselectCommand(): RelayCommand {
    return this.#deselectCommand;
  }

  get selectNextCommand(): RelayCommand {
    return this.#selectNextCommand;
  }

  get selectPreviousCommand(): RelayCommand {
    return this.#selectPreviousCommand;
  }

  get reconstructCommand(): RelayCommand {
    return this.#reconstructCommand;
  }

  // ── Lifecycle predicates ─────────────────────────────────────────────────

  canConstruct(): boolean {
    return (
      this.#status === ConstructionStatus.Destructed ||
      this.#status === ConstructionStatus.Constructed
    );
  }

  canDestruct(): boolean {
    return (
      this.#status === ConstructionStatus.Constructed ||
      this.#status === ConstructionStatus.Destructed
    );
  }

  canReconstruct(): boolean {
    return this.#status === ConstructionStatus.Constructed;
  }

  // ── Lifecycle operations ─────────────────────────────────────────────────

  construct(): void {
    this.#refuseDuringDisposeCascade("construct");
    if (this.#status === ConstructionStatus.Constructed) return;

    requireTransition(this.#status, "construct");

    if (this.#inFlight) {
      throw new StatusTransitionError(this.#status, "construct");
    }
    this.#inFlight = true;

    if (this.#background) {
      try {
        this._setStatus(ConstructionStatus.Constructing);
      } catch (error) {
        this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
        this.#releaseInFlight();
        throw error;
      }
      drainBackground(this.#sharedScheduler(), () => {
        this.#scheduleBackground(() => {
          // dispose() may have run between scheduling and execution; Disposed is
          // terminal (spec/02 invariant 3), and a started dispose cascade admits
          // no hook (spec/02 §7.2), so skip the work and the marshalled emission.
          if (this.#isDisposedOrCascading()) {
            this.#releaseInFlight();
            return;
          }
          let deferred: DeferredLifecycle | null;
          try {
            deferred = this.#runLifecycleHookPhase(() => this._onConstruct());
          } catch (e) {
            // VMX-007: roll _status back to Destructed and clear the in-flight
            // guard so a throwing background hook leaves the VM recoverable.
            this.#rollBackFailedBackgroundHook(ConstructionStatus.Destructed, e);
            return;
          }
          // VMX-025: marshal the terminal Constructed emission onto the foreground
          // scheduler so subscribers observe the status change on the foreground
          // (UI) thread, not the background (pool) thread. _setStatus re-checks
          // Disposed, so a dispose() landing before this runs still aborts the
          // transition — no resurrection, no post-dispose publish.
          this.#completeTransition(
            deferred,
            ConstructionStatus.Constructed,
            ConstructionStatus.Destructed,
            true,
          );
        });
      });
    } else {
      let pending = false;
      try {
        try {
          this._setStatus(ConstructionStatus.Constructing);
        } catch (error) {
          this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
          throw error;
        }
        if (this.#isDisposedOrCascading()) return;
        let deferred: DeferredLifecycle | null;
        try {
          deferred = this.#runLifecycleHookPhase(() => this._onConstruct());
        } catch (e) {
          // VMX-007: a throwing construct hook must not wedge the VM in the
          // transient Constructing state. Roll _status back to the prior settled
          // state (Destructed), then re-throw so the caller sees the original
          // failure. The VM is left recoverable instead of wedged.
          this._setStatus(ConstructionStatus.Destructed);
          throw e;
        }
        pending = this.#completeTransition(
          deferred,
          ConstructionStatus.Constructed,
          ConstructionStatus.Destructed,
          false,
        );
      } finally {
        if (!pending) this.#releaseInFlight();
      }
    }
  }

  destruct(): void {
    this.#refuseDuringDisposeCascade("destruct");
    if (this.#status === ConstructionStatus.Destructed) return;

    requireTransition(this.#status, "destruct");

    if (this.#inFlight) {
      throw new StatusTransitionError(this.#status, "destruct");
    }
    this.#inFlight = true;

    if (this.#background) {
      try {
        this._setStatus(ConstructionStatus.Destructing);
      } catch (error) {
        this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
        this.#releaseInFlight();
        throw error;
      }
      drainBackground(this.#sharedScheduler(), () => {
        this.#scheduleBackground(() => {
          // dispose() may have run between scheduling and execution; Disposed is
          // terminal (spec/02 invariant 3), and a started dispose cascade admits
          // no hook (spec/02 §7.2), so skip the work and the marshalled emission.
          if (this.#isDisposedOrCascading()) {
            this.#releaseInFlight();
            return;
          }
          let deferred: DeferredLifecycle | null;
          try {
            deferred = this.#runLifecycleHookPhase(() => this._onDestruct());
          } catch (e) {
            // VMX-007: roll _status back to Constructed and clear the in-flight
            // guard so a throwing background hook leaves the VM recoverable.
            this.#rollBackFailedBackgroundHook(ConstructionStatus.Constructed, e);
            return;
          }
          // VMX-025: marshal the terminal Destructed emission onto the foreground
          // scheduler so subscribers observe the status change on the foreground
          // (UI) thread, not the background (pool) thread. _setStatus re-checks
          // Disposed, so a dispose() landing before this runs still aborts the
          // transition — no resurrection, no post-dispose publish.
          this.#completeTransition(
            deferred,
            ConstructionStatus.Destructed,
            ConstructionStatus.Constructed,
            true,
          );
        });
      });
    } else {
      let pending = false;
      try {
        try {
          this._setStatus(ConstructionStatus.Destructing);
        } catch (error) {
          this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
          throw error;
        }
        if (this.#isDisposedOrCascading()) return;
        let deferred: DeferredLifecycle | null;
        try {
          deferred = this.#runLifecycleHookPhase(() => this._onDestruct());
        } catch (e) {
          // VMX-007: a throwing destruct hook must not wedge the VM in the
          // transient Destructing state. Roll _status back to the prior settled
          // state (Constructed), then re-throw. The VM is left recoverable.
          this._setStatus(ConstructionStatus.Constructed);
          throw e;
        }
        pending = this.#completeTransition(
          deferred,
          ConstructionStatus.Destructed,
          ConstructionStatus.Constructed,
          false,
        );
      } finally {
        if (!pending) this.#releaseInFlight();
      }
    }
  }

  reconstruct(): void {
    this.#refuseDuringDisposeCascade("reconstruct");
    requireTransition(this.#status, "reconstruct");

    if (this.#inFlight) {
      throw new StatusTransitionError(this.#status, "reconstruct");
    }
    this.#inFlight = true;

    let pending = false;
    try {
      try {
        this._setStatus(ConstructionStatus.Destructing);
      } catch (error) {
        this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
        throw error;
      }
      if (this.#isDisposedOrCascading()) return;
      let deferred: DeferredLifecycle | null;
      try {
        deferred = this.#runLifecycleHookPhase(() => this._onDestruct());
      } catch (e) {
        // VMX-007: a failed destruct phase rolls back to Constructed (the state
        // reconstruct started from) so the VM stays recoverable.
        this._setStatus(ConstructionStatus.Constructed);
        throw e;
      }
      if (deferred !== null) {
        // A background child is still destructing: continue with the construct
        // phase only once every child has reached Destructed (spec/02 §6).
        pending = true;
        let settling = true;
        deferred.then(({ failed, error, rethrow }) => {
          if (failed) {
            try {
              this._setStatus(ConstructionStatus.Constructed);
            } finally {
              this.#releaseInFlight();
            }
            if (rethrow) this.#surfaceSettledFailure(error, settling);
            return;
          }
          try {
            let stillPending = false;
            try {
              stillPending = this.#reconstructConstructPhase();
            } finally {
              if (!stillPending) this.#releaseInFlight();
            }
          } catch (e) {
            // The construct phase has already rolled back (VMX-007). An
            // inline throw here would drop work queued in this flush (#1053).
            this.#surfaceSettledFailure(e, settling);
          }
        });
        settling = false;
        return;
      }
      pending = this.#reconstructConstructPhase();
    } finally {
      if (!pending) this.#releaseInFlight();
    }
  }

  /**
   * The Destructed → Constructing → Constructed half of reconstruct(). Returns
   * true while the construct phase waits for a background child.
   */
  #reconstructConstructPhase(): boolean {
    this._setStatus(ConstructionStatus.Destructed);
    if (this.#isDisposedOrCascading()) return false;

    try {
      this._setStatus(ConstructionStatus.Constructing);
    } catch (error) {
      this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
      throw error;
    }
    if (this.#isDisposedOrCascading()) return false;
    let deferred: DeferredLifecycle | null;
    try {
      deferred = this.#runLifecycleHookPhase(() => this._onConstruct());
    } catch (e) {
      // VMX-007: a failed construct phase rolls back to Destructed (the
      // destruct phase already completed) so the VM stays recoverable.
      this._setStatus(ConstructionStatus.Destructed);
      throw e;
    }
    return this.#completeTransition(
      deferred,
      ConstructionStatus.Constructed,
      ConstructionStatus.Destructed,
      false,
    );
  }

  /**
   * Publish the terminal status of a transition whose hook has returned. When
   * the hook deferred completion (a background child is still settling), the
   * terminal status — or the rollback status if a child failed — is published
   * once the deferral settles, and the in-flight guard is held until then.
   * Returns true while the transition is pending. A synchronous, non-foreground
   * completion leaves clearing the in-flight guard to the caller.
   *
   * A deferred walk can fail inside a flush of the foreground scheduler, where a
   * throw drops the work queued behind it (#1053, as #726 for a hook). So a
   * rethrown failure goes through `#surfaceRollbackFailure` or
   * `#surfaceSettledFailure`, and completions are queued as counted actions.
   */
  #completeTransition(
    deferred: DeferredLifecycle | null,
    success: ConstructionStatus,
    rollback: ConstructionStatus,
    foreground: boolean,
  ): boolean {
    // Publish, then release the in-flight guard (as the synchronous path and
    // the C#/Python flavors do), so an observer of the terminal status cannot
    // start a reentrant transition. A parent waiting on this VM continues only
    // after the release (see #runWhenReleased), so it may legally start this
    // VM's next transition (reconstruct).
    const finish = (status: ConstructionStatus): void => {
      try {
        this._setStatus(status);
      } finally {
        this.#releaseInFlight();
      }
    };
    if (deferred === null) {
      if (foreground) this.#queueCompletion(() => { finish(success); });
      else this._setStatus(success);
      return false;
    }
    let settling = true;
    deferred.then(({ failed, error, rethrow }) => {
      const status = failed ? rollback : success;
      if (!foreground) {
        finish(status);
        if (failed && rethrow) this.#surfaceSettledFailure(error, settling);
        return;
      }
      if (!(failed && rethrow)) {
        this.#queueCompletion(() => { finish(status); });
        return;
      }
      this.#surfaceRollbackFailure(() => { finish(status); }, error, false);
    });
    settling = false;
    return true;
  }

  /**
   * Clear the in-flight guard, then run the continuations of parents that
   * observed this VM settle during the transition that just ended. A
   * continuation failure is rethrown after every continuation has run, so it
   * surfaces from the work that published this VM's terminal status — for a
   * background VM, the dispatcher's scheduled work, as a throwing background
   * hook does (VMX-049) — instead of from inside a propertyChanged subscriber,
   * where rxjs would report it as an unhandled error.
   */
  #releaseInFlight(): void {
    this.#inFlight = false;
    this.#runAfterRelease();
  }

  /**
   * Run the queued parent continuations. `dispose()` runs them too: a VM
   * disposed while its transition is deferred (for example mid-reconstruct)
   * never releases its guard, and a waiting parent must still settle.
   */
  #runAfterRelease(): void {
    if (this.#afterRelease.length === 0) return;
    const continuations = this.#afterRelease;
    this.#afterRelease = [];
    let failed = false;
    let failure: unknown;
    for (const continuation of continuations) {
      try {
        continuation();
      } catch (error) {
        if (!failed) {
          failed = true;
          failure = error;
        }
      }
    }
    if (failed) throw failure;
  }

  /**
   * Run `continuation` once this VM is no longer in flight: immediately when it
   * is idle or Disposed, otherwise right after its current transition releases
   * the guard or this VM is disposed.
   */
  #runWhenReleased(continuation: () => void): void {
    if (this.#inFlight && this.#status !== ConstructionStatus.Disposed) {
      this.#afterRelease.push(continuation);
    } else {
      continuation();
    }
  }

  static {
    // Internal seam for compensateAutoConstruct; stays out of the declarations.
    runWhenReleased = (vm, continuation) => { vm.#runWhenReleased(continuation); };
  }

  /** Run a lifecycle hook and return its deferred completion, if it registered one. */
  #runLifecycleHookPhase(hook: () => void): DeferredLifecycle | null {
    this.#deferredLifecycle = null;
    try {
      this.#runLifecycleHook(hook);
    } catch (error) {
      this.#abandonDeferredLifecycle();
      throw error;
    }
    // The hook may have registered a deferral through _transitionChildren.
    const deferred = this.#deferredLifecycle as DeferredLifecycle | null;
    this.#deferredLifecycle = null;
    if (deferred !== null && this.#isDisposedOrCascading()) {
      this.#abandonDeferredLifecycle();
      return null;
    }
    return deferred;
  }

  #abandonDeferredLifecycle(): void {
    this.#deferredLifecycle = null;
    const cancel = this.#cancelChildWait;
    this.#cancelChildWait = null;
    cancel?.();
  }

  /**
   * Stop waiting for a pending child transition without settling this VM, so
   * a child reaching Disposed does not roll this VM back first. The VMx
   * containers do this through `_beginDisposeCascade` at the start of
   * `dispose()`, which also closes hook admission.
   */
  protected _abandonChildTransition(): void {
    this.#abandonDeferredLifecycle();
  }

  /**
   * @internal Unsupported: not part of the public API; containers only.
   * Start the inline dispose cascade (spec/02 §7.2, ADR-0175). A container
   * calls this at the start of `dispose()`, before it disposes its first
   * child. It abandons a pending child wait, as `_abandonChildTransition`
   * does, and closes hook admission: until this VM publishes Disposed, a
   * `construct()`, `destruct()` or `reconstruct()` call throws the
   * `StatusTransitionError` of a Disposed VM, no hook runs, and no status
   * other than Disposed commits.
   */
  protected _beginDisposeCascade(): void {
    this.#cascadeStarted = true;
    this.#abandonDeferredLifecycle();
  }

  /**
   * Construct (`construct === true`) or destruct the given child VMs as part
   * of this VM's own transition (spec/02-lifecycle.md §6.1, ADR-0162). A leaf
   * VM that holds member VMs calls this from its `_onConstruct` or
   * `_onDestruct` override, so the members settle before this VM publishes
   * `Constructed` or `Destructed`:
   *
   * - The walk takes `children` in the order given, one child at a time: a
   *   child starts only after the previous child settled. To destruct in
   *   reverse order, pass a reversed list.
   * - A child already at the target status, or `Disposed`, is skipped. A
   *   child already in the transient status (`Constructing` /
   *   `Destructing`) is joined: the walk waits for it and does not start it
   *   again. A child that reaches `Disposed` during the wait counts as
   *   settled (ADR-0189).
   * - A child left in its transient status (a background child) defers this
   *   VM's terminal status. This VM stays `Constructing` / `Destructing` until
   *   the child settles, and then the walk continues.
   * - A child that settles at any other status (its hook failed) stops the
   *   walk and rolls this VM back to its prior settled status. Siblings that
   *   already reached the target are not undone. A synchronous failure is
   *   thrown from `construct()` / `destruct()`.
   * - `after` runs exactly once, after every child reached the target and
   *   before this VM publishes its terminal status. A throwing `after` rolls
   *   this VM back like a child failure.
   *
   * Call it only from this VM's own construct or destruct hook, including the
   * two phases of `reconstruct()`. A call from anywhere else throws an `Error`
   * and starts no child. `children` is read lazily, one child at a time.
   *
   * @example
   * ```ts
   * protected override _onConstruct(): void {
   *   super._onConstruct();
   *   this._transitionChildren([this.chart, this.table], true);
   * }
   * protected override _onDestruct(): void {
   *   this._transitionChildren([this.table, this.chart], false, () => super._onDestruct());
   * }
   * ```
   */
  protected _transitionChildren(
    children: Iterable<ComponentVMBase>,
    construct: boolean,
    after?: () => void,
  ): void {
    this.#requireOwnLifecycleHook();
    this.#walkChildren(children, construct, after, undefined, undefined);
  }

  /**
   * @internal Unsupported: not part of the public API; containers only.
   * Container form of {@link _transitionChildren}. A child in
   * `joined` already started this transition (factory population): it is
   * joined and its settled status is final, so it is never restarted.
   * `joined` is read live, so a container can extend its walk while it runs.
   * With `isMember`, the walk counts members only (spec/06 §5.1, ADR-0186): it
   * skips a child that is not a member before it starts or joins it, and a
   * child that is no longer a member when it settles does not fail the walk.
   */
  protected _transitionChildrenJoining(
    children: Iterable<ComponentVMBase>,
    construct: boolean,
    after: (() => void) | undefined,
    joined: ReadonlySet<ComponentVMBase>,
    isMember?: (child: ComponentVMBase) => boolean,
  ): void {
    this.#requireOwnLifecycleHook();
    this.#walkChildren(children, construct, after, joined, isMember);
  }

  #requireOwnLifecycleHook(): void {
    if (!this.#activeLifecycleHook) {
      throw new Error(
        "_transitionChildren can only be called from this VM's own construct or destruct hook",
      );
    }
  }

  #walkChildren(
    children: Iterable<ComponentVMBase>,
    construct: boolean,
    after: (() => void) | undefined,
    joined: ReadonlySet<ComponentVMBase> | undefined,
    isMember: ((child: ComponentVMBase) => boolean) | undefined,
  ): void {
    // A child that is no longer a member does not change this VM (ADR-0186).
    const removed = (child: ComponentVMBase): boolean => isMember?.(child) === false;
    const target = construct ? ConstructionStatus.Constructed : ConstructionStatus.Destructed;
    const transient = construct
      ? ConstructionStatus.Constructing
      : ConstructionStatus.Destructing;
    const targetName = construct ? "Constructed" : "Destructed";
    const iterator = children[Symbol.iterator]();
    let deferred: DeferredLifecycle | null = null;
    const reachedTargetOrDisposed = (child: ComponentVMBase): boolean =>
      child.status === target || child.status === ConstructionStatus.Disposed;

    const settle = (result: DeferredLifecycleResult): void => {
      this.#cancelChildWait = null;
      deferred?.settle(result);
    };

    const waitFor = (child: ComponentVMBase): void => {
      if (deferred === null) {
        if (this.#deferredLifecycle !== null) {
          throw new Error("A lifecycle hook already deferred completion");
        }
        deferred = new DeferredLifecycle();
        this.#deferredLifecycle = deferred;
      }
      let done = false;
      let cancelled = false;
      let subscription: Subscription | undefined;
      const stopWaiting = (): boolean => {
        if (done) return false;
        done = true;
        subscription?.unsubscribe();
        return true;
      };
      const continueWalk = (): void => {
        // This VM was disposed (or abandoned the wait) in the meantime.
        if (cancelled) return;
        // Read the status now, not at the settle: a joined reconstructing
        // child is Constructed again by its release (spec/02 §6). A child
        // that reached Disposed meanwhile counts as settled (ADR-0189), and
        // one that is no longer a member does not change this VM (ADR-0186).
        if (!reachedTargetOrDisposed(child) && !removed(child)) {
          // The child rolled back and surfaced its own failure.
          settle({
            failed: true,
            error: new Error(`Child '${child.name}' did not reach ${targetName}`),
            rethrow: false,
          });
          return;
        }
        let stillPending: boolean;
        try {
          stillPending = advance();
        } catch (error) {
          settle({ failed: true, error, rethrow: !(error instanceof JoinedChildFailure) });
          return;
        }
        if (!stillPending) settle({ failed: false, error: undefined, rethrow: false });
      };
      subscription = child.propertyChanged.subscribe({
        next: (name) => {
          // "isConstructed" is the last per-status notification _setStatus raises.
          if (name !== "isConstructed" || child.status === transient) return;
          if (!stopWaiting()) return;
          // Continue only after the child finished publishing and released its
          // in-flight guard, so this VM may start the child's next transition
          // and a failure here does not escape from the child's subscriber.
          child._ownershipIdentity.#runWhenReleased(continueWalk);
        },
        // The child's notifications ended: it is Disposed (ADR-0189).
        complete: () => {
          if (!stopWaiting()) return;
          continueWalk();
        },
      });
      // propertyChanged does not replay, so no settle can have arrived yet.
      this.#cancelChildWait = () => {
        cancelled = true;
        stopWaiting();
      };
    };

    // Returns true when a child is pending and the rest continues on its settle.
    const advance = (): boolean => {
      for (let next = iterator.next(); next.done !== true; next = iterator.next()) {
        const child = next.value;
        if (removed(child)) continue;
        // A Disposed child is skipped: no lifecycle call (spec/02 §6, ADR-0189).
        if (child.status === ConstructionStatus.Disposed) continue;
        if (
          child.status !== target &&
          child.status !== transient &&
          joined?.has(child) !== true
        ) {
          if (construct) child.construct();
          else child.destruct();
        }
        if (child.status === transient) {
          waitFor(child);
          return true;
        }
        // A child disposed during its own transition counts as settled.
        if (!reachedTargetOrDisposed(child) && !removed(child)) {
          const message = `Child '${child.name}' did not reach ${targetName}`;
          // A joined child already surfaced its own failure.
          throw joined?.has(child) === true ? new JoinedChildFailure(message) : new Error(message);
        }
      }
      after?.();
      return false;
    };

    advance();
  }

  dispose(): void {
    // A re-entrant call (for example from a member's disposal) is a no-op;
    // the outer call finishes the teardown.
    if (this.#status === ConstructionStatus.Disposed || this.#disposeStarted) return;
    this.#disposeStarted = true;
    // The member cascade closes hook admission first (spec/02 §7.2).
    this.#cascadeStarted = true;

    disposeBestEffort([
      // A transition waiting on a child never settles once Disposed.
      () => this.#abandonDeferredLifecycle(),
      // Depth-first (spec/02 §7.1, ADR-0162): members reach Disposed before
      // this VM publishes Disposed.
      () => this.#disposeMembers(),
      () => this._setStatus(ConstructionStatus.Disposed),
      // A composite clears this VM as its current child (spec/06 §4.3 rule 9,
      // ADR-0189). It skips the clear during its own dispose cascade.
      () => this._parent?.childDisposed(this),
      // A parent waiting for this VM's release now sees Disposed and settles.
      () => this.#runAfterRelease(),
      () => {
        if (this.#activeLifecycleHook) {
          this.#terminalCleanupPending = true;
        } else {
          this.#finishTerminalCleanup();
        }
      },
    ]);
  }

  #finishTerminalCleanup(): void {
    if (this.#terminalCleanupStarted) return;
    this.#terminalCleanupStarted = true;
    disposeBestEffort([
      () => this._onDispose(),
      () => this.#disposeOwnedResources(),
      () => {
        if (!this.#triggersDisposed) {
          this.#triggersDisposed = true;
          this.#statusTrigger.complete();
          if (this.#activePropertyNotifications === 0) {
            this.#propertyChangedSubject.complete();
          } else {
            this.#propertyNotificationTeardownPending = true;
          }
        }
      },
      () => this.#selectCommand.dispose(),
      () => this.#deselectCommand.dispose(),
      () => this.#selectNextCommand.dispose(),
      () => this.#selectPreviousCommand.dispose(),
      () => this.#reconstructCommand.dispose(),
    ]);
  }

  #restoreStatusAfterPublicationFailure(status: ConstructionStatus): void {
    try {
      this._setStatus(status);
    } catch {
      // The original transition publication failure remains primary.
    }
  }

  #runLifecycleHook(hook: () => void): void {
    this.#activeLifecycleHook = true;
    let hookFailed = false;
    let hookError: unknown;
    try {
      hook();
    } catch (error) {
      hookFailed = true;
      hookError = error;
    }
    this.#activeLifecycleHook = false;

    let cleanupFailed = false;
    let cleanupError: unknown;
    if (this.#terminalCleanupPending) {
      this.#terminalCleanupPending = false;
      try {
        this.#finishTerminalCleanup();
      } catch (error) {
        cleanupFailed = true;
        cleanupError = error;
      }
    }
    if (hookFailed) throw hookError;
    if (cleanupFailed) throw cleanupError;
  }

  // ── Selection ────────────────────────────────────────────────────────────

  canSelect(): boolean {
    return (
      this._parent !== null &&
      this._parent.supportsChildSelection &&
      this._parent.currentChild !== this &&
      this.#status === ConstructionStatus.Constructed
    );
  }

  select(): void {
    // A disposed VM's selection calls are silent no-ops (spec/02 §3).
    if (this.#status === ConstructionStatus.Disposed) return;
    if (this._parent !== null) {
      this._parent.selectChild(this);
    }
  }

  canDeselect(): boolean {
    return (
      this.#status !== ConstructionStatus.Disposed &&
      this._parent !== null &&
      this._parent.currentChild === this
    );
  }

  deselect(): void {
    if (this.#status === ConstructionStatus.Disposed) return;
    if (this._parent !== null) {
      this._parent.deselectChild(this);
    }
  }

  // ── Overridable lifecycle hooks ──────────────────────────────────────────

  protected _onConstruct(): void {
    if (this.#onConstructCb !== null) this.#onConstructCb();
  }

  protected _onDestruct(): void {
    if (this.#onDestructCb !== null) this.#onDestructCb();
  }

  protected _onDispose(): void {
    // override in subclasses
  }

  protected own<T extends OwnedResource>(resource: T): T {
    // A forwarding decorator registers on the wrapped component (ADR-0151).
    const owner = this._ownershipIdentity;
    if (owner !== this) return owner.own(resource);
    if (this.#status === ConstructionStatus.Disposed) {
      ComponentVMBase.#disposeOwnedResource(resource);
    } else {
      this.#ownedResources.push(resource);
    }
    return resource;
  }

  /**
   * Register `member` as a member VM that this VM disposes (spec/02 §7.1,
   * ADR-0162). `dispose()` disposes the members in registration order before
   * this VM publishes `Disposed`, so a member and its own children reach
   * `Disposed` first. Every member is disposed even when one throws; the
   * first failure is thrown from `dispose()` after the rest of the teardown.
   *
   * A member is not a container child: it has no parent link, takes no part
   * in selection, and is not constructed with this VM. Pass it to
   * {@link _transitionChildren} from the construct and destruct hooks to
   * transition it with this VM.
   *
   * A member registered while this VM is disposing or already disposed is
   * disposed at once, and a failure of that disposal is thrown from this
   * call. Registering this VM itself throws an `Error`. Returns `member`, so
   * a field can register it inline:
   * `readonly chart = this.ownMember(new ChartVM(...))`.
   */
  protected ownMember<T extends ComponentVMBase>(member: T): T {
    // A forwarding decorator registers on the wrapped component (ADR-0151).
    const owner = this._ownershipIdentity;
    if (owner !== this) return owner.ownMember(member);
    if (member._ownershipIdentity === owner) {
      throw new Error("A VM cannot register itself as its own member");
    }
    if (this.#disposeStarted || this.#status === ConstructionStatus.Disposed) {
      member.dispose();
    } else if (!this.#members.includes(member)) {
      this.#members.push(member);
    }
    return member;
  }

  #disposeMembers(): void {
    const members = this.#members.splice(0);
    disposeBestEffort(members.map((member) => () => member.dispose()));
  }

  static #disposeOwnedResource(resource: OwnedResource): void {
    try {
      if (typeof resource === "function") resource();
      else if ("dispose" in resource) resource.dispose();
      else resource.unsubscribe();
    } catch {
      // Terminal cleanup is best-effort; one failure must not block the rest.
    }
  }

  #disposeOwnedResources(): void {
    const resources = this.#ownedResources.splice(0).reverse();
    for (const resource of resources) {
      ComponentVMBase.#disposeOwnedResource(resource);
    }
  }

  // ── Internal helpers ─────────────────────────────────────────────────────

  protected _setStatus(newStatus: ConstructionStatus): void {
    // Disposed is terminal (spec/02 invariant 3): a background transition
    // racing dispose() must neither resurrect the VM nor publish
    // post-dispose status messages.
    if (this.#status === ConstructionStatus.Disposed) return;
    // Once the inline dispose cascade has started, the next and last status is
    // Disposed (spec/02 §7.2, ADR-0175). A commit, rollback or restore of a
    // transition that started earlier publishes nothing.
    if (this.#cascadeStarted && newStatus !== ConstructionStatus.Disposed) return;

    this.#status = newStatus;

    disposeBestEffort([
      () => this.#hub.send(
        ConstructionStatusChangedMessage.create(this, this.#name, newStatus),
      ),
      () => this._raisePropertyChanged("status"),
      () => this._raisePropertyChanged("isConstructed"),
      () => {
        if (!this.#triggersDisposed) {
          this.#statusTrigger.next();
        }
      },
    ]);
  }

  protected get _hub(): IMessageHub {
    return this.#hub;
  }

  protected get _dispatcher(): IDispatcher {
    return this.#dispatcher;
  }

  protected get _name(): string {
    return this.#name;
  }

  /**
   * Roll a failed background hook back to `rollback` on the foreground (VMX-025;
   * `_setStatus` re-checks Disposed), clear the in-flight guard, and surface
   * `error`.
   */
  #rollBackFailedBackgroundHook(rollback: ConstructionStatus, error: unknown): void {
    this.#surfaceRollbackFailure(() => {
      try {
        this._setStatus(rollback);
      } finally {
        this.#releaseInFlight();
      }
    }, error, true);
  }

  /**
   * Queue `restore` on the foreground and surface `error` without dropping a
   * queued completion.
   *
   * `RxDispatcher.immediate()` and `NullDispatcher` use `queueScheduler` for
   * both channels. A throw inside an active flush of that scheduler drops every
   * queued action (#726, #1053). `restore` can queue more work, such as the
   * rollback of a parent that waited on this VM. So `error` takes one of three
   * paths:
   *
   * - A background `construct()` or `destruct()` can still be inside its
   *   `schedule()` call on the shared scheduler. Then the outermost one records
   *   `error`, and it throws the error after the flush drains.
   * - A hook failure (`onBackground`) with separate schedulers throws `error`
   *   on the background, as #842 does. asyncScheduler reports it as an
   *   unobserved async throw (VMX-049).
   * - Otherwise `#throwAfterCountedActions` throws `error` on the foreground.
   */
  #surfaceRollbackFailure(restore: () => void, error: unknown, onBackground: boolean): void {
    this.#queueCompletion(restore);
    if (this.#recordOnActiveDrain(error)) return;
    if (this.#sharedScheduler() === null && onBackground) throw error;
    this.#throwAfterCountedActions(error);
  }

  /**
   * Surface `error` for a transition whose rollback has already run on this
   * call stack. A continuation can run while its own transition is still being
   * set up (`settling`). Then it throws to that caller, as before. Otherwise an
   * active drain records the error, or `#throwAfterCountedActions` throws it.
   */
  #surfaceSettledFailure(error: unknown, settling: boolean): void {
    if (settling) throw error;
    if (this.#recordOnActiveDrain(error)) return;
    this.#throwAfterCountedActions(error);
  }

  /**
   * Record `error` on the active drain of this VM's shared scheduler, if any.
   * The drain keeps the first failure of its flush. It reports every later
   * one through `reportUnhandled` (ADR-0200 §2.3).
   */
  #recordOnActiveDrain(error: unknown): boolean {
    const shared = this.#sharedScheduler();
    const drain = shared === null ? undefined : activeSharedDrains.get(shared);
    if (drain === undefined) return false;
    // An error that already left the flush is its first failure (#1052).
    if (drain.flushFailed || drain.failure !== null) reportUnhandled(error);
    else drain.failure = { error };
    return true;
  }

  /** Queue `work` on the foreground as a counted completion (#1053). */
  #queueCompletion(work: () => void): void {
    this._scheduleForegroundCounted(work);
  }

  /**
   * @internal Unsupported: not part of the public API; containers only.
   * Queue `work` through `_scheduleForeground` as a counted foreground
   * action (#1053). A flush error from other work, also work that
   * VMx did not queue, does not drop it: its finalizer runs it (#1052). A
   * composite queues an asynchronous selection delivery here (#1421). A
   * scheduler that marks itself cancelled, such as a disposed
   * `ManualDispatcher`, does not run it.
   */
  protected _scheduleForegroundCounted(work: () => void): void {
    scheduleCounted(this.#dispatcher.foreground, (w) => this.#scheduleForegroundTracked(w), work);
  }

  /** Queue `work` on the background as a counted action (#1053). */
  #scheduleBackground(work: () => void): void {
    const { background } = this.#dispatcher;
    scheduleCounted(background, (w) => background.schedule(w), work);
  }

  /**
   * Schedule `work` through `_scheduleForeground` and return its subscription.
   * Returns null when an override does not pass `work` itself to the base
   * method, so VMx cannot recover that action (#1052).
   */
  #scheduleForegroundTracked(work: () => void): Subscription | null {
    const tracking: ForegroundTracking = { work, subscription: null };
    const outer = this.#foregroundTracking;
    this.#foregroundTracking = tracking;
    try {
      this._scheduleForeground(work);
    } finally {
      this.#foregroundTracking = outer;
    }
    return tracking.subscription;
  }

  /**
   * Throw `error` from a foreground action after the counted actions queued on
   * the foreground have run, so the throw drops none of them.
   *
   * While counted actions are pending, the action queues itself again behind
   * them. A throw can drop a counted action, and an override of
   * `_scheduleForeground` can skip one. Such an action never runs. So if no
   * counted action was queued or ran since the last pass, the action stops
   * waiting. It clears the stale count and throws.
   *
   * Two such failures in one synchronous flush both wait. Only the error of
   * the first throw to run leaves the flush. A throw that the scheduler
   * unsubscribes before it runs, for example after that error, reports
   * `error` through `reportUnhandled` instead (ADR-0200 §2.3). It does so even
   * on a scheduler that marked itself cancelled: cancellation stops work, not
   * reports. An active drain keeps the first recorded failure instead.
   */
  #throwAfterCountedActions(error: unknown): void {
    // During recovery, an error is already leaving the failed flush. This
    // failure is a later one, so it is reported (#1052, ADR-0200 §2.3).
    if (recoveries.has(this.#dispatcher.foreground)) {
      reportUnhandled(error);
      return;
    }
    const counted = countedActionsOf(this.#dispatcher.foreground);
    let seen = counted.version;
    const schedule = (): void => {
      let ran = false;
      const attempt = (): void => {
        ran = true;
        if (counted.pending > 0 && counted.version !== seen) {
          seen = counted.version;
          schedule();
          return;
        }
        counted.pending = 0;
        throw error;
      };
      // A custom SchedulerLike can return an object without rxjs `add`.
      const subscription: Partial<Subscription> | null = this.#scheduleForegroundTracked(attempt);
      if (typeof subscription?.add === "function" && subscription.closed !== true) {
        subscription.add(() => {
          if (!ran) reportUnhandled(error);
        });
      }
    };
    schedule();
  }

  /** The scheduler that serves both channels, or null with separate schedulers. */
  #sharedScheduler(): SchedulerLike | null {
    const { foreground, background } = this.#dispatcher;
    return foreground === background ? foreground : null;
  }

  /** Schedule work on the foreground scheduler. */
  protected _scheduleForeground(work: () => void): void {
    const subscription = this.#dispatcher.foreground.schedule(work);
    const tracking = this.#foregroundTracking;
    if (tracking?.work === work) tracking.subscription = subscription;
  }
}

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
import type { Observable, Subscription } from "rxjs";
import type { ViewModelType } from "./types.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import { StatusTransitionError } from "../lifecycle/exceptions.js";
import { requireTransition } from "../lifecycle/transitionValidator.js";
import { ConstructionStatusChangedMessage } from "../messages/constructionStatusChanged.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import { RelayCommand } from "../commands/relayCommand.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
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
  #activeLifecycleHook = false;
  #terminalCleanupPending = false;
  #terminalCleanupStarted = false;
  /** Set by `_transitionChildren` while a hook waits for a pending child. */
  #deferredLifecycle: DeferredLifecycle | null = null;
  /** Cancels the active child-settle subscription, if any. */
  #cancelChildWait: (() => void) | null = null;

  readonly #selectCommand: RelayCommand;
  readonly #deselectCommand: RelayCommand;
  readonly #selectNextCommand: RelayCommand;
  readonly #selectPreviousCommand: RelayCommand;
  readonly #reconstructCommand: RelayCommand;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    background?: boolean;
  }) {
    this.#name = opts.name;
    this.#hint = opts.hint;
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

  #isDisposed(): boolean {
    return this.#status === ConstructionStatus.Disposed;
  }

  get isConstructed(): boolean {
    return this.#status === ConstructionStatus.Constructed;
  }

  // ── IsCurrent ────────────────────────────────────────────────────────────

  get isCurrent(): boolean {
    return this.#isCurrent;
  }

  _setIsCurrent(value: boolean): void {
    // Post-dispose guard: spec/02 invariant 3 — Disposed is terminal. A
    // selection change on an already-disposed VM is a silent no-op (no
    // local or hub property-change emission), mirroring Swift (VMX-006).
    if (this.#status === ConstructionStatus.Disposed) return;
    if (this.#isCurrent === value) return;
    this.#isCurrent = value;
    this._notifyPropertyChanged("isCurrent");
  }

  // ── propertyChanged observable ───────────────────────────────────────────

  get propertyChanged(): Observable<string> {
    return this.#propertyChangedSubject.asObservable();
  }

  protected _raisePropertyChanged(propertyName: string): void {
    if (!this.#triggersDisposed) {
      this.#propertyChangedSubject.next(propertyName);
    }
  }

  /** Publish one hub message, then one VM-local notification for assigned state. */
  protected _notifyPropertyChanged(propertyName: string): void {
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
      this.#dispatcher.background.schedule(() => {
        // dispose() may have run between scheduling and execution; Disposed is
        // terminal (spec/02 invariant 3), so skip the work and the marshalled
        // emission.
        if (this.#status === ConstructionStatus.Disposed) {
          this.#releaseInFlight();
          return;
        }
        let deferred: DeferredLifecycle | null;
        try {
          deferred = this.#runLifecycleHookPhase(() => this._onConstruct());
        } catch (e) {
          // VMX-007: roll _status back to Destructed (marshalled onto the
          // foreground per VMX-025; _setStatus re-checks Disposed) and clear the
          // in-flight guard so a throwing background hook leaves the VM
          // recoverable, then re-throw. Under the synchronous immediate
          // dispatcher the rollback runs inline and the throw surfaces to the
          // caller; on asapScheduler it is an unobserved async throw (delivering
          // it to an awaiter is tracked by VMX-049).
          this._scheduleForeground(() => {
            try {
              this._setStatus(ConstructionStatus.Destructed);
            } finally {
              this.#releaseInFlight();
            }
          });
          throw e;
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
    } else {
      let pending = false;
      try {
        try {
          this._setStatus(ConstructionStatus.Constructing);
        } catch (error) {
          this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
          throw error;
        }
        if (this.#isDisposed()) return;
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
      this.#dispatcher.background.schedule(() => {
        // dispose() may have run between scheduling and execution; Disposed is
        // terminal (spec/02 invariant 3), so skip the work and the marshalled
        // emission.
        if (this.#status === ConstructionStatus.Disposed) {
          this.#releaseInFlight();
          return;
        }
        let deferred: DeferredLifecycle | null;
        try {
          deferred = this.#runLifecycleHookPhase(() => this._onDestruct());
        } catch (e) {
          // VMX-007: roll _status back to Constructed (marshalled onto the
          // foreground per VMX-025; _setStatus re-checks Disposed) and clear the
          // in-flight guard so a throwing background hook leaves the VM
          // recoverable, then re-throw (unobserved async throw on asapScheduler;
          // VMX-049 tracks delivering it to an awaiter).
          this._scheduleForeground(() => {
            try {
              this._setStatus(ConstructionStatus.Constructed);
            } finally {
              this.#releaseInFlight();
            }
          });
          throw e;
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
    } else {
      let pending = false;
      try {
        try {
          this._setStatus(ConstructionStatus.Destructing);
        } catch (error) {
          this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Constructed);
          throw error;
        }
        if (this.#isDisposed()) return;
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
      if (this.#isDisposed()) return;
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
        deferred.then(({ failed, error, rethrow }) => {
          if (failed) {
            try {
              this._setStatus(ConstructionStatus.Constructed);
            } finally {
              this.#releaseInFlight();
            }
            if (rethrow) throw error;
            return;
          }
          let stillPending = false;
          try {
            stillPending = this.#reconstructConstructPhase();
          } finally {
            if (!stillPending) this.#releaseInFlight();
          }
        });
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
    if (this.#isDisposed()) return false;

    try {
      this._setStatus(ConstructionStatus.Constructing);
    } catch (error) {
      this.#restoreStatusAfterPublicationFailure(ConstructionStatus.Destructed);
      throw error;
    }
    if (this.#isDisposed()) return false;
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
      if (foreground) this._scheduleForeground(() => { finish(success); });
      else this._setStatus(success);
      return false;
    }
    deferred.then(({ failed, error, rethrow }) => {
      const status = failed ? rollback : success;
      if (foreground) this._scheduleForeground(() => { finish(status); });
      else finish(status);
      if (failed && rethrow) throw error;
    });
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
   * the guard.
   */
  #runWhenReleased(continuation: () => void): void {
    if (this.#inFlight && this.#status !== ConstructionStatus.Disposed) {
      this.#afterRelease.push(continuation);
    } else {
      continuation();
    }
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
    if (deferred !== null && this.#isDisposed()) {
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
   * Stop waiting for a pending child transition without settling this VM.
   * Containers call this at the start of `dispose()`, before disposing their
   * children, so a child reaching Disposed does not roll this VM back first.
   */
  protected _abandonChildTransition(): void {
    this.#abandonDeferredLifecycle();
  }

  /**
   * Transition `children` sequentially to Constructed (`construct === true`)
   * or Destructed, then run `after`. Call only from `_onConstruct` /
   * `_onDestruct`. A child that settles synchronously keeps the hook
   * synchronous. A child left in its transient status (a background child)
   * defers this VM's own terminal status until the child settles (spec/02 §6,
   * spec/08 §8); a child that settles anywhere else rolls this VM back. A child
   * already in the transient status is joined, not restarted. A child in
   * `joined` already started this transition (factory population): it is
   * joined and its settled status is final, so it is never restarted.
   */
  protected _transitionChildren(
    children: readonly ComponentVMBase[],
    construct: boolean,
    after?: () => void,
    joined?: ReadonlySet<ComponentVMBase>,
  ): void {
    const target = construct ? ConstructionStatus.Constructed : ConstructionStatus.Destructed;
    const transient = construct
      ? ConstructionStatus.Constructing
      : ConstructionStatus.Destructing;
    const targetName = construct ? "Constructed" : "Destructed";
    let index = 0;
    let deferred: DeferredLifecycle | null = null;

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
      subscription = child.propertyChanged.subscribe({
        next: (name) => {
          // "isConstructed" is the last per-status notification _setStatus raises.
          if (name !== "isConstructed" || child.status === transient) return;
          if (!stopWaiting()) return;
          const settled = child.status;
          // Continue only after the child finished publishing and released its
          // in-flight guard, so this VM may start the child's next transition
          // and a failure here does not escape from the child's subscriber.
          child._ownershipIdentity.#runWhenReleased(() => {
            // This VM was disposed (or abandoned the wait) in the meantime.
            if (cancelled) return;
            if (settled !== target) {
              // The child rolled back (and surfaced its own failure) or was disposed.
              settle({
                failed: true,
                error: new Error(`Child '${child.name}' did not reach ${targetName}`),
                rethrow: false,
              });
              return;
            }
            index += 1;
            let stillPending: boolean;
            try {
              stillPending = advance();
            } catch (error) {
              settle({ failed: true, error, rethrow: !(error instanceof JoinedChildFailure) });
              return;
            }
            if (!stillPending) settle({ failed: false, error: undefined, rethrow: false });
          });
        },
        complete: () => {
          if (!stopWaiting()) return;
          settle({
            failed: true,
            error: new Error(`Child '${child.name}' was disposed before reaching ${targetName}`),
            rethrow: false,
          });
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
      for (; index < children.length; index += 1) {
        const child = children[index];
        if (child === undefined) continue;
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
        if (child.status !== target) {
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
    if (this.#status === ConstructionStatus.Disposed) return;

    disposeBestEffort([
      // A transition waiting on a child never settles once Disposed.
      () => this.#abandonDeferredLifecycle(),
      () => this._setStatus(ConstructionStatus.Disposed),
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
    if (this.#status === ConstructionStatus.Disposed) {
      ComponentVMBase.#disposeOwnedResource(resource);
    } else {
      this.#ownedResources.push(resource);
    }
    return resource;
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

  /** Schedule work on the foreground scheduler. */
  protected _scheduleForeground(work: () => void): void {
    this.#dispatcher.foreground.schedule(work);
  }
}

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
import { reportUnhandled } from "../services/reportUnhandled.js";
import { declareCapabilities } from "../capabilities/registry.js";
import { disposeBestEffort } from "./disposal.js";
import { queueSelectionInputs } from "./selectionInputScope.js";
import { setRunWhenReleased, type ParentTransfer } from "./parentTransfer.js";
import {
  countedActionsOf,
  drainBackground,
  isRecovering,
  recordOnActiveDrain,
  scheduleCounted,
} from "./schedulerRecovery.js";

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

/** A foreground schedule whose subscription VMx keeps for recovery (#1052). */
interface ForegroundTracking {
  readonly work: () => void;
  subscription: Subscription | null;
}

/** One lifecycle phase: the transient status it publishes, its rollback status and its hook. */
interface PhaseSpec {
  readonly transient: ConstructionStatus;
  /** The status a failed phase returns to: the prior settled status (VMX-007). */
  readonly rollback: ConstructionStatus;
  readonly hook: () => void;
}

/** construct() or destruct(): one phase, plus the status the transition settles to. */
interface TransitionSpec extends PhaseSpec {
  readonly operation: "construct" | "destruct";
  readonly settled: ConstructionStatus;
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
  /** A link that changes re-raises Select and Deselect `canExecuteChanged` (ADR-0242). */
  set _parent(value: IOwningParentVM | null) {
    if (this.#parent === value) return;
    this.#parent = value;
    this.#raiseSelectionInputsChanged();
  }
  /** @internal Rejects nested ownership changes until the active mutation commits. */
  _ownershipInProgress = false;
  /** @internal Canonical component identity shared by forwarding decorators. */
  // eslint-disable-next-line @typescript-eslint/prefer-return-this-type -- decorators return the wrapped root
  get _ownershipIdentity(): ComponentVMBase { return this; }

  readonly #propertyChangedSubject = new Subject<string>();
  readonly #statusTrigger = new Subject<void>();
  /** Fires when IsCurrent or the Parent link changes (ADR-0242). */
  readonly #selectionTrigger = new Subject<void>();
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
    const selectionTrigger = this.#selectionTrigger.asObservable();

    this.#selectCommand = RelayCommand.builder()
      .predicate(() => this.canSelect())
      .task(() => this.select())
      .triggers(trigger)
      .triggers(selectionTrigger)
      .build();

    this.#deselectCommand = RelayCommand.builder()
      .predicate(() => this.canDeselect())
      .task(() => this.deselect())
      .triggers(trigger)
      .triggers(selectionTrigger)
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
    try {
      this._notifyPropertyChanged("isCurrent");
    } finally {
      this.#raiseSelectionInputsChanged();
    }
  }

  /**
   * Re-raises `canExecuteChanged` of Select and Deselect (ADR-0242). Skipped
   * once teardown has started, since a completed Subject must not be fed.
   */
  #raiseSelectionInputsChanged(): void {
    queueSelectionInputs(() => this.#emitSelectionInputs());
  }

  /**
   * Emits the Select and Deselect notification (ADR-0242). It runs when the
   * outermost selection-input scope closes, after the container finishes its
   * membership change.
   */
  #emitSelectionInputs(): void {
    if (!this.#triggersDisposed) {
      this.#selectionTrigger.next();
    }
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
    this.#transition({
      operation: "construct",
      transient: ConstructionStatus.Constructing,
      settled: ConstructionStatus.Constructed,
      rollback: ConstructionStatus.Destructed,
      hook: () => this._onConstruct(),
    });
  }

  destruct(): void {
    this.#transition({
      operation: "destruct",
      transient: ConstructionStatus.Destructing,
      settled: ConstructionStatus.Destructed,
      rollback: ConstructionStatus.Constructed,
      hook: () => this._onDestruct(),
    });
  }

  /**
   * The body of construct() and destruct() (spec/02 §5). A background VM
   * publishes the transient status here, then runs the hook on the background
   * scheduler. Otherwise the phase runs inline. The in-flight guard is held
   * until the transition settles, or until a deferred completion does.
   */
  #transition(spec: TransitionSpec): void {
    this.#refuseDuringDisposeCascade(spec.operation);
    if (this.#status === spec.settled) return;

    requireTransition(this.#status, spec.operation);

    if (this.#inFlight) {
      throw new StatusTransitionError(this.#status, spec.operation);
    }
    this.#inFlight = true;

    if (this.#background) {
      try {
        this.#publishTransient(spec);
      } catch (error) {
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
            deferred = this.#runLifecycleHookPhase(spec.hook);
          } catch (e) {
            // VMX-007: roll _status back to the prior settled status and clear the
            // in-flight guard so a throwing background hook leaves the VM recoverable.
            this.#rollBackFailedBackgroundHook(spec.rollback, e);
            return;
          }
          // VMX-025: marshal the terminal status onto the foreground scheduler so
          // subscribers observe the change on the foreground (UI) thread, not the
          // background (pool) thread. _setStatus re-checks Disposed, so a dispose()
          // landing before this runs still aborts the transition — no resurrection,
          // no post-dispose publish.
          this.#completeTransition(deferred, spec.settled, spec.rollback, true);
        });
      });
    } else {
      let pending = false;
      try {
        const phase = this.#runPhase(spec);
        if (phase !== null) {
          pending = this.#completeTransition(phase.deferred, spec.settled, spec.rollback, false);
        }
      } finally {
        if (!pending) this.#releaseInFlight();
      }
    }
  }

  /**
   * Publish the transient status of a phase. When the publication fails, restore
   * the rollback status and rethrow; the publication failure stays primary.
   */
  #publishTransient(spec: PhaseSpec): void {
    try {
      this._setStatus(spec.transient);
    } catch (error) {
      this.#restoreStatusAfterPublicationFailure(spec.rollback);
      throw error;
    }
  }

  /**
   * Run one synchronous phase: publish the transient status, then run the hook.
   * Returns null without running the hook when the VM is disposing or disposed.
   * A failing hook publishes the rollback status and rethrows (VMX-007).
   */
  #runPhase(spec: PhaseSpec): { readonly deferred: DeferredLifecycle | null } | null {
    this.#publishTransient(spec);
    if (this.#isDisposedOrCascading()) return null;
    let deferred: DeferredLifecycle | null;
    try {
      deferred = this.#runLifecycleHookPhase(spec.hook);
    } catch (e) {
      // VMX-007: a throwing hook must not wedge the VM in the transient status.
      this._setStatus(spec.rollback);
      throw e;
    }
    return { deferred };
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
      const destruct = this.#runPhase({
        transient: ConstructionStatus.Destructing,
        rollback: ConstructionStatus.Constructed,
        hook: () => this._onDestruct(),
      });
      if (destruct === null) return;
      const deferred = destruct.deferred;
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

    const phase = this.#runPhase({
      transient: ConstructionStatus.Constructing,
      rollback: ConstructionStatus.Destructed,
      hook: () => this._onConstruct(),
    });
    if (phase === null) return false;
    return this.#completeTransition(
      phase.deferred,
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
    setRunWhenReleased((vm, continuation) => { vm.#runWhenReleased(continuation); });
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
          // Completed, never disposed (ADR-0242): see #emitSelectionInputs.
          this.#selectionTrigger.complete();
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
    return recordOnActiveDrain(this.#sharedScheduler(), error);
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
    if (isRecovering(this.#dispatcher.foreground)) {
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

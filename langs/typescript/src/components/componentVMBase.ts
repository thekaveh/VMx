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
import type { Observable } from "rxjs";
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

/** @internal Validate exclusive ownership/cycles and stage the old removal. */
export function beginParentTransfer(
  child: ComponentVMBase,
  destination: IOwningParentVM,
): ParentTransfer | null {
  if (destination.containsChild(child)) {
    throw new Error(`Cannot add '${child.name}': destination already contains that identity`);
  }

  let cursor: IOwningParentVM | null = destination;
  while (cursor !== null) {
    if (cursor.owner === child) {
      throw new Error(`Cannot add '${child.name}': operation would create a parent cycle`);
    }
    cursor = cursor.ownerParent;
  }

  return child._parent?.detachForTransfer(child) ?? null;
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
  #isCurrent = false;
  /** @internal Set by CompositeVMBase / GroupVM to wire parent-child selection delegation. */
  _parent: IOwningParentVM | null = null;

  readonly #propertyChangedSubject = new Subject<string>();
  readonly #statusTrigger = new Subject<void>();
  #triggersDisposed = false;
  #activePropertyNotifications = 0;
  #propertyNotificationTeardownPending = false;
  #ownedResources: OwnedResource[] = [];

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
      this._setStatus(ConstructionStatus.Constructing);
      this.#dispatcher.background.schedule(() => {
        // dispose() may have run between scheduling and execution; Disposed is
        // terminal (spec/02 invariant 3), so skip the work and the marshalled
        // emission.
        if (this.#status === ConstructionStatus.Disposed) {
          this.#inFlight = false;
          return;
        }
        try {
          this._onConstruct();
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
              this.#inFlight = false;
            }
          });
          throw e;
        }
        // VMX-025: marshal the terminal Constructed emission onto the foreground
        // scheduler so subscribers observe the status change on the foreground
        // (UI) thread, not the background (pool) thread. _setStatus re-checks
        // Disposed, so a dispose() landing before this runs still aborts the
        // transition — no resurrection, no post-dispose publish.
        this._scheduleForeground(() => {
          try {
            this._setStatus(ConstructionStatus.Constructed);
          } finally {
            this.#inFlight = false;
          }
        });
      });
    } else {
      try {
        this._setStatus(ConstructionStatus.Constructing);
        try {
          this._onConstruct();
        } catch (e) {
          // VMX-007: a throwing construct hook must not wedge the VM in the
          // transient Constructing state. Roll _status back to the prior settled
          // state (Destructed), then re-throw so the caller sees the original
          // failure. The VM is left recoverable instead of wedged.
          this._setStatus(ConstructionStatus.Destructed);
          throw e;
        }
        this._setStatus(ConstructionStatus.Constructed);
      } finally {
        this.#inFlight = false;
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
      this._setStatus(ConstructionStatus.Destructing);
      this.#dispatcher.background.schedule(() => {
        // dispose() may have run between scheduling and execution; Disposed is
        // terminal (spec/02 invariant 3), so skip the work and the marshalled
        // emission.
        if (this.#status === ConstructionStatus.Disposed) {
          this.#inFlight = false;
          return;
        }
        try {
          this._onDestruct();
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
              this.#inFlight = false;
            }
          });
          throw e;
        }
        // VMX-025: marshal the terminal Destructed emission onto the foreground
        // scheduler so subscribers observe the status change on the foreground
        // (UI) thread, not the background (pool) thread. _setStatus re-checks
        // Disposed, so a dispose() landing before this runs still aborts the
        // transition — no resurrection, no post-dispose publish.
        this._scheduleForeground(() => {
          try {
            this._setStatus(ConstructionStatus.Destructed);
          } finally {
            this.#inFlight = false;
          }
        });
      });
    } else {
      try {
        this._setStatus(ConstructionStatus.Destructing);
        try {
          this._onDestruct();
        } catch (e) {
          // VMX-007: a throwing destruct hook must not wedge the VM in the
          // transient Destructing state. Roll _status back to the prior settled
          // state (Constructed), then re-throw. The VM is left recoverable.
          this._setStatus(ConstructionStatus.Constructed);
          throw e;
        }
        this._setStatus(ConstructionStatus.Destructed);
      } finally {
        this.#inFlight = false;
      }
    }
  }

  reconstruct(): void {
    requireTransition(this.#status, "reconstruct");

    if (this.#inFlight) {
      throw new StatusTransitionError(this.#status, "reconstruct");
    }
    this.#inFlight = true;

    try {
      this._setStatus(ConstructionStatus.Destructing);
      try {
        this._onDestruct();
      } catch (e) {
        // VMX-007: a failed destruct phase rolls back to Constructed (the state
        // reconstruct started from) so the VM stays recoverable.
        this._setStatus(ConstructionStatus.Constructed);
        throw e;
      }
      this._setStatus(ConstructionStatus.Destructed);

      this._setStatus(ConstructionStatus.Constructing);
      try {
        this._onConstruct();
      } catch (e) {
        // VMX-007: a failed construct phase rolls back to Destructed (the
        // destruct phase already completed) so the VM stays recoverable.
        this._setStatus(ConstructionStatus.Destructed);
        throw e;
      }
      this._setStatus(ConstructionStatus.Constructed);
    } finally {
      this.#inFlight = false;
    }
  }

  dispose(): void {
    if (this.#status === ConstructionStatus.Disposed) return;

    this._setStatus(ConstructionStatus.Disposed);
    try {
      this._onDispose();
    } finally {
      this.#disposeOwnedResources();
    }

    if (!this.#triggersDisposed) {
      this.#triggersDisposed = true;
      this.#statusTrigger.complete();
      if (this.#activePropertyNotifications === 0) {
        this.#propertyChangedSubject.complete();
      } else {
        this.#propertyNotificationTeardownPending = true;
      }
    }

    this.#selectCommand.dispose();
    this.#deselectCommand.dispose();
    this.#selectNextCommand.dispose();
    this.#selectPreviousCommand.dispose();
    this.#reconstructCommand.dispose();
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
    if (this._parent !== null) {
      this._parent.selectChild(this);
    }
  }

  canDeselect(): boolean {
    return this._parent !== null && this._parent.currentChild === this;
  }

  deselect(): void {
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

    this.#hub.send(
      ConstructionStatusChangedMessage.create(this, this.#name, newStatus),
    );

    this._raisePropertyChanged("status");
    this._raisePropertyChanged("isConstructed");

    if (!this.#triggersDisposed) {
      this.#statusTrigger.next();
    }
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

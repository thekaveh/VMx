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
import { Subject, Subscription } from "rxjs";
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
  readonly currentChild: ComponentVMBase | null;
  selectChild(vm: ComponentVMBase): void;
  deselectChild(vm: ComponentVMBase): void;
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
  #isCurrent = false;
  _parent: IParentVM | null = null;

  readonly #propertyChangedSubject = new Subject<string>();
  readonly #statusTrigger = new Subject<void>();
  #triggersDisposed = false;

  readonly #selectCommand: RelayCommand;
  readonly #deselectCommand: RelayCommand;
  readonly #selectNextCommand: RelayCommand;
  readonly #selectPreviousCommand: RelayCommand;
  readonly #reconstructCommand: RelayCommand;
  readonly #commandSubs: Subscription[] = [];

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
    // canExecute report false for any orphan leaf, matching spec CVM-005.
    this.#selectNextCommand = RelayCommand.builder()
      .predicate(() => false)
      .build();

    this.#selectPreviousCommand = RelayCommand.builder()
      .predicate(() => false)
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
    if (this.#isCurrent === value) return;
    this.#isCurrent = value;
    this._raisePropertyChanged("isCurrent");
    this.#hub.send(PropertyChangedMessage.create(this, this.#name, "IsCurrent"));
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
        try {
          this._onConstruct();
          this._setStatus(ConstructionStatus.Constructed);
        } finally {
          this.#inFlight = false;
        }
      });
    } else {
      try {
        this._setStatus(ConstructionStatus.Constructing);
        this._onConstruct();
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
        try {
          this._onDestruct();
          this._setStatus(ConstructionStatus.Destructed);
        } finally {
          this.#inFlight = false;
        }
      });
    } else {
      try {
        this._setStatus(ConstructionStatus.Destructing);
        this._onDestruct();
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
      this._onDestruct();
      this._setStatus(ConstructionStatus.Destructed);

      this._setStatus(ConstructionStatus.Constructing);
      this._onConstruct();
      this._setStatus(ConstructionStatus.Constructed);
    } finally {
      this.#inFlight = false;
    }
  }

  dispose(): void {
    if (this.#status === ConstructionStatus.Disposed) return;

    this._setStatus(ConstructionStatus.Disposed);
    this._onDispose();

    if (!this.#triggersDisposed) {
      this.#triggersDisposed = true;
      this.#statusTrigger.complete();
      this.#propertyChangedSubject.complete();
    }

    for (const sub of this.#commandSubs) sub.unsubscribe();
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

  // ── Internal helpers ─────────────────────────────────────────────────────

  protected _setStatus(newStatus: ConstructionStatus): void {
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

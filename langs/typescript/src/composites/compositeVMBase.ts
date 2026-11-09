/**
 * CompositeVMBase — abstract base for all CompositeVM variants.
 *
 * Extends ComponentVMBase with:
 * - Ordered children list
 * - current selection slot
 * - collectionChanged Observable
 * - Coordinated construct / destruct / dispose for child hierarchy
 * - Batch update support (spec v1.1)
 * - AutoConstructOnAdd support (spec v1.1)
 *
 * See spec/06-composite-vm.md.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import {
  beginParentTransfer,
  captureParentTransferCommit,
  ContainerRollbackError,
  ComponentVMBase,
  ParentTransfer,
} from "../components/componentVMBase.js";
import type { IOwningParentVM } from "../components/componentVMBase.js";
import { disposeBestEffort } from "../components/disposal.js";
import { emittedIndex } from "../collections/emittedIndex.js";
import {
  constructWalk,
  deliverCollectionChanged,
  destructWalk,
  maybeAutoConstruct,
} from "../components/vmContainer.js";
import { ViewModelType } from "../components/types.js";
import type { ChildOrder } from "../components/types.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import {
  makeCollectionChangedEvent,
  BatchUpdateHandle,
} from "../collections/index.js";
import type {
  CollectionChangedEvent,
  IBatchable,
  ISelectableVmCollection,
  ObservableMembershipSource,
} from "../collections/index.js";
import type { Subscription } from "rxjs";

export abstract class CompositeVMBase<VM extends ComponentVMBase>
  extends ComponentVMBase
  implements
    IOwningParentVM,
    IBatchable,
    ISelectableVmCollection<VM>,
    ObservableMembershipSource<VM>
{
  readonly supportsChildSelection = true;
  readonly owner = this;
  readonly #asyncSelection: boolean;
  readonly #autoConstructOnAdd: boolean;
  readonly #destructOrder: ChildOrder;
  protected _children: VM[] = [];
  #current: VM | null = null;
  readonly #collectionChangedSubject = new Subject<CollectionChangedEvent>();
  #populated = false;
  /** Collects the children population started constructing (see `_onConstruct`). */
  #populationJoined: Set<ComponentVMBase> | null = null;
  #batchDepth = 0;
  #batchDirty = false;
  readonly #currentSelector: ((xs: Iterable<VM>) => VM | null) | null;
  readonly #onCurrentChanged: ((vm: VM | null) => void) | null;
  #disposeRequested = false;
  #disposeDeferred = false;
  #membershipTransactionActive = false;
  /**
   * True while this composite's own membership transaction is uncommitted: a
   * child is attached but not admitted, a population is staged, or a transfer
   * detach has not committed. Every selection call fails meanwhile (spec/06
   * §4.3 rule 4, ADR-0173). TypeScript has one thread, so the transaction
   * owner is always the caller.
   */
  #uncommitted = false;
  /** Children attached but not yet admitted (spec/06 §4.3 rule 2). */
  readonly #unadmitted = new Set<VM>();
  /** Active current-publication leases (spec/06 §4.3 rule 5). */
  #activeCurrentPublications = 0;

  constructor(opts: {
    name: string;
    /** Defaults to `""`. */
    hint?: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    asyncSelection?: boolean;
    autoConstructOnAdd?: boolean;
    /** Defaults to `"insertion"` (spec/06 §5, ADR-0161). */
    destructOrder?: ChildOrder;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    currentSelector?: ((xs: Iterable<VM>) => VM | null) | null;
    onCurrentChanged?: ((vm: VM | null) => void) | null;
  }) {
    super(opts);
    this.#asyncSelection = opts.asyncSelection ?? false;
    this.#autoConstructOnAdd = opts.autoConstructOnAdd ?? false;
    this.#destructOrder = opts.destructOrder ?? "insertion";
    this.#currentSelector = opts.currentSelector ?? null;
    this.#onCurrentChanged = opts.onCurrentChanged ?? null;
  }

  get type(): ViewModelType {
    return ViewModelType.Composite;
  }

  // ── IParentVM implementation ──────────────────────────────────────────────

  get currentChild(): ComponentVMBase | null {
    return this.#current;
  }

  get ownerParent(): IOwningParentVM | null {
    return this._parent;
  }

  /**
   * The child `select()` path. Every refusal changes nothing and raises
   * nothing (spec/05 §6, spec/06 §3.1, ADR-0188). An asynchronous delivery
   * checks Constructed again (#1229).
   */
  selectChild(vm: ComponentVMBase): void {
    for (const child of this._children) {
      if (child === vm) {
        if (child.status !== ConstructionStatus.Constructed) return;
        this._setCurrent(child, this.#asyncSelection, true, true);
        return;
      }
    }
  }

  /** The child `deselect()` path; a refusal is silent too (ADR-0188). */
  deselectChild(vm: ComponentVMBase): void {
    if (this.#current === vm) {
      this._setCurrent(null, this.#asyncSelection, false, true);
    }
  }

  /**
   * Rule 9, the dispose clear (spec/06 §4.3, ADR-0189): a child that
   * published Disposed from its own `dispose()` stops being current. It
   * clears only while that child is still current, and it does not run
   * during this composite's own disposal.
   */
  childDisposed(vm: ComponentVMBase): void {
    if (this.#disposePending() || this.status === ConstructionStatus.Disposed) return;
    const current = this.#current;
    if (current !== null && current._ownershipIdentity === vm._ownershipIdentity) {
      this.#commitCurrent(null);
    }
  }

  containsChild(vm: ComponentVMBase): boolean {
    const identity = vm._ownershipIdentity;
    return this._children.some((child) => child._ownershipIdentity === identity);
  }

  detachForTransfer(vm: ComponentVMBase): ParentTransfer {
    this.#beginMembershipTransaction();
    const index = this._children.findIndex((child) => child === vm);
    if (index < 0) {
      this.#endMembershipTransaction();
      throw new Error("Recorded parent does not contain child identity");
    }
    const child = this._children[index] as VM;
    this._children.splice(index, 1);
    this.#uncommitted = true;
    return new ParentTransfer(
      () => {
        this.#uncommitted = false;
        let hasError = false;
        let firstError: unknown;
        try {
          this.#clearDetached([child]);
        } catch (error) {
          hasError = true;
          firstError = error;
        }
        try {
          this._emitCollectionChanged(
            makeCollectionChangedEvent("remove", { oldItems: [child], oldIndex: index }),
          );
        } catch (error) {
          if (!hasError) {
            hasError = true;
            firstError = error;
          }
        }
        try {
          this.#endMembershipTransaction(!hasError);
        } catch (error) {
          if (!hasError) {
            hasError = true;
            firstError = error;
          }
        }
        if (hasError) throw firstError;
      },
      () => {
        try {
          this._children.splice(Math.min(index, this._children.length), 0, child);
          child._parent = this;
        } finally {
          this.#uncommitted = false;
          this.#endMembershipTransaction(false);
        }
      },
    );
  }

  // ── collectionChanged ─────────────────────────────────────────────────────

  get collectionChanged(): Observable<CollectionChangedEvent> {
    return this.#collectionChangedSubject.asObservable();
  }

  // ── current property ──────────────────────────────────────────────────────

  get current(): VM | null {
    return this.#current;
  }

  set current(value: VM | null) {
    this._setCurrent(value, this.#asyncSelection);
  }

  // ── Selection methods ─────────────────────────────────────────────────────

  selectComponent(vm: VM): void {
    // A call that only rule 8 (Destructing) refuses is silent in _setCurrent
    // (spec/06 §3.1, ADR-0188).
    if (!this.#admitsSelectComponent(vm)) {
      throw new Error(
        `Cannot select '${vm.name}': canSelectComponent returned false.`,
      );
    }
    // An asynchronous delivery checks Constructed again (#1220).
    this._setCurrent(vm, this.#asyncSelection, true);
  }

  deselectComponent(vm: VM): void {
    if (this.#current !== vm) {
      throw new Error(
        `Cannot deselect '${vm.name}': it is not the current selection.`,
      );
    }
    this.current = null;
  }

  /**
   * True only if {@link selectComponent} would select `vm` now: `vm` is an
   * admitted, constructed member, no disposal of this composite is pending,
   * this composite is not Destructing, and no membership transaction of this
   * composite is uncommitted (spec/06 §3.1, ADR-0173, ADR-0188).
   */
  canSelectComponent(vm: VM): boolean {
    return this.#admitsSelectComponent(vm) && this.status !== ConstructionStatus.Destructing;
  }

  /** Every `canSelectComponent` check except rule 8 (Destructing). */
  #admitsSelectComponent(vm: VM): boolean {
    return (
      !this.#uncommitted &&
      !this.#disposePending() &&
      this.#isSelectableMember(vm) &&
      vm.status === ConstructionStatus.Constructed
    );
  }

  // ── Collection API ────────────────────────────────────────────────────────

  get count(): number {
    return this._children.length;
  }

  [Symbol.iterator](): Iterator<VM> {
    return this._children[Symbol.iterator]();
  }

  snapshot(): readonly VM[] {
    return [...this._children];
  }

  subscribeMembership(callback: () => void): Subscription {
    return this.#collectionChangedSubject.subscribe(() => callback());
  }

  at(index: number): VM {
    const item = this._children[index];
    if (item === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    return item;
  }

  add(item: VM): void {
    if ((item as unknown) == null) throw new Error("child must not be null");
    this.#beginMembershipTransaction();
    let transfer: ParentTransfer | null = null;
    let attached = false;
    const originalStatus = item.status;
    try {
      transfer = beginParentTransfer(item, this);
      this.#requireTransactionCanContinue();
      this._children.push(item);
      item._parent = this;
      attached = true;
      this.#stage([item]);
      this._maybeAutoConstruct(item);
      this.#requireTransactionCanContinue();
    } catch (error) {
      let compensationError: unknown;
      if (attached) {
        const index = this._children.indexOf(item);
        if (index >= 0) this._children.splice(index, 1);
        if (item._parent === this) item._parent = null;
      }
      if (
        originalStatus === ConstructionStatus.Destructed &&
        item.status === ConstructionStatus.Constructed
      ) {
        try { item.destruct(); } catch (rollbackError) {
          compensationError = rollbackError;
        }
      }
      try {
        transfer?.rollback();
      } finally {
        this.#admit();
        this.#endMembershipTransaction(false);
      }
      if (compensationError !== undefined) {
        throw new ContainerRollbackError(error, compensationError);
      }
      throw error;
    }
    const commitError = captureParentTransferCommit(transfer);
    // Admitted after the old parent's detach commit (COMP-006, spec/06 §4.3 rule 2).
    this.#admit();
    try {
      const idx = this._children.length - 1;
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", {
          newItems: [item],
          newIndex: idx,
        }),
      );
      if (commitError !== undefined) throw commitError;
    } catch (error) {
      this.#endMembershipTransaction(false);
      throw error;
    }
    this.#endMembershipTransaction();
  }

  insert(index: number, item: VM): void {
    if ((item as unknown) == null) throw new Error("child must not be null");
    this.#beginMembershipTransaction();
    // splice would silently normalize/clamp while the emitted newIndex
    // carried the raw argument (spec/21 §3.2); `length` appends.
    if (!Number.isInteger(index) || index < 0 || index > this._children.length) {
      this.#endMembershipTransaction();
      throw new RangeError(`Index ${String(index)} out of range`);
    }
    index = emittedIndex(index);
    let transfer: ParentTransfer | null = null;
    let attached = false;
    const originalStatus = item.status;
    try {
      transfer = beginParentTransfer(item, this);
      this.#requireTransactionCanContinue();
      this._children.splice(index, 0, item);
      item._parent = this;
      attached = true;
      this.#stage([item]);
      this._maybeAutoConstruct(item);
      this.#requireTransactionCanContinue();
    } catch (error) {
      let compensationError: unknown;
      if (attached) {
        const actual = this._children.indexOf(item);
        if (actual >= 0) this._children.splice(actual, 1);
        if (item._parent === this) item._parent = null;
      }
      if (
        originalStatus === ConstructionStatus.Destructed &&
        item.status === ConstructionStatus.Constructed
      ) {
        try { item.destruct(); } catch (rollbackError) {
          compensationError = rollbackError;
        }
      }
      try {
        transfer?.rollback();
      } finally {
        this.#admit();
        this.#endMembershipTransaction(false);
      }
      if (compensationError !== undefined) {
        throw new ContainerRollbackError(error, compensationError);
      }
      throw error;
    }
    const commitError = captureParentTransferCommit(transfer);
    // Admitted after the old parent's detach commit (COMP-006, spec/06 §4.3 rule 2).
    this.#admit();
    try {
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", {
          newItems: [item],
          newIndex: index,
        }),
      );
      if (commitError !== undefined) throw commitError;
    } catch (error) {
      this.#endMembershipTransaction(false);
      throw error;
    }
    this.#endMembershipTransaction();
  }

  remove(item: VM): boolean {
    this.#requireChildAdmission();
    const idx = this._children.indexOf(item);
    if (idx < 0) return false;
    this.removeAt(idx);
    return true;
  }

  removeAt(index: number): void {
    this.#beginMembershipTransaction();
    let item: VM;
    try {
      if (!Number.isInteger(index) || index < 0 || index >= this._children.length) {
        throw new RangeError(`Index ${String(index)} out of range`);
      }
      index = emittedIndex(index);
      item = this._children[index] as VM;
    } catch (error) {
      this.#endMembershipTransaction(false);
      throw error;
    }
    this._children.splice(index, 1);
    if (item._parent === this) item._parent = null;
    this.#publishCommittedMembership([
      () => this.#clearDetached([item]),
      () =>
        this._emitCollectionChanged(
          makeCollectionChangedEvent("remove", {
            oldItems: [item],
            oldIndex: index,
          }),
        ),
    ]);
  }

  /**
   * Publishes a committed membership change. Every step runs even when an
   * earlier one throws (for example a throwing `onCurrentChanged`), so the
   * collection event is never lost; the first failure is rethrown after the
   * membership transaction ends.
   */
  #publishCommittedMembership(
    steps: readonly (() => void)[],
    priorError?: { readonly error: unknown },
  ): void {
    let failure = priorError;
    for (const step of steps) {
      try {
        step();
      } catch (error) {
        failure ??= { error };
      }
    }
    this.#endMembershipTransaction(failure === undefined);
    if (failure !== undefined) throw failure.error;
  }

  /** Replace the child at *index*. Emits a Remove followed by an Add (per spec). */
  setAt(index: number, value: VM): void {
    if ((value as unknown) == null) throw new Error("child must not be null");
    this.#beginMembershipTransaction();
    if (!Number.isInteger(index) || index < 0 || index >= this._children.length) {
      this.#endMembershipTransaction();
      throw new RangeError(`Index ${String(index)} out of range`);
    }
    index = emittedIndex(index);
    const old = this._children[index] as VM;
    let transfer: ParentTransfer | null = null;
    let attached = false;
    const originalStatus = value.status;
    try {
      transfer = beginParentTransfer(value, this);
      this.#requireTransactionCanContinue();
      // `old` keeps this composite as its parent until the commit, which
      // frees it and clears Current in one step. No other container can adopt
      // it while it is still current here (COMP-006), and a rollback can
      // always put it back (#1219).
      this._children[index] = value;
      value._parent = this;
      attached = true;
      this.#stage([value]);
      this._maybeAutoConstruct(value);
      this.#requireTransactionCanContinue();
    } catch (error) {
      let compensationError: unknown;
      if (attached) {
        const actual = this._children.indexOf(value);
        if (actual >= 0) this._children[actual] = old;
        if (value._parent === this) value._parent = null;
      }
      if (
        originalStatus === ConstructionStatus.Destructed &&
        value.status === ConstructionStatus.Constructed
      ) {
        try { value.destruct(); } catch (rollbackError) {
          compensationError = rollbackError;
        }
      }
      try {
        transfer?.rollback();
      } finally {
        this.#admit();
        this.#endMembershipTransaction(false);
      }
      if (compensationError !== undefined) {
        throw new ContainerRollbackError(error, compensationError);
      }
      throw error;
    }
    const commitError = captureParentTransferCommit(transfer);
    // Admitted after the old parent's detach commit (COMP-006, spec/06 §4.3 rule 2).
    this.#admit();
    this.#publishCommittedMembership(
      [
        () => this.#detachClearingCurrent(old),
        () =>
          this._emitCollectionChanged(
            makeCollectionChangedEvent("remove", { oldItems: [old], oldIndex: index }),
          ),
        () =>
          this._emitCollectionChanged(
            makeCollectionChangedEvent("add", { newItems: [value], newIndex: index }),
          ),
      ],
      commitError === undefined ? undefined : { error: commitError },
    );
  }

  clear(): void {
    this.#beginMembershipTransaction();
    const detached = this._children;
    for (const child of detached) {
      if (child._parent === this) child._parent = null;
    }
    this._children = [];
    this.#publishCommittedMembership([
      () => this.#clearDetached(detached),
      () => this._emitCollectionChanged(makeCollectionChangedEvent("reset")),
    ]);
  }

  move(fromIndex: number, toIndex: number): void {
    this.#requireChildAdmission();
    fromIndex = this._validateMoveIndex(fromIndex);
    toIndex = this._validateMoveIndex(toIndex);
    if (fromIndex === toIndex) return;
    const item = this.at(fromIndex);
    this._children.splice(fromIndex, 1);
    this._children.splice(toIndex, 0, item);
    this._emitCollectionChanged(
      makeCollectionChangedEvent("move", {
        newItems: [item],
        newIndex: toIndex,
        oldItems: [item],
        oldIndex: fromIndex,
      }),
    );
  }

  // ── Batch updates (spec v1.1) ─────────────────────────────────────────────

  batchUpdate(): BatchUpdateHandle {
    this.#batchDepth++;
    return new BatchUpdateHandle(this);
  }

  _exitBatch(): void {
    this.#batchDepth--;
    if (this.#batchDepth === 0 && this.#batchDirty) {
      this.#batchDirty = false;
      this.#deliverCollectionChanged(makeCollectionChangedEvent("reset"));
    }
  }

  protected _emitCollectionChanged(event: CollectionChangedEvent): void {
    if (this.#batchDepth > 0) {
      this.#batchDirty = true;
      return;
    }
    this.#deliverCollectionChanged(event);
  }

  // Local subscribers first, then one hub message (see `deliverCollectionChanged`).
  #deliverCollectionChanged(event: CollectionChangedEvent): void {
    deliverCollectionChanged(
      this,
      this.#collectionChangedSubject,
      () => this.#disposeRequested || this.#disposeDeferred,
      event,
    );
  }

  protected _maybeAutoConstruct(child: VM): void {
    maybeAutoConstruct(this, this.#autoConstructOnAdd, child);
  }

  /** Rejects an index outside the children; returns it with -0 as +0 (#769). */
  private _validateMoveIndex(index: number): number {
    if (!Number.isInteger(index) || index < 0 || index >= this._children.length) {
      throw new RangeError(`Move index ${String(index)} out of range`);
    }
    return emittedIndex(index);
  }

  // ── Lifecycle overrides ───────────────────────────────────────────────────

  protected override _onConstruct(): void {
    super._onConstruct();
    // Children whose construct population started are joined, not restarted.
    const joined = new Set<ComponentVMBase>();
    if (!this.#populated) {
      this.#populationJoined = joined;
      try {
        this._populateChildren();
      } finally {
        this.#populationJoined = null;
      }
      this.#populated = true;
    }
    // spec/02 §6: the composite settles only after every child has (a
    // background child defers the composite's terminal status).
    this._transitionChildrenJoining(
      constructWalk(() => this._children, this.#autoConstructOnAdd, joined),
      true,
      () => {
        // Apply the optional initial-current selector (spec/06 §3.2, ADR-0042).
        // The composite is still in Constructing here; every child is Constructed.
        // Selector returning null or an out-of-set value leaves current at its
        // prior value and emits no notification (matches selectComponent semantics).
        if (this.#currentSelector !== null) {
          const initial = this.#currentSelector(this);
          if (initial !== null) this.#applySelectorResult(initial);
        }
      },
      joined,
    );
  }

  protected override _onDestruct(): void {
    // spec/06 §5, ADR-0173 rule 8: the clear opens no transaction and is never
    // refused, so it also runs inside this composite's own transaction and
    // while disposal is deferred (COMP-005).
    if (this.#current !== null) this.#commitCurrent(null);
    // A disposal deferred by the clear's lease runs when the lease ends; a
    // disposed composite begins no child work (spec/02 §2.4).
    if (this.status === ConstructionStatus.Disposed) return;
    // spec/06 §5: children are destructed in the configured order (ADR-0161).
    this._transitionChildren(destructWalk(this._children, this.#destructOrder), false, () => {
      super._onDestruct();
    });
  }

  override dispose(): void {
    if (this.#disposeRequested) return;
    // spec/06 §4.2 and §4.3 rule 5: a disposal requested during a membership
    // transaction or a current publication is deferred. The flag stays set
    // until this call admits the disposal, so no transaction and no non-null
    // selection starts in between.
    if (this.#membershipTransactionActive || this.#activeCurrentPublications > 0) {
      this.#disposeDeferred = true;
      return;
    }
    this.#disposeRequested = true;
    this.#disposeDeferred = false;
    // Dispose cascade (LIFE-013): depth-first dispose each child, in the
    // configured destruct order (ADR-0161), then self.
    disposeBestEffort([
      () => this._beginDisposeCascade(),
      ...destructWalk(this._children, this.#destructOrder).map((child) => () => child.dispose()),
      () => super.dispose(),
    ]);
  }

  protected override _onDispose(): void {
    if (!this.#collectionChangedSubject.closed) {
      this.#collectionChangedSubject.complete();
    }
  }

  // ── Factory hook ──────────────────────────────────────────────────────────

  protected _populateChildren(): void {
    this.#requireChildAdmission();
    // Default: no-op. Subclasses override to evaluate their factory.
  }

  #requireChildAdmission(): void {
    if (this.#disposeRequested || this.#disposeDeferred) {
      throw new Error("Cannot attach a child while the container is disposing");
    }
    if (this.#membershipTransactionActive) {
      throw new Error("Container membership transaction is already in progress");
    }
  }

  #beginMembershipTransaction(): void {
    this.#requireChildAdmission();
    this.#membershipTransactionActive = true;
  }

  #requireTransactionCanContinue(): void {
    if (this.#disposeRequested || this.#disposeDeferred) {
      throw new Error("Cannot attach a child while the container is disposing");
    }
  }

  #endMembershipTransaction(propagateDisposeFailure = true): void {
    this.#membershipTransactionActive = false;
    if (this.#disposeDeferred && this.#activeCurrentPublications === 0) {
      this.#runDeferredDispose(propagateDisposeFailure);
    }
  }

  #endCurrentPublication(propagateDisposeFailure: boolean): void {
    this.#activeCurrentPublications -= 1;
    if (
      this.#activeCurrentPublications === 0 &&
      !this.#membershipTransactionActive &&
      this.#disposeDeferred
    ) {
      this.#runDeferredDispose(propagateDisposeFailure);
    }
  }

  #runDeferredDispose(propagateDisposeFailure: boolean): void {
    try {
      this.dispose();
    } catch (error) {
      if (propagateDisposeFailure) throw error;
    }
  }

  #disposePending(): boolean {
    return this.#disposeRequested || this.#disposeDeferred;
  }

  /** Marks attached children as unadmitted and the transaction as uncommitted. */
  #stage(children: readonly VM[]): void {
    for (const child of children) this.#unadmitted.add(child);
    this.#uncommitted = true;
  }

  /** Admits the staged children, or forgets them on rollback (spec/06 §4.3 rule 2). */
  #admit(): void {
    this.#unadmitted.clear();
    this.#uncommitted = false;
  }

  /**
   * Rule 2: an admitted member that is not Disposed (spec/06 §4.3, ADR-0189).
   * A Disposed child stays a member but is never selectable.
   */
  #isSelectableMember(vm: VM): boolean {
    return (
      vm.status !== ConstructionStatus.Disposed &&
      this._children.includes(vm) &&
      !this.#unadmitted.has(vm)
    );
  }

  /** A child population left pending is joined by the child walk, never restarted. */
  #joinIfPending(child: VM): void {
    if (
      child.status !== ConstructionStatus.Constructed &&
      child.status !== ConstructionStatus.Disposed
    ) this.#populationJoined?.add(child);
  }

  protected _attachPopulation(children: Iterable<VM>): void {
    const candidates = [...children];
    if (new Set(candidates.map((child) => child._ownershipIdentity)).size !== candidates.length) {
      throw new Error(
        "Factory population contains a duplicate child identity (duplicate canonical child identity)",
      );
    }
    this.#beginMembershipTransaction();
    const start = this._children.length;
    const transfers: ParentTransfer[] = [];
    const originalStatuses: ConstructionStatus[] = [];
    try {
      this.#requireTransactionCanContinue();
      for (const child of candidates) {
        const transfer = beginParentTransfer(child, this);
        transfers.push(transfer);
        originalStatuses.push(child.status);
        this._children.push(child);
        child._parent = this;
        this.#stage([child]);
      }

      // Make the entire snapshot visible before any child hook runs.
      for (const child of candidates) {
        if (
          this.status === ConstructionStatus.Constructing &&
          child.status !== ConstructionStatus.Constructed
        ) {
          child.construct();
          this.#joinIfPending(child);
        } else {
          this._maybeAutoConstruct(child);
        }
      }
      this.#requireTransactionCanContinue();
    } catch (error) {
      let compensationError: unknown;
      while (this._children.length > start) {
        const child = this._children.pop();
        const originalStatus = originalStatuses[this._children.length - start];
        if (
          child !== undefined &&
          originalStatus === ConstructionStatus.Destructed &&
          child.status === ConstructionStatus.Constructed
        ) {
          try { child.destruct(); } catch (rollbackError) {
            compensationError ??= rollbackError;
          }
        }
        if (child?._parent === this) child._parent = null;
      }
      try {
        for (const transfer of [...transfers].reverse()) transfer.rollback();
      } finally {
        this.#admit();
        this.#endMembershipTransaction(false);
      }
      if (compensationError !== undefined) {
        throw new ContainerRollbackError(error, compensationError);
      }
      throw error;
    }
    let commitError: Error | undefined;
    for (const transfer of transfers) {
      const error = captureParentTransferCommit(transfer);
      commitError ??= error;
    }
    // Admitted after the old parents' detach commits (COMP-006, spec/06 §4.3 rule 2).
    this.#admit();
    this.#populated = true;
    try {
      candidates.forEach((child) => {
        const index = this._children.findIndex((candidate) => candidate === child);
        if (index >= start) {
          this._emitCollectionChanged(
            makeCollectionChangedEvent("add", { newItems: [child], newIndex: index }),
          );
        }
      });
      if (commitError !== undefined) throw commitError;
    } catch (error) {
      this.#endMembershipTransaction(false);
      throw error;
    }
    this.#endMembershipTransaction();
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  /**
   * The selection calls: the setter, `selectComponent`, `deselectComponent`
   * and the child `select`/`deselect` paths (spec/06 §3, §4.3, ADR-0173).
   * The call opens no membership transaction. It validates now and raises
   * as the synchronous setter does, also with `asyncSel`; the asynchronous
   * delivery validates again and drops silently when no longer valid.
   * `requireConstructed` (`selectComponent` and `selectChild`) makes the
   * delivery also drop a child that is no longer Constructed (#1220, #1229).
   * `silent` (the child paths) drops a refusal instead of raising it
   * (ADR-0188). Rule 8 (Destructing) is always silent.
   */
  protected _setCurrent(
    value: VM | null,
    asyncSel: boolean,
    requireConstructed = false,
    silent = false,
  ): void {
    const refusal = this.#selectionRefusal(value);
    if (refusal !== null) {
      if (silent) return;
      throw refusal;
    }
    // Rule 8: a non-null selection while Destructing changes nothing and
    // raises nothing, so destruct() ends with Current null (ADR-0188).
    if (value !== null && this.status === ConstructionStatus.Destructing) return;
    if (asyncSel) {
      const captured = value;
      this._scheduleForeground(() => this.#deliverSelection(captured, requireConstructed));
    } else {
      this.#commitCurrent(value);
    }
  }

  /** The raising refusals of rules 2, 3 and 4, or null when none applies. */
  #selectionRefusal(value: VM | null): Error | null {
    // Rule 4: the caller owns an uncommitted transaction of this composite.
    if (this.#uncommitted) {
      return new Error("Container membership transaction is already in progress");
    }
    // Rule 3 for a non-null value; after Disposed every call keeps its
    // documented refusal (chapter 01 §4).
    if (
      this.status === ConstructionStatus.Disposed ||
      (value !== null && this.#disposePending())
    ) {
      return new Error("Cannot change the selection while the container is disposing");
    }
    // Rule 2: an attached but unadmitted child, or a Disposed child, is not a
    // member for selection.
    if (value !== null && !this.#isSelectableMember(value)) {
      return new Error(
        `Cannot set current to '${value.name}': it is not a member of this composite.`,
      );
    }
    return null;
  }

  /**
   * Rule 7: an asynchronous delivery revalidates and drops silently. A
   * `selectComponent` or `selectChild` delivery also requires a Constructed
   * child (spec/06 §3.1).
   */
  #deliverSelection(value: VM | null, requireConstructed: boolean): void {
    if (this.#uncommitted || this.status === ConstructionStatus.Disposed) return;
    if (value !== null && (this.#disposePending() || !this.#isSelectableMember(value))) return;
    // Rule 8: a delivery while Destructing is dropped (ADR-0188).
    if (value !== null && this.status === ConstructionStatus.Destructing) return;
    if (value !== null && requireConstructed && value.status !== ConstructionStatus.Constructed) {
      return;
    }
    this.#commitCurrent(value);
  }

  /**
   * The construct walk's non-raising validated assignment (spec/06 §3.2,
   * ADR-0165, ADR-0173): a silent no-op while disposal is pending, inside an
   * uncommitted transaction of this composite, or for a value that is not an
   * admitted member or is Disposed (ADR-0189).
   */
  #applySelectorResult(value: VM): void {
    if (this.#uncommitted || this.#disposePending() || !this.#isSelectableMember(value)) return;
    this.#commitCurrent(value);
  }

  /**
   * Frees a replaced child and clears it as Current in one step (#1219): no
   * other composite can adopt and select it in between, so the clear never
   * resets the flag of a selection elsewhere (COMP-006, spec/06 §4.3 rule 6).
   */
  #detachClearingCurrent(detached: VM): void {
    if (detached._parent === this) detached._parent = null;
    this.#clearDetached([detached]);
  }

  /** Rule 6: a detach clears Current only while a detached child is current. */
  #clearDetached(detached: readonly VM[]): void {
    const current = this.#current;
    if (current !== null && detached.includes(current)) this.#commitCurrent(null);
  }

  /**
   * Commits `current` and both current flags, then publishes them and runs
   * `onCurrentChanged` under the current-publication lease (spec/06 §4.3
   * rules 1 and 5). A dispose() from those callbacks is deferred until the
   * last lease ends and no membership transaction is open.
   */
  #commitCurrent(value: VM | null): void {
    const previous = this.#current;
    if (previous === value) return;
    this.#current = value;
    const previousChanged = previous?._commitIsCurrent(false) ?? false;
    const valueChanged = value?._commitIsCurrent(true) ?? false;
    this.#activeCurrentPublications += 1;
    try {
      if (previousChanged) previous?._publishIsCurrent();
      if (valueChanged) value?._publishIsCurrent();
      this._notifyPropertyChanged("current");
      // Invoke the optional builder-registered onCurrentChanged callback AFTER
      // state update + hub publish + INPC raise so every observer sees the new
      // value consistently (spec/06 §3.2, ADR-0042 §5.2).
      if (this.#onCurrentChanged !== null) this.#onCurrentChanged(value);
    } catch (error) {
      this.#endCurrentPublication(false);
      throw error;
    }
    this.#endCurrentPublication(true);
  }
}

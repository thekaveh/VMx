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
import { ViewModelType } from "../components/types.js";
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
  protected _children: VM[] = [];
  #current: VM | null = null;
  readonly #collectionChangedSubject = new Subject<CollectionChangedEvent>();
  #populated = false;
  #batchDepth = 0;
  #batchDirty = false;
  readonly #currentSelector: ((xs: Iterable<VM>) => VM | null) | null;
  readonly #onCurrentChanged: ((vm: VM | null) => void) | null;
  #disposeRequested = false;
  #disposeDeferred = false;
  #membershipTransactionActive = false;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    asyncSelection?: boolean;
    autoConstructOnAdd?: boolean;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
    currentSelector?: ((xs: Iterable<VM>) => VM | null) | null;
    onCurrentChanged?: ((vm: VM | null) => void) | null;
  }) {
    super(opts);
    this.#asyncSelection = opts.asyncSelection ?? false;
    this.#autoConstructOnAdd = opts.autoConstructOnAdd ?? false;
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

  selectChild(vm: ComponentVMBase): void {
    for (const child of this._children) {
      if (child === vm) {
        this._setCurrent(child, this.#asyncSelection);
        return;
      }
    }
  }

  deselectChild(vm: ComponentVMBase): void {
    if (this.#current === vm) {
      this._setCurrent(null, this.#asyncSelection);
    }
  }

  containsChild(vm: ComponentVMBase): boolean {
    return this._children.some((child) => child === vm);
  }

  detachForTransfer(vm: ComponentVMBase): ParentTransfer {
    this.#beginMembershipTransaction();
    const index = this._children.findIndex((child) => child === vm);
    if (index < 0) {
      this.#endMembershipTransaction();
      throw new Error("Recorded parent does not contain child identity");
    }
    const child = this._children[index] as VM;
    const wasCurrent = this.#current === child;
    this._children.splice(index, 1);
    return new ParentTransfer(
      () => {
        try {
          if (wasCurrent) this._applyCurrentChange(null, true);
          this._emitCollectionChanged(
            makeCollectionChangedEvent("remove", { oldItems: [child], oldIndex: index }),
          );
        } finally {
          this.#endMembershipTransaction();
        }
      },
      () => {
        try {
          this._children.splice(Math.min(index, this._children.length), 0, child);
          child._parent = this;
        } finally {
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
    if (!this.canSelectComponent(vm)) {
      throw new Error(
        `Cannot select '${vm.name}': canSelectComponent returned false.`,
      );
    }
    this.current = vm;
  }

  deselectComponent(vm: VM): void {
    if (this.#current !== vm) {
      throw new Error(
        `Cannot deselect '${vm.name}': it is not the current selection.`,
      );
    }
    this.current = null;
  }

  canSelectComponent(vm: VM): boolean {
    return (
      this._children.includes(vm) &&
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
    this.#beginMembershipTransaction();
    let transfer: ParentTransfer | null = null;
    let attached = false;
    try {
      transfer = beginParentTransfer(item, this);
      this.#requireTransactionCanContinue();
      this._children.push(item);
      item._parent = this;
      attached = true;
      this._maybeAutoConstruct(item);
      this.#requireTransactionCanContinue();
    } catch (error) {
      if (attached) {
        const index = this._children.indexOf(item);
        if (index >= 0) this._children.splice(index, 1);
        if (item._parent === this) item._parent = null;
      }
      try {
        transfer?.rollback();
      } finally {
        this.#endMembershipTransaction();
      }
      throw error;
    }
    const commitError = captureParentTransferCommit(transfer);
    try {
      const idx = this._children.length - 1;
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", {
          newItems: [item],
          newIndex: idx,
        }),
      );
      if (commitError !== undefined) throw commitError;
    } finally {
      this.#endMembershipTransaction();
    }
  }

  insert(index: number, item: VM): void {
    this.#beginMembershipTransaction();
    // splice would silently normalize/clamp while the emitted newIndex
    // carried the raw argument (spec/21 §3.2); `length` appends.
    if (index < 0 || index > this._children.length) {
      this.#endMembershipTransaction();
      throw new RangeError(`Index ${String(index)} out of range`);
    }
    let transfer: ParentTransfer | null = null;
    let attached = false;
    try {
      transfer = beginParentTransfer(item, this);
      this.#requireTransactionCanContinue();
      this._children.splice(index, 0, item);
      item._parent = this;
      attached = true;
      this._maybeAutoConstruct(item);
      this.#requireTransactionCanContinue();
    } catch (error) {
      if (attached) {
        const actual = this._children.indexOf(item);
        if (actual >= 0) this._children.splice(actual, 1);
        if (item._parent === this) item._parent = null;
      }
      try {
        transfer?.rollback();
      } finally {
        this.#endMembershipTransaction();
      }
      throw error;
    }
    const commitError = captureParentTransferCommit(transfer);
    try {
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", {
          newItems: [item],
          newIndex: index,
        }),
      );
      if (commitError !== undefined) throw commitError;
    } finally {
      this.#endMembershipTransaction();
    }
  }

  remove(item: VM): boolean {
    this.#requireChildAdmission();
    const idx = this._children.indexOf(item);
    if (idx < 0) return false;
    this.removeAt(idx);
    return true;
  }

  removeAt(index: number): void {
    this.#requireChildAdmission();
    if (index < 0 || index >= this._children.length) {
      throw new RangeError(`Index ${String(index)} out of range`);
    }
    const item = this._children[index] as VM;
    this._children.splice(index, 1);
    if (item._parent === this) item._parent = null;
    if (this.#current === item) {
      this._applyCurrentChange(null, true);
    }
    this._emitCollectionChanged(
      makeCollectionChangedEvent("remove", {
        oldItems: [item],
        oldIndex: index,
      }),
    );
  }

  /** Replace the child at *index*. Emits a Remove followed by an Add (per spec). */
  setAt(index: number, value: VM): void {
    this.#beginMembershipTransaction();
    if (index < 0 || index >= this._children.length) {
      this.#endMembershipTransaction();
      throw new RangeError(`Index ${String(index)} out of range`);
    }
    const old = this._children[index] as VM;
    let transfer: ParentTransfer | null = null;
    let attached = false;
    try {
      transfer = beginParentTransfer(value, this);
      this.#requireTransactionCanContinue();
      this._children[index] = value;
      old._parent = null;
      value._parent = this;
      attached = true;
      this._maybeAutoConstruct(value);
      this.#requireTransactionCanContinue();
    } catch (error) {
      if (attached) {
        const actual = this._children.indexOf(value);
        if (actual >= 0) this._children[actual] = old;
        old._parent = this;
        if (value._parent === this) value._parent = null;
      }
      try {
        transfer?.rollback();
      } finally {
        this.#endMembershipTransaction();
      }
      throw error;
    }
    const commitError = captureParentTransferCommit(transfer);
    try {
      if (this.#current === old) this._applyCurrentChange(null, true);
      this._emitCollectionChanged(
        makeCollectionChangedEvent("remove", { oldItems: [old], oldIndex: index }),
      );
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", { newItems: [value], newIndex: index }),
      );
      if (commitError !== undefined) throw commitError;
    } finally {
      this.#endMembershipTransaction();
    }
  }

  clear(): void {
    this.#requireChildAdmission();
    for (const child of this._children) {
      if (child._parent === this) child._parent = null;
    }
    this._children = [];
    // Route through _setCurrent (mirrors C# Clear / removeAt): a bare
    // `this.#current = null` left the old current child's isCurrent true
    // and skipped the "current" property notification.
    this._setCurrent(null, false);
    this._emitCollectionChanged(makeCollectionChangedEvent("reset"));
  }

  move(fromIndex: number, toIndex: number): void {
    this.#requireChildAdmission();
    this._validateMoveIndex(fromIndex);
    this._validateMoveIndex(toIndex);
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
      this.#collectionChangedSubject.next(makeCollectionChangedEvent("reset"));
    }
  }

  protected _emitCollectionChanged(event: CollectionChangedEvent): void {
    if (this.#batchDepth > 0) {
      this.#batchDirty = true;
      return;
    }
    this.#collectionChangedSubject.next(event);
  }

  protected _maybeAutoConstruct(child: VM): void {
    if (!this.#autoConstructOnAdd) return;
    if (this.status !== ConstructionStatus.Constructed) return;
    if (child.status === ConstructionStatus.Constructed) return;
    child.construct();
  }

  private _validateMoveIndex(index: number): void {
    if (!Number.isInteger(index) || index < 0 || index >= this._children.length) {
      throw new RangeError(`Move index ${String(index)} out of range`);
    }
  }

  // ── Lifecycle overrides ───────────────────────────────────────────────────

  protected override _onConstruct(): void {
    super._onConstruct();
    if (!this.#populated) {
      this._populateChildren();
      this.#populated = true;
    }
    for (const child of [...this._children]) {
      child.construct();
    }
    // Apply the optional initial-current selector (spec/06 §3.2, ADR-0042).
    // The composite is still in Constructing here; every child is Constructed.
    // Selector returning null or an out-of-set value leaves current at its
    // prior value and emits no notification (matches selectComponent semantics).
    if (this.#currentSelector !== null) {
      const initial = this.#currentSelector(this);
      if (initial !== null && this._children.includes(initial)) {
        this._setCurrent(initial, false);
      }
    }
  }

  protected override _onDestruct(): void {
    if (this.#current !== null) {
      this._setCurrent(null, false);
    }
    for (const child of [...this._children]) {
      child.destruct();
    }
    super._onDestruct();
  }

  override dispose(): void {
    if (this.#disposeRequested || this.#disposeDeferred) return;
    if (this.#membershipTransactionActive) {
      this.#disposeDeferred = true;
      return;
    }
    this.#disposeRequested = true;
    // Dispose cascade (LIFE-013): depth-first dispose each child, then self.
    disposeBestEffort([
      ...[...this._children].map((child) => () => child.dispose()),
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
    if (this.#disposeDeferred) {
      this.#disposeDeferred = false;
      try {
        this.dispose();
      } catch (error) {
        if (propagateDisposeFailure) throw error;
      }
    }
  }

  protected _attachPopulation(children: Iterable<VM>): void {
    const candidates = [...children];
    if (new Set(candidates).size !== candidates.length) {
      throw new Error("Factory population contains a duplicate child identity");
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
      }

      // Make the entire snapshot visible before any child hook runs.
      for (const child of candidates) {
        this._maybeAutoConstruct(child);
        if (
          this.status === ConstructionStatus.Constructing &&
          child.status !== ConstructionStatus.Constructed
        ) child.construct();
      }
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
        this.#endMembershipTransaction();
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
    } finally {
      this.#endMembershipTransaction();
    }
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  protected _setCurrent(value: VM | null, asyncSel: boolean): void {
    this.#requireChildAdmission();
    if (value !== null && !this._children.includes(value)) {
      throw new Error(
        `Cannot set current to '${value.name}': it is not a member of this composite.`,
      );
    }
    if (asyncSel) {
      const captured = value;
      this._scheduleForeground(() => this._applyCurrentChange(captured));
    } else {
      this._applyCurrentChange(value);
    }
  }

  private _applyCurrentChange(value: VM | null, internalTransaction = false): void {
    // Async TOCTOU guard: with async selection the child may have been removed
    // between _setCurrent's membership check and this deferred foreground
    // delivery. Dropping silently upholds the spec/06 §3 invariant that a
    // non-null current is always a member of the children collection.
    if (this.#membershipTransactionActive && !internalTransaction) return;
    if (value !== null && !this._children.includes(value)) return;
    if (this.#current === value) return;

    const previous = this.#current;
    this.#current = value;

    if (previous !== null) previous._setIsCurrent(false);
    if (value !== null) value._setIsCurrent(true);

    this._notifyPropertyChanged("current");

    // Invoke the optional builder-registered onCurrentChanged callback AFTER
    // state update + hub publish + INPC raise so every observer sees the new
    // value consistently (spec/06 §3.2, ADR-0042 §5.2).
    if (this.#onCurrentChanged !== null) {
      this.#onCurrentChanged(value);
    }
  }
}

/**
 * GroupVM<VM> — ordered peer-child container viewmodel (no selection slot).
 *
 * See spec/07-group-vm.md.
 */
import { Subject } from "rxjs";
import type { Observable, Subscription } from "rxjs";
import {
  beginParentTransfer,
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
import { BuilderValidationError } from "../builders/exceptions.js";

const optionHub = Symbol("optionHub");
const optionDispatcher = Symbol("optionDispatcher");
import {
  makeCollectionChangedEvent,
  BatchUpdateHandle,
} from "../collections/index.js";
import type {
  CollectionChangedEvent,
  IBatchable,
  IVmCollection,
  ObservableMembershipSource,
} from "../collections/index.js";

/** GroupVM parent adaptor — no selection concept. */
class GroupParent<VM extends ComponentVMBase> implements IOwningParentVM {
  constructor(private readonly group: GroupVM<VM>) {}

  readonly supportsChildSelection = false;
  readonly currentChild = null;
  get owner(): ComponentVMBase { return this.group; }
  get ownerParent(): IOwningParentVM | null { return this.group._parent; }
  selectChild(_vm: ComponentVMBase): void { /* no-op */ }
  deselectChild(_vm: ComponentVMBase): void { /* no-op */ }
  containsChild(vm: ComponentVMBase): boolean {
    return this.group._containsIdentity(vm);
  }
  detachForTransfer(vm: ComponentVMBase): ParentTransfer {
    return this.group._detachForTransfer(vm);
  }
}

export class GroupVM<VM extends ComponentVMBase>
  extends ComponentVMBase
  implements IBatchable, IVmCollection<VM>, ObservableMembershipSource<VM>
{
  readonly #autoConstructOnAdd: boolean;
  readonly #childrenFactory: (() => Iterable<VM>) | null;
  protected _children: VM[] = [];
  #populated = false;
  #batchDepth = 0;
  #disposeRequested = false;
  #disposeDeferred = false;
  #membershipTransactionActive = false;
  #batchDirty = false;
  readonly #collectionChangedSubject = new Subject<CollectionChangedEvent>();
  readonly #groupParent: GroupParent<VM>;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    autoConstructOnAdd?: boolean;
    childrenFactory?: (() => Iterable<VM>) | null;
    onConstruct?: (() => void) | null;
    onDestruct?: (() => void) | null;
  }) {
    super(opts);
    this.#groupParent = new GroupParent(this);
    this.#autoConstructOnAdd = opts.autoConstructOnAdd ?? false;
    this.#childrenFactory = opts.childrenFactory ?? null;
  }

  get type(): ViewModelType {
    return ViewModelType.Group;
  }

  // ── collectionChanged ─────────────────────────────────────────────────────

  get collectionChanged(): Observable<CollectionChangedEvent> {
    return this.#collectionChangedSubject.asObservable();
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
    const idx = this._children.length;
    let transfer: ParentTransfer | null = null;
    let attached = false;
    try {
      transfer = beginParentTransfer(item, this.#groupParent);
      this.#requireTransactionCanContinue();
      this._children.push(item);
      item._parent = this.#groupParent;
      attached = true;
      this._maybeAutoConstruct(item);
      this.#requireTransactionCanContinue();
    } catch (error) {
      if (attached) {
        const index = this._children.indexOf(item);
        if (index >= 0) this._children.splice(index, 1);
        if (item._parent === this.#groupParent) item._parent = null;
      }
      try { transfer?.rollback(); } finally { this.#endMembershipTransaction(); }
      throw error;
    }
    try {
      transfer.commit();
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", { newItems: [item], newIndex: idx }),
      );
    } finally { this.#endMembershipTransaction(); }
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
      transfer = beginParentTransfer(item, this.#groupParent);
      this.#requireTransactionCanContinue();
      this._children.splice(index, 0, item);
      item._parent = this.#groupParent;
      attached = true;
      this._maybeAutoConstruct(item);
      this.#requireTransactionCanContinue();
    } catch (error) {
      if (attached) {
        const actual = this._children.indexOf(item);
        if (actual >= 0) this._children.splice(actual, 1);
        if (item._parent === this.#groupParent) item._parent = null;
      }
      try { transfer?.rollback(); } finally { this.#endMembershipTransaction(); }
      throw error;
    }
    try {
      transfer.commit();
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", { newItems: [item], newIndex: index }),
      );
    } finally { this.#endMembershipTransaction(); }
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
    const item = this._children[index];
    if (item === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    this._children.splice(index, 1);
    if (item._parent === this.#groupParent) item._parent = null;
    this._emitCollectionChanged(
      makeCollectionChangedEvent("remove", { oldItems: [item], oldIndex: index }),
    );
  }

  /** Replace the child at *index*. Emits a Remove followed by an Add (per spec). */
  setAt(index: number, value: VM): void {
    this.#beginMembershipTransaction();
    const old = this._children[index];
    if (old === undefined) {
      this.#endMembershipTransaction();
      throw new RangeError(`Index ${String(index)} out of range`);
    }
    let transfer: ParentTransfer | null = null;
    let attached = false;
    try {
      transfer = beginParentTransfer(value, this.#groupParent);
      this.#requireTransactionCanContinue();
      this._children[index] = value;
      old._parent = null;
      value._parent = this.#groupParent;
      attached = true;
      this._maybeAutoConstruct(value);
      this.#requireTransactionCanContinue();
    } catch (error) {
      if (attached) {
        const actual = this._children.indexOf(value);
        if (actual >= 0) this._children[actual] = old;
        old._parent = this.#groupParent;
        if (value._parent === this.#groupParent) value._parent = null;
      }
      try { transfer?.rollback(); } finally { this.#endMembershipTransaction(); }
      throw error;
    }
    try {
      transfer.commit();
      this._emitCollectionChanged(
        makeCollectionChangedEvent("remove", { oldItems: [old], oldIndex: index }),
      );
      this._emitCollectionChanged(
        makeCollectionChangedEvent("add", { newItems: [value], newIndex: index }),
      );
    } finally { this.#endMembershipTransaction(); }
  }

  clear(): void {
    this.#requireChildAdmission();
    for (const child of this._children) {
      if (child._parent === this.#groupParent) child._parent = null;
    }
    this._children = [];
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

  /** @internal */
  _containsIdentity(vm: ComponentVMBase): boolean {
    return this._children.some((child) => child === vm);
  }

  /** @internal */
  _detachForTransfer(vm: ComponentVMBase): ParentTransfer {
    this.#beginMembershipTransaction();
    const index = this._children.findIndex((child) => child === vm);
    if (index < 0) {
      this.#endMembershipTransaction();
      throw new Error("Recorded parent does not contain child identity");
    }
    const child = this._children[index] as VM;
    this._children.splice(index, 1);
    return new ParentTransfer(
      () => {
        try {
          this._emitCollectionChanged(
            makeCollectionChangedEvent("remove", { oldItems: [child], oldIndex: index }),
          );
        } finally { this.#endMembershipTransaction(); }
      },
      () => {
        try {
          this._children.splice(Math.min(index, this._children.length), 0, child);
          child._parent = this.#groupParent;
        } finally { this.#endMembershipTransaction(); }
      },
    );
  }

  private _maybeAutoConstruct(child: VM): void {
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
    this._populateChildren();
    // Snapshot (parity with CompositeVMBase and dispose below): a child
    // lifecycle hook that mutates the group must not skip/repeat siblings.
    for (const child of [...this._children]) {
      child.construct();
    }
  }

  protected override _onDestruct(): void {
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

  #endMembershipTransaction(): void {
    this.#membershipTransactionActive = false;
    if (this.#disposeDeferred) {
      this.#disposeDeferred = false;
      this.dispose();
    }
  }

  private _populateChildren(): void {
    if (this.#populated || this.#childrenFactory === null) return;
    const children = [...this.#childrenFactory()];
    if (new Set(children).size !== children.length) {
      throw new Error("Factory population contains a duplicate child identity");
    }
    this.#beginMembershipTransaction();
    const start = this._children.length;
    const transfers: ParentTransfer[] = [];
    const originalStatuses: ConstructionStatus[] = [];
    try {
      this.#requireTransactionCanContinue();
      for (const child of children) {
        const transfer = beginParentTransfer(child, this.#groupParent);
        transfers.push(transfer);
        originalStatuses.push(child.status);
        this._children.push(child);
        child._parent = this.#groupParent;
      }

      // Make the entire factory snapshot visible before any child hook runs,
      // matching composite population and the other flavors.
      for (const child of children) {
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
        if (child?._parent === this.#groupParent) child._parent = null;
      }
      try {
        for (const transfer of [...transfers].reverse()) transfer.rollback();
      } finally { this.#endMembershipTransaction(); }
      if (compensationError !== undefined) {
        throw new ContainerRollbackError(error, compensationError);
      }
      throw error;
    }
    try {
      for (const transfer of transfers) transfer.commit();
      children.forEach((child, offset) => {
        this._emitCollectionChanged(
          makeCollectionChangedEvent("add", {
            newItems: [child],
            newIndex: start + offset,
          }),
        );
      });
      this.#populated = true;
    } finally { this.#endMembershipTransaction(); }
  }

  static builder<VM extends ComponentVMBase>(): GroupVMBuilder<VM> {
    return new GroupVMBuilder<VM>();
  }

  /**
   * Constructs a {@link GroupVM} from an options object in a single call — an
   * additive alternative to the fluent {@link GroupVMBuilder}. Delegates to that
   * builder, so the required-field validation ({@link BuilderValidationError} on
   * a missing name/services/children) and the resulting VM are identical to the
   * fluent path.
   */
  static create<VM extends ComponentVMBase>(options: GroupVMOptions<VM>): GroupVM<VM> {
    // Widen to Partial so the required-field guards remain meaningful for JS
    // callers / casts that bypass the type; validation is delegated to build().
    const o = options as Partial<GroupVMOptions<VM>>;
    let b = new GroupVMBuilder<VM>();
    if (o.children !== undefined) b = b.children(o.children);
    if (o.name !== undefined) b = b.name(o.name);
    if (o.hint !== undefined) b = b.hint(o.hint);
    if (o.hub !== undefined) b = b[optionHub](o.hub);
    if (o.dispatcher !== undefined) b = b[optionDispatcher](o.dispatcher);
    if (o.autoConstructOnAdd !== undefined) b = b.autoConstructOnAdd(o.autoConstructOnAdd);
    if (o.onConstruct !== undefined) b = b.onConstruct(o.onConstruct);
    if (o.onDestruct !== undefined) b = b.onDestruct(o.onDestruct);
    return b.build();
  }
}

/**
 * Options for the additive {@link GroupVM.create} construction form
 * (ADR-0055 / VMX-020). A one-call alternative to the fluent
 * {@link GroupVMBuilder}.
 */
export interface GroupVMOptions<VM extends ComponentVMBase> {
  /** Required VM name. */
  name: string;
  /** Required message hub. */
  hub: IMessageHub;
  /** Required dispatcher. */
  dispatcher: IDispatcher;
  /** Required children factory (invoked lazily on construct; `() => []` for empty). */
  children: () => Iterable<VM>;
  /** Optional hint (default: ""). */
  hint?: string;
  /** Optional auto-construct-on-add flag (default: false). */
  autoConstructOnAdd?: boolean;
  /** Optional OnConstruct lifecycle callback. */
  onConstruct?: () => void;
  /** Optional OnDestruct lifecycle callback. */
  onDestruct?: () => void;
}

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

export class GroupVMBuilder<VM extends ComponentVMBase> {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #autoConstructOnAdd = false;
  #childrenFactory: (() => Iterable<VM>) | null = null;
  #onConstruct: (() => void) | null = null;
  #onDestruct: (() => void) | null = null;

  constructor(from?: GroupVMBuilder<VM>) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#autoConstructOnAdd = from.#autoConstructOnAdd;
      this.#childrenFactory = from.#childrenFactory;
      this.#onConstruct = from.#onConstruct;
      this.#onDestruct = from.#onDestruct;
    }
  }

  name(value: string): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#name = value;
    return b;
  }

  hint(value: string): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  [optionHub](hub: IMessageHub): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#hub = hub;
    return b;
  }

  [optionDispatcher](dispatcher: IDispatcher): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#dispatcher = dispatcher;
    return b;
  }

  autoConstructOnAdd(value: boolean): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#autoConstructOnAdd = value;
    return b;
  }

  children(factory: () => Iterable<VM>): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#childrenFactory = factory;
    return b;
  }

  onConstruct(cb: () => void): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#onConstruct = cb;
    return b;
  }

  onDestruct(cb: () => void): GroupVMBuilder<VM> {
    const b = new GroupVMBuilder<VM>(this);
    b.#onDestruct = cb;
    return b;
  }

  build(): GroupVM<VM> {
    if (this.#name === null) throw new BuilderValidationError("name");
    if (this.#hub === null || this.#dispatcher === null)
      throw new BuilderValidationError("services");
    if (this.#childrenFactory === null)
      throw new BuilderValidationError("children");
    return new GroupVM<VM>({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      autoConstructOnAdd: this.#autoConstructOnAdd,
      childrenFactory: this.#childrenFactory,
      onConstruct: this.#onConstruct,
      onDestruct: this.#onDestruct,
    });
  }
}

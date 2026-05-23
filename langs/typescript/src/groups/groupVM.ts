/**
 * GroupVM<VM> — ordered peer-child container viewmodel (no selection slot).
 *
 * See spec/07-group-vm.md.
 */
import { Subject } from "rxjs";
import type { Observable } from "rxjs";
import { ComponentVMBase } from "../components/componentVMBase.js";
import type { IParentVM } from "../components/componentVMBase.js";
import { ViewModelType } from "../components/types.js";
import { ConstructionStatus } from "../lifecycle/status.js";
import type { IMessageHub } from "../services/messageHub.js";
import type { IDispatcher } from "../services/dispatcher.js";
import {
  makeCollectionChangedEvent,
  BatchUpdateHandle,
} from "../collections/index.js";
import type { CollectionChangedEvent, IBatchable } from "../collections/index.js";

/** GroupVM parent adaptor — no selection concept. */
class GroupParent implements IParentVM {
  readonly currentChild = null;
  selectChild(_vm: ComponentVMBase): void { /* no-op */ }
  deselectChild(_vm: ComponentVMBase): void { /* no-op */ }
}

export class GroupVM<VM extends ComponentVMBase>
  extends ComponentVMBase
  implements IBatchable
{
  readonly #autoConstructOnAdd: boolean;
  readonly #childrenFactory: (() => Iterable<VM>) | null;
  protected _children: VM[] = [];
  #populated = false;
  #batchDepth = 0;
  #batchDirty = false;
  readonly #collectionChangedSubject = new Subject<CollectionChangedEvent>();
  readonly #groupParent = new GroupParent();

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

  at(index: number): VM {
    const item = this._children[index];
    if (item === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    return item;
  }

  add(item: VM): void {
    const idx = this._children.length;
    this._children.push(item);
    item._parent = this.#groupParent;
    this._maybeAutoConstruct(item);
    this._emitCollectionChanged(
      makeCollectionChangedEvent("add", { newItems: [item], newIndex: idx }),
    );
  }

  insert(index: number, item: VM): void {
    this._children.splice(index, 0, item);
    item._parent = this.#groupParent;
    this._maybeAutoConstruct(item);
    this._emitCollectionChanged(
      makeCollectionChangedEvent("add", { newItems: [item], newIndex: index }),
    );
  }

  remove(item: VM): boolean {
    const idx = this._children.indexOf(item);
    if (idx < 0) return false;
    this.removeAt(idx);
    return true;
  }

  removeAt(index: number): void {
    const item = this._children[index];
    if (item === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    this._children.splice(index, 1);
    item._parent = null;
    this._emitCollectionChanged(
      makeCollectionChangedEvent("remove", { oldItems: [item], oldIndex: index }),
    );
  }

  /** Replace the child at *index*. Emits a Remove followed by an Add (per spec). */
  setAt(index: number, value: VM): void {
    const old = this._children[index];
    if (old === undefined) throw new RangeError(`Index ${String(index)} out of range`);
    this._children[index] = value;
    old._parent = null;
    value._parent = this.#groupParent;
    this._emitCollectionChanged(
      makeCollectionChangedEvent("remove", { oldItems: [old], oldIndex: index }),
    );
    this._maybeAutoConstruct(value);
    this._emitCollectionChanged(
      makeCollectionChangedEvent("add", { newItems: [value], newIndex: index }),
    );
  }

  clear(): void {
    for (const child of this._children) {
      child._parent = null;
    }
    this._children = [];
    this._emitCollectionChanged(makeCollectionChangedEvent("reset"));
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

  private _emitCollectionChanged(event: CollectionChangedEvent): void {
    if (this.#batchDepth > 0) {
      this.#batchDirty = true;
      return;
    }
    this.#collectionChangedSubject.next(event);
  }

  private _maybeAutoConstruct(child: VM): void {
    if (!this.#autoConstructOnAdd) return;
    if (this.status !== ConstructionStatus.Constructed) return;
    if (child.status === ConstructionStatus.Constructed) return;
    child.construct();
  }

  // ── Lifecycle overrides ───────────────────────────────────────────────────

  protected override _onConstruct(): void {
    super._onConstruct();
    this._populateChildren();
    for (const child of this._children) {
      child.construct();
    }
  }

  protected override _onDestruct(): void {
    for (const child of this._children) {
      child.destruct();
    }
    super._onDestruct();
  }

  override dispose(): void {
    for (const child of [...this._children]) {
      child.dispose();
    }
    super.dispose();
  }

  protected override _onDispose(): void {
    if (!this.#collectionChangedSubject.closed) {
      this.#collectionChangedSubject.complete();
    }
  }

  private _populateChildren(): void {
    if (this.#populated || this.#childrenFactory === null) return;
    this.#populated = true;
    for (const child of this.#childrenFactory()) {
      this.add(child);
    }
  }

  static builder<VM extends ComponentVMBase>(): GroupVMBuilder<VM> {
    return new GroupVMBuilder<VM>();
  }
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
    if (this.#name === null) throw new Error("BuilderValidationError: name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("BuilderValidationError: services (hub, dispatcher) are required");
    if (this.#childrenFactory === null)
      throw new Error("BuilderValidationError: children factory is required");
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
